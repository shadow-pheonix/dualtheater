"""Local JSON IPC. The mpv control pipe is never exposed over the network."""
import itertools
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid


class OverlappedPipe:
    """Windows duplex pipes require independent overlapped reads and writes.

    CPython's _winapi provides the same primitives used by multiprocessing.
    A synchronous file handle deadlocks when a reader is waiting as we write.
    """
    def __init__(self, path):
        import _winapi
        self.api = _winapi
        self.closed = False
        self.handle = _winapi.CreateFile(path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                                         0, 0, _winapi.OPEN_EXISTING,
                                         _winapi.FILE_FLAG_OVERLAPPED, 0)

    def read(self, size):
        ov, error = self.api.ReadFile(self.handle, size, overlapped=True)
        if error == self.api.ERROR_IO_PENDING:
            while self.api.WaitForSingleObject(ov.event, 500) == self.api.WAIT_TIMEOUT:
                if self.closed:
                    ov.cancel()
                    ov.GetOverlappedResult(True)
                    return b''
        count, error = ov.GetOverlappedResult(True)
        if error not in (0, self.api.ERROR_MORE_DATA):
            raise OSError(error, 'mpv pipe read failed')
        return ov.getbuffer()[:count]

    def write(self, data):
        ov, error = self.api.WriteFile(self.handle, data, overlapped=True)
        if error == self.api.ERROR_IO_PENDING and self.api.WaitForSingleObject(ov.event, 3000) == self.api.WAIT_TIMEOUT:
            ov.cancel()
            ov.GetOverlappedResult(True)
            raise TimeoutError('mpv pipe write timed out')
        count, error = ov.GetOverlappedResult(True)
        if error or count != len(data):
            raise OSError(error, 'mpv pipe write failed')
        return count

    def close(self):
        if not self.closed:
            self.closed = True
            self.api.CloseHandle(self.handle)


class Mpv:
    def __init__(self, executable, device, log_dir, diagnostic=False):
        self.executable = str(executable)
        self.device = device
        self.log_dir = Path(log_dir)
        self.diagnostic = diagnostic
        self.proc = self.pipe = None
        self.pending = {}
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.events = queue.Queue()
        self.restarts = 0

    def launch(self):
        if os.name != 'nt':
            raise RuntimeError('The audio host requires Windows WASAPI')
        pipe = r'\\.\pipe\dualtheater-' + uuid.uuid4().hex
        self.log_dir.mkdir(parents=True, exist_ok=True)
        args = [self.executable, '--no-config', '--idle=yes', '--vid=no', '--sid=no',
                '--audio-display=no', '--pause=yes', '--keep-open=yes', '--speed=1',
                '--audio-pitch-correction=no', '--audio-spdif=truehd',
                '--audio-exclusive=yes', '--ao=wasapi', '--audio-fallback-to-null=no',
                '--audio-file-auto=no', '--autoload-files=no', '--osc=no',
                '--ordered-chapters=no', '--access-references=no',
                '--input-default-bindings=no', '--input-vo-keyboard=no',
                '--script=' + str(Path(__file__).with_name('select_audio.lua')),
                '--input-ipc-server=' + pipe,
                '--log-file=' + str(self.log_dir / 'mpv.log')]
        if self.device:
            args.append('--audio-device=' + self.device)
        # Passthrough is selected separately by --audio-spdif. Reject regular
        # decoders so a failed passthrough attempt cannot fall back to PCM.
        if not self.diagnostic:
            args.append('--ad=-')
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError('mpv exited; see logs/mpv.log')
            try:
                self.pipe = OverlappedPipe(pipe)
                break
            except OSError:
                time.sleep(.05)
        if self.pipe is None:
            self.close()
            raise TimeoutError('mpv IPC did not open')
        threading.Thread(target=self._read, daemon=True).start()
        self.command('get_property', 'mpv-version')
        self.command('set_property', 'user-data/dualtheater-diagnostic', self.diagnostic)

    def _read(self):
        try:
            buffer = bytearray()
            while True:
                chunk = self.pipe.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while b'\n' in buffer:
                    raw, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)
                    msg = json.loads(raw)
                    with self.lock:
                        waiter = self.pending.get(msg.get('request_id'))
                    if waiter:
                        waiter.put(msg)
                    elif msg.get('event') == 'playback-restart':
                        self.restarts += 1
                    elif msg.get('event') in ('end-file', 'shutdown', 'file-loaded'):
                        self.events.put(msg)
        except (OSError, ValueError, AttributeError):
            pass
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({'error': 'IPC disconnected'})

    def command(self, *args, timeout=3):
        waiter = queue.Queue(maxsize=2)
        request_id = next(self.ids)
        with self.lock:
            self.pending[request_id] = waiter
            try:
                self.pipe.write((json.dumps({'command': list(args), 'request_id': request_id},
                                           ensure_ascii=False, separators=(',', ':')) + '\n').encode())
            except Exception:
                self.pending.pop(request_id, None)
                raise
        try:
            msg = waiter.get(timeout=timeout)
            if msg.get('error') != 'success':
                raise RuntimeError(f'mpv {args[0]}: {msg.get("error")}')
            return msg.get('data')
        except queue.Empty as e:
            raise TimeoutError(f'mpv {args[0]} timed out') from e
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def get(self, name, default=None):
        try:
            return self.command('get_property', name)
        except RuntimeError as e:
            if 'property unavailable' in str(e) or 'property not found' in str(e):
                return default
            raise

    def pause(self, value=True):
        self.command('set_property', 'pause', value)

    def seek(self, seconds):
        before = self.restarts
        self.command('seek', seconds, 'absolute+exact')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.restarts > before and not self.get('seeking', True):
                return
            time.sleep(.02)
        raise TimeoutError('mpv seek did not restart playback')

    def audio_sample(self):
        t0 = time.perf_counter_ns()
        position = self.get('audio-pts')
        t1 = time.perf_counter_ns()
        return {'position_ms': None if position is None else position * 1000,
                'host_ns': (t0 + t1) // 2, 'uncertainty_ms': (t1 - t0) / 2e6}

    def verify(self):
        params = self.get('audio-out-params', {}) or {}
        codec = self.get('audio-codec-name', '') or ''
        decoder = self.get('audio-decoder', '') or ''
        ao = self.get('current-ao', '') or ''
        fmt = str(params.get('format', ''))
        valid = ao == 'wasapi' and fmt.lower() == 'spdif-truehd'
        if not self.diagnostic and not valid:
            raise RuntimeError(f'TrueHD passthrough not confirmed: AO={ao}, format={fmt}, '
                               f'codec={codec}, decoder={decoder}. Check HDMI endpoint and track.')
        return {'valid': valid, 'ao': ao, 'format': fmt, 'codec': codec, 'decoder': decoder,
                'params': params, 'diagnostic': self.diagnostic}

    def close(self):
        if self.proc and self.proc.poll() is None:
            try:
                if self.pipe:
                    self.command('quit', timeout=.5)
            except Exception:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=2)
        if self.pipe:
            self.pipe.close()
        self.pipe = None
