"""Desktop settings, device discovery and background operations; no GUI dependency."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading

from .server import HostRuntime, lan_address
from .player_download import managed_player, install_player
from . import __version__
from .diagnostics import save_report

VERSION = __version__
PROFILE_NAME = 'DualTheater-RobustSync'


def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / PROFILE_NAME


def find_mpv(saved='', executable_dir=None, data_dir=None):
    directory = Path(executable_dir or (Path(sys.executable).parent if getattr(sys, 'frozen', False)
                                      else Path(__file__).resolve().parent.parent))
    data_dir = Path(data_dir or default_data_dir())
    downloaded = managed_player(data_dir)
    # Saved managed paths must pass the receipt check, including supporting DLLs.
    if saved and Path(saved).resolve().is_relative_to((data_dir/'players').resolve()):
        saved = downloaded
    for candidate in (saved, downloaded,
                      directory / 'mpv.exe', directory / 'tools/mpv.exe', shutil.which('mpv.exe')):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return ''


class Settings:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'settings.local.json'
        self.values = {}
        self.warning = ''
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict):
                    raise ValueError('Expected a JSON object')
                self.values = {key: value[key] for key in ('mpv', 'device', 'sync_mode') if isinstance(value.get(key), str)}
            except (OSError, ValueError):
                self.warning = 'Saved audio setup could not be read. Choose mpv and HDMI audio again.'

    def save(self, mpv, device, sync_mode='audio-clock'):
        if not Path(mpv).is_file() or not device.startswith('wasapi/'):
            raise ValueError('Choose an existing mpv executable and a WASAPI audio device.')
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.warning and self.path.exists():
            # Preserve unreadable settings for local recovery; never publish them.
            backup = self.path.with_name('settings.local.unreadable.json')
            if backup.exists():
                raise RuntimeError('An unreadable settings backup already exists; preserve it before saving again.')
            self.path.replace(backup)
        temporary = self.path.with_suffix('.tmp')
        if sync_mode not in ('baseline', 'servo', 'audio-clock'):
            raise ValueError('Select a supported sync mode')
        self.values = {'mpv': str(Path(mpv).resolve()), 'device': device, 'sync_mode': sync_mode}
        temporary.write_text(json.dumps(self.values, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
        self.warning = ''


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        match = re.match(r"\s*'([^']+)'\s+\((.*)\)\s*$", line)
        if match and match[1].startswith('wasapi/'):
            devices.append({'id': match[1], 'label': match[2] or match[1]})
    # Friendly names may collide; number them rather than displaying long endpoint IDs.
    counts = {}
    for device in devices:
        label = device['label']
        counts[label] = counts.get(label, 0) + 1
        if sum(d['label'] == label for d in devices) > 1 or counts[label] > 1:
            device['label'] = f"{label} ({counts[label]})"
    return devices


def list_devices(executable, allow_empty=False):
    if not Path(executable).is_file():
        raise ValueError('Select mpv.exe first.')
    result = subprocess.run([str(executable), '--no-config', '--audio-device=help'],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('mpv could not list audio devices. Choose a working Windows mpv build.')
    devices = parse_devices((result.stdout + result.stderr).decode('utf-8', errors='replace'))
    if not devices and not allow_empty:
        raise RuntimeError('No Windows WASAPI devices found. Check the HDMI connection and refresh.')
    return devices


def runtime_args(mpv, device, directory, ephemeral=False, sync_mode='audio-clock'):
    return argparse.Namespace(mpv=str(mpv), device=device, data_dir=str(directory),
                              diagnostic=False, host=lan_address(), sync_mode=sync_mode,
                              ui_port=0 if ephemeral else 8764, media_port=0 if ephemeral else 8765,
                              control_port=0 if ephemeral else 8766,
                              discovery_port=0 if ephemeral else 8767)


def format_time(milliseconds):
    seconds = max(0, int((milliseconds or 0) / 1000))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def verify_core(path):
    """Frozen-resource, local-service and library check without creating a GUI or opening HDMI."""
    import hashlib
    import http.client
    import tempfile
    from .calibration import FIXTURE_SHA256
    root = Path(__file__).resolve().parent.parent
    for name in ('controller.html', 'select_audio.lua', 'audio_timing.lua'):
        if not Path(__file__).with_name(name).is_file():
            raise RuntimeError('Missing bundled resource: ' + name)
    if hashlib.sha256((root/'calibration-phone-SDR-TrueHD.mkv').read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError('Calibration reference integrity check failed')
    with tempfile.TemporaryDirectory(prefix='dualtheater-core-') as directory:
        runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/core-check', directory, ephemeral=True))
        try:
            runtime.start()
            movies = Path(directory)/'movies'; movies.mkdir()
            grant = runtime.app.action({'action': 'library_add', 'path': str(movies)})
            page = runtime.app.action({'action': 'browse', 'provider': 'windows', 'entry': grant['root_id']})
            assert page['entries'] == []
            connection = http.client.HTTPConnection('127.0.0.1', runtime.args.ui_port, timeout=5)
            connection.request('GET', '/')
            response = connection.getresponse(); html = response.read()
            assert response.status == 200 and b'id="subtitles"' in html and b'id="library"' in html
            connection.close()
            report = json.dumps(runtime.app.diagnostic_report())
            assert directory not in report and runtime.app.ui_token not in report
        finally:
            runtime.close()
    player = 'not configured'
    if os.environ.get('DUALTHEATER_MPV'):
        list_devices(os.environ['DUALTHEATER_MPV'], allow_empty=True); player = 'passed'
    Path(path).write_text(json.dumps({'version': VERSION, 'resources': 'passed',
        'host_start_stop': 'passed', 'library': 'passed', 'diagnostics': 'passed',
        'external_player': player, 'gui': 'not tested', 'physical_playback': 'not tested'}), encoding='utf-8')


class DesktopService:
    """Keep slow IPC/network work off Tk's thread; preserve Coordinator transport logic."""
    def __init__(self, directory, runtime_factory=HostRuntime):
        self.directory = Path(directory)
        self.runtime_factory = runtime_factory
        self.runtime = None
        self.receiver_info = {}
        self.commands = queue.Queue(maxsize=8)
        self.priority_pauses = queue.Queue(maxsize=1)
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.cancel_download = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.poller = threading.Thread(target=self._poll, daemon=True)
        self.worker.start()
        self.poller.start()
        threading.Thread(target=self._pause_work, daemon=True).start()

    def submit(self, operation, **values):
        if operation == 'priority_pause':
            if self.runtime:
                self.runtime.app.cancel.set()
            try: self.priority_pauses.put_nowait(True)
            except queue.Full: pass  # Repeated Pause presses coalesce.
            return True
        if operation == 'download_mpv':
            self.cancel_download.clear()
        if operation in ('stop', 'close'):
            self.cancel_download.set()
        if operation in ('stop', 'close') or (operation == 'action' and values.get('action') == 'pause'):
            if self.runtime:
                self.runtime.app.cancel.set()
        try:
            self.commands.put_nowait((operation, values))
            return True
        except queue.Full:
            self.events.put(('error', 'Please wait for the current operation.'))
            return False

    def _pause_work(self):
        while not self.closed.is_set():
            try: self.priority_pauses.get(timeout=.2)
            except queue.Empty: continue
            try:
                runtime = self.runtime
                if runtime and not getattr(runtime, 'closed', False):
                    runtime.app.action({'action': 'pause'})
                    self.events.put(('action_done', 'pause'))
            except Exception:
                if not self.closed.is_set(): self.events.put(('error', 'Could not pause; check the TV connection.'))
            finally:
                self.priority_pauses.task_done()

    def _work(self):
        while not self.closed.is_set():
            operation, values = self.commands.get()
            self.events.put(('busy', True))
            try:
                if operation == 'devices':
                    self.events.put(('devices', list_devices(values['mpv'])))
                elif operation == 'download_mpv':
                    player = install_player(self.directory, cancel=self.cancel_download,
                        progress=lambda message:self.events.put(('download_progress',message)))
                    self.events.put(('mpv_ready',player))
                elif operation == 'start':
                    if self.runtime:
                        raise RuntimeError('Stop the connection before changing audio setup.')
                    runtime = self.runtime_factory(runtime_args(values['mpv'], values['device'], self.directory,
                        sync_mode=values.get('sync_mode', 'audio-clock')))
                    runtime.app.receiver_observations.update(self.receiver_info)
                    runtime.start()
                    self.runtime = runtime
                    self.events.put(('started', None))
                elif operation == 'action':
                    if not self.runtime:
                        raise RuntimeError('Start the TV connection first.')
                    self.runtime.app.action(values)
                    self.events.put(('action_done', values['action']))
                elif operation == 'library':
                    if not self.runtime:
                        raise RuntimeError('Start the TV connection to manage your library.')
                    if values.get('action') not in ('browse', 'providers', 'library_add', 'library_remove', 'load_entry'):
                        raise ValueError('Unknown library operation')
                    result = self.runtime.app.action(values)
                    self.events.put(('library_result', {'action': values['action'], 'result': result}))
                    if values['action'] == 'load_entry':
                        self.events.put(('action_done', 'load'))
                elif operation == 'export_diagnostics':
                    if not self.runtime:
                        raise RuntimeError('Start the TV connection before exporting diagnostics.')
                    save_report(values['path'], self.runtime.app.diagnostic_report())
                    self.events.put(('diagnostics_exported', None))
                elif operation in ('inspect_s95tr', 'inspect_hdmi'):
                    from .receiver import inspect_s95tr, inspect_hdmi
                    if self.runtime and self.runtime.app.state in ('playing', 'armed', 'loading', 'seeking'):
                        raise RuntimeError('Pause playback before inspecting receiver information')
                    result = inspect_s95tr(values['address']) if operation == 'inspect_s95tr' else inspect_hdmi()
                    self.receiver_info[operation] = result
                    if self.runtime:
                        self.runtime.app.receiver_observations[operation] = result
                    self.events.put(('receiver_information', result))
                elif operation in ('stop', 'close'):
                    runtime, self.runtime = self.runtime, None
                    if runtime:
                        runtime.close()
                    self.events.put(('stopped', None))
                    if operation == 'close':
                        self.closed.set()
                else:
                    raise ValueError('Unknown desktop operation')
            except Exception as e:
                message = str(e)
                if isinstance(e, OSError) and getattr(e, 'winerror', None) == 10048:
                    message = 'Another DualTheater host is using the connection ports. Close it, then try again.'
                self.events.put(('error', message))
                if operation == 'close':
                    self.closed.set()
            finally:
                self.events.put(('busy', False))

    def _poll(self):
        while not self.closed.wait(.6):
            runtime = self.runtime
            if runtime:
                try:
                    self.events.put(('status', runtime.app.snapshot()))
                except Exception:
                    # IPC can disappear during load/stop. The operation result owns errors.
                    pass
