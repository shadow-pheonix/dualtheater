"""DualTheater: HTTP byte serving, authenticated TV control, and audio-led sync."""
import argparse
from collections import deque
import csv
from datetime import datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import queue
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from .mpv import Mpv
from .sync import ClockFilter, VideoServo, parse_range
from .pairing import PairingStore
from .discovery import DiscoveryServer, DISCOVERY_PORT
from .diagnostics import SessionDiagnostics, receiver_report
from .calibration import CalibrationService
from .timing import AffineClock, AudioTimeline, AdaptiveServo

ROOT = Path(__file__).resolve().parent.parent


def ns():
    return time.perf_counter_ns()


def finite(value, low, high):
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Value must be between {low} and {high}')
    return value


class Peer:
    def __init__(self, sock, reader):
        self.sock, self.reader = sock, reader
        self.lock = threading.Lock()
        self.pending = {}
        self.counter = 0
        self.clock = ClockFilter()
        self.status = {}
        self.status_seen = None
        self.seen = ns()
        self.closed = False
        self.last_remote_id = 0
        self.remote_controls = False
        self.local_host = sock.getsockname()[0]
        self.timing_token = secrets.token_urlsafe(32)
        self.timing = None
        self.timing_protocol = False

    def send(self, msg):
        with self.lock:
            if self.closed:
                raise ConnectionError('TV disconnected')
            self.sock.sendall((json.dumps(msg, separators=(',', ':')) + '\n').encode())

    def request(self, op, **values):
        with self.lock:
            self.counter += 1
            key = self.counter
            waiter = queue.Queue()
            self.pending[key] = waiter
        try:
            self.send(dict(op=op, id=key, **values))
            try:
                result = waiter.get(timeout=5)
            except queue.Empty as e:
                raise TimeoutError('TV did not acknowledge ' + op) from e
            if result.get('error'):
                raise RuntimeError('TV: ' + result['error'])
            return result
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def close(self):
        with self.lock:
            self.closed = True
            for waiter in self.pending.values():
                waiter.put({'error': 'TV disconnected'})
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        if self.timing:
            self.timing.close()


class TimingLink:
    """One TV-session-bound duplex timing stream; no transport commands."""
    def __init__(self, sock):
        self.sock = sock
        self.sock.settimeout(.5)
        self.lock = threading.Lock()
        self.closed = False

    def send(self, message):
        with self.lock:
            if self.closed:
                raise ConnectionError('Timing connection closed')
            if message.get('op') == 'ping':
                message = dict(message, t0=ns())
            self.sock.sendall((json.dumps(message, separators=(',', ':')) + '\n').encode())

    def close(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Coordinator:
    def __init__(self, args, mpv_factory=Mpv):
        self.args, self.mpv_factory = args, mpv_factory
        self.sync_mode = getattr(args, 'sync_mode', 'baseline')
        if self.sync_mode not in ('baseline', 'servo', 'audio-clock'):
            raise ValueError('Unknown sync mode')
        self.pair_token = secrets.token_hex(6)
        self.pair_code = f'{secrets.randbelow(1000000):06d}'
        self.host_name = socket.gethostname()[:63]
        self.data_dir = Path(getattr(args, 'data_dir', None) or ROOT)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pairings = PairingStore(self.data_dir / 'pairings.json')
        self.ui_token = secrets.token_urlsafe(24)
        self.media_token = secrets.token_urlsafe(24)
        self.peer = self.mpv = self.media = None
        self.epoch = 0
        self.state = 'idle'
        self.error = ''
        self.offset_ms = 0.0
        self.offset_source = 'zero_default'
        self.offset_context = None
        self.receiver_observations = {}
        self.video_context = {}
        self.anchor_ms = 0.0
        self.duration_ms = 0.0
        self.offset_file = self.data_dir / f'calibration-{self.sync_mode}.json'
        if self.offset_file.exists():
            try:
                saved = json.loads(self.offset_file.read_text())
                self.offset_ms = finite(saved['video_lead_ms'], -2000, 2000)
                self.offset_source = saved.get('source', 'manual') if saved.get('source') in ('manual', 'phone') else 'manual'
                self.offset_context = saved.get('context')
            except (ValueError, KeyError, OSError):
                pass
        self.audio_info = {}
        self.audio_sample = {}
        self.drift_ms = None
        self.speed = 1.0
        self.playback_lead_ms = self.offset_ms
        self.last_correction = 0
        self.servo = VideoServo() if self.sync_mode == 'baseline' else AdaptiveServo()
        self.audio_running = threading.Event()
        self.latest_anchor = None
        self.timing_error = ''
        self.last_frame_key = None
        self.started_ns = 0
        self.diagnostics = SessionDiagnostics()
        self.calibration = CalibrationService(self, ROOT / 'calibration-phone-SDR-TrueHD.mkv')
        self.recoveries = deque()
        self.op_lock = threading.RLock()
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.remote_queue = queue.Queue(maxsize=8)
        self.logs = deque(maxlen=40)
        self.log_dir = self.data_dir / 'logs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.csv_file = (self.log_dir / 'timing.csv').open('w', newline='', encoding='utf-8')
        self.csv = csv.writer(self.csv_file)
        self.csv.writerow(['host_ns', 'epoch', 'audio_ms', 'video_ms', 'error_ms', 'video_speed',
                           'clock_rtt_ms', 'ipc_uncertainty_ms'])

    def log(self, text):
        line = datetime.now().strftime('%H:%M:%S') + ' ' + str(text)
        self.logs.append(line)
        with (self.log_dir / 'events.log').open('a', encoding='utf-8') as f:
            f.write(line + '\n')
        if sys.stdout is not None:
            print(line, flush=True)

    def snapshot(self):
        p = self.peer
        best = p.clock.best(ns()) if p else None
        return {'state': self.state, 'error': self.error, 'file': self.media.name if self.media else None,
                'position_ms': self.audio_sample.get('position_ms', self.anchor_ms) if self.state == 'playing' else self.anchor_ms,
                'duration_ms': self.duration_ms,
                'epoch': self.epoch, 'video_lead_ms': self.offset_ms, 'drift_ms': self.drift_ms,
                'video_speed': self.speed, 'audio': self.audio_info, 'audio_sample': self.audio_sample,
                'tv': p.status if p else {}, 'connected': bool(p and not p.closed),
                'clock_rtt_ms': best.rtt_ns / 1e6 if best else None,
                'logs': list(self.logs), 'host': self.args.host, 'control_port': self.args.control_port,
                'pair_token': self.pair_token, 'diagnostic': self.args.diagnostic,
                'pair_code': self.pair_code, 'host_name': self.host_name,
                'diagnostics': self.diagnostic_report(),
                'phone_calibration': self.calibration.snapshot(), 'sync_mode': self.sync_mode,
                'offset_source': self.offset_source, 'offset_profile': self.offset_profile_status(),
                'audio_tracks': self.mpv.get('track-list', []) if self.mpv and self.state not in ('loading', 'seeking') else []}

    def diagnostic_report(self):
        # This path performs no mpv IPC and never copies a raw snapshot/log.
        p = self.peer
        status_seen = p.status_seen if p else None
        report = self.diagnostics.report(
            state=self.state, connected=bool(p and not p.closed), status=p.status if p else {},
            status_age_ms=(ns() - status_seen) / 1e6 if status_seen is not None else None,
            epoch=self.epoch, audio=self.audio_info, video_lead_ms=self.offset_ms)
        from .diagnostics import number, vocabulary
        report['sync'] = {'mode': self.sync_mode, 'offset_source': self.offset_source,
                         'offset_profile': self.offset_profile_status(),
                         'active_video_lead_ms': self.playback_lead_ms,
                         'drift_basis': 'scheduled_release' if self.sync_mode == 'baseline' else 'media_timeline',
                         'physical_accuracy': 'unvalidated'}
        clock = p.clock.best(ns()) if p else None
        fresh = (p and not p.closed and status_seen is not None
                 and 0 <= ns() - status_seen <= 2_000_000_000 and p.status.get('epoch') == self.epoch)
        remote = p.status.get('remote_clock') if fresh else None
        remote = remote if isinstance(remote, dict) else {}
        observed = p.status.get('rendered_frame') if fresh else None
        event_ns = observed.get('rendered_ns') if isinstance(observed, dict) else None
        event_host = (clock.host(event_ns) if hasattr(clock, 'host') else event_ns - clock.offset_ns
                      ) if clock is not None and type(event_ns) is int else None
        if (not isinstance(observed, dict) or observed.get('epoch') != self.epoch
            or event_host is None or not 0 <= ns() - event_host <= 2_000_000_000):
            observed = {}
        report['sync'].update(clock_uncertainty_ms=number(clock.uncertainty_ns / 1e6, 0)
                if hasattr(clock, 'uncertainty_ns') else None,
            clock_rate_ppm=number((clock.rate - 1) * 1e6) if hasattr(clock, 'rate') else None,
            remote_clock_state=vocabulary(remote.get('state'),
                ('paused', 'acquiring', 'locked', 'slewing', 'holdover', 'audio_anchor_expired', 'audio_phase_jump')),
            remote_clock_phase_ms=number(remote.get('phase_error_ms')),
            rendered_callback_present=bool(observed),
            release_to_render_ms=number((observed['rendered_ns'] - observed['release_ns']) / 1e6, 0, 500)
                if type(observed.get('rendered_ns')) is int and type(observed.get('release_ns')) is int else None)
        report['receiver'] = receiver_report(self.receiver_observations)
        return report

    def profile_context(self):
        status = self.peer.status if self.peer else {}
        frame = status.get('frame') or {}
        if frame.get('mime'):
            self.video_context = {k: frame.get(k) for k in ('mime', 'width', 'height', 'color')}
        return {'sync_mode': self.sync_mode,
                'video': self.video_context.copy(),
                'audio_format': self.audio_info.get('format'),
                'receiver': self.receiver_observations.get('inspect_s95tr')}

    def offset_profile_status(self):
        if self.offset_source == 'zero_default':
            return 'unmeasured'
        if not self.offset_context:
            return 'context_unknown'
        return 'context_matches' if self.offset_context == self.profile_context() else 'context_changed'

    def tv(self):
        if not self.peer or self.peer.closed:
            raise RuntimeError('Connect the TV companion first')
        if ns() - self.peer.seen > 2_000_000_000:
            raise RuntimeError('TV telemetry is stale')
        return self.peer

    def pause_both(self, reason='paused'):
        self.audio_running.clear()
        self.latest_anchor = None
        self.epoch += 1
        if self.mpv:
            if self.state == 'playing':
                self.anchor_ms = max(0, self.mpv.get('time-pos', 0) * 1000)
            self.mpv.pause()
        if self.peer and not self.peer.closed:
            self.peer.request('pause', epoch=self.epoch)
        self.state = reason
        self.speed = 1.0
        self.servo.reset()
        self.last_frame_key = None

    def fail(self, message):
        self.diagnostics.error()
        self.error = str(message)
        self.cancel.set()
        try:
            self.pause_both('error')
        except Exception:
            self.state = 'error'
            if self.mpv:
                try:
                    self.mpv.pause()
                except Exception:
                    pass
        self.log('ERROR: ' + self.error)

    def wait_for(self, predicate, seconds=30):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if self.cancel.is_set() or self.stop.is_set():
                raise RuntimeError('Operation cancelled')
            p = self.tv()
            if p.status.get('error'):
                raise RuntimeError(p.status['error'])
            if predicate(p):
                return
            time.sleep(.05)
        raise TimeoutError('Timed out waiting for both players; inspect TV status and mpv log')

    def mpv_ready(self, position):
        return (not self.mpv.get('idle-active', True) and not self.mpv.get('seeking', True)
                and bool(self.mpv.get('audio-out-params', None)))

    def ready(self, p, position):
        s = p.status
        return (s.get('epoch') == self.epoch and s.get('state') == 'ready'
                and not s.get('seek_pending', True) and abs(s.get('position_ms', -9999) - position) < 150
                and self.mpv_ready(position))

    def load(self, path, aid='auto'):
        self.tv()
        media = Path(path).expanduser().resolve(strict=True)
        if not media.is_file() or media.suffix.lower() not in ('.mkv', '.mp4', '.m2ts', '.ts'):
            raise ValueError('Choose an MKV, MP4, M2TS or TS file')
        if not self.args.diagnostic and not self.args.device:
            raise ValueError('Choose an explicit WASAPI HDMI endpoint in Start.ps1 or --device')
        self.pause_both('loading')
        if self.mpv:
            self.mpv.close()
        self.media = media
        self.video_context = {}
        self.anchor_ms = 0
        self.media_token = secrets.token_urlsafe(24)
        self.mpv = self.mpv_factory(self.args.mpv, self.args.device, self.log_dir, self.args.diagnostic)
        self.mpv.launch()
        self.mpv.command('set_property', 'user-data/dualtheater-aid', str(aid))
        self.mpv.command('loadfile', str(media), 'replace')
        self.epoch += 1
        peer = self.tv()
        peer.request('load', epoch=self.epoch,
                          url=f'http://{peer.local_host}:{self.args.media_port}/media/{self.media_token}/{media.suffix.lower()[1:]}',
                          position_ms=0)
        self.wait_for(lambda p: self.ready(p, 0))
        self.audio_info = self.mpv.verify()
        self.duration_ms = (self.mpv.get('duration', 0) or 0) * 1000
        tracks = self.mpv.get('track-list', [])
        self.log('Prepared ' + media.name + '; audio=' + json.dumps(self.audio_info))
        self.log('Audio tracks: ' + json.dumps([t for t in tracks if t.get('type') == 'audio']))
        self.state = 'paused'

    def prepare(self, position_ms):
        self.pause_both('seeking')
        self.anchor_ms = position_ms
        self.mpv.seek(position_ms / 1000)
        self.epoch += 1  # A seek barrier must not accept the preceding pause's READY status.
        self.tv().request('seek', epoch=self.epoch, position_ms=round(position_ms))
        self.wait_for(lambda p: self.ready(p, position_ms))
        self.audio_info = self.mpv.verify()
        self.state = 'paused'

    def start(self, prepared=False):
        if not self.mpv or not self.media:
            raise RuntimeError('Load a file first')
        p = self.tv()
        if self.sync_mode != 'baseline' and not p.timing_protocol:
            raise RuntimeError('This sync mode requires the matching Robust Sync TV app')
        if self.sync_mode != 'baseline':
            self.wait_for(lambda q: q.timing and not q.timing.closed, seconds=5)
            self.timing_error = ''
        self.wait_for(lambda p: p.clock.best(ns()) is not None, seconds=8)
        self.audio_info = self.mpv.verify()
        if not prepared:
            self.prepare(self.anchor_ms)
        self.wait_for(lambda q: q.status.get('epoch') == self.epoch and q.status.get('state') == 'ready'
                      and not q.status.get('seek_pending', True), seconds=10)
        clock = p.clock.best(ns())
        if not clock or clock.rtt_ns > 30_000_000:
            raise RuntimeError('Clock round-trip exceeds 30 ms; improve LAN connection')
        # Offset is made with separate start deadlines, including at media time zero.
        # Positive lead starts video first; negative lead starts audio first.
        start_at = ns() + 1_000_000_000
        self.playback_lead_ms = self.offset_ms
        video_at = start_at + round(max(0, -self.offset_ms) * 1e6)
        audio_at = start_at + round(max(0, self.offset_ms) * 1e6)
        arm = dict(epoch=self.epoch, host_ns=video_at, offset_ns=clock.offset_ns)
        if self.sync_mode != 'baseline':
            if clock.uncertainty_ns > 12_000_000:
                raise RuntimeError('Clock uncertainty exceeds 12 ms; improve the LAN connection')
            arm.update(video_ns=clock.remote(video_at), audio_ns=clock.remote(audio_at),
                       position_ms=self.anchor_ms, video_lead_ms=self.offset_ms)
        p.request('arm', **arm)
        if ns() > start_at - 300_000_000:
            raise RuntimeError('Start acknowledgement arrived too late; press Play again')
        self.state = 'armed'
        self.drift_ms = None
        self.servo.reset()
        audio_started = False
        finish_at = max(video_at, audio_at) + 150_000_000
        while ns() < finish_at:
            if not audio_started and ns() >= audio_at:
                self.mpv.pause(False)
                self.audio_running.set()
                audio_started = True
            if self.cancel.wait(.002 if ns() >= start_at else .01):
                raise RuntimeError('Start cancelled')
            if p.closed or ns() - p.seen > 1_000_000_000:
                raise RuntimeError('TV disconnected before start')
            if p.status.get('state') in ('buffering', 'error'):
                raise RuntimeError('TV became unready before start')
        if not audio_started:
            self.mpv.pause(False)
            self.audio_running.set()
        if self.sync_mode != 'baseline':
            self.verify_progress(p, video_at)
        self.state = 'playing'
        self.started_ns = ns()
        self.last_correction = ns()
        self.log('Started epoch ' + str(self.epoch))

    def verify_progress(self, peer, video_at):
        """An armed deadline is not proof of either device advancing."""
        first = None
        deadline = ns() + 3_000_000_000
        while ns() < deadline:
            if self.cancel.wait(.025) or self.stop.is_set():
                raise RuntimeError('Start cancelled')
            if self.timing_error:
                raise RuntimeError(self.timing_error)
            s = peer.status
            if peer.closed or s.get('error') or s.get('state') == 'buffering':
                raise RuntimeError('Playback became unavailable during start verification')
            anchor = self.latest_anchor
            frame = s.get('frame', {})
            clock = peer.clock.best(ns())
            fresh = (anchor and anchor.get('epoch') == self.epoch and s.get('epoch') == self.epoch
                     and s.get('playing') and frame.get('valid') and frame.get('epoch') == self.epoch
                     and clock is not None
                     and frame.get('release_ns', 0) > clock.remote(video_at)
                     and frame.get('sequence', 0) > 0)
            if fresh:
                point = (anchor['position_ms'], frame['position_ms'], frame['sequence'])
                if first is None:
                    first = point
                elif point[0] - first[0] >= 20 and point[1] - first[1] >= 20 and point[2] > first[2]:
                    if self.sync_mode == 'audio-clock' and not s.get('remote_clock', {}).get('reads_recent'):
                        continue
                    return
        raise RuntimeError('Scheduled start did not produce fresh audio and video progress')

    def sample_audio(self):
        """Dedicated source sampler, independent of the host operation/UI loops."""
        model, model_epoch = AudioTimeline(), -1
        while not self.stop.wait(.04):
            if self.sync_mode == 'baseline' or not self.audio_running.is_set():
                model.reset()
                continue
            epoch, mpv, peer = self.epoch, self.mpv, self.peer
            if epoch != model_epoch:
                model.reset(); model_epoch = epoch
            if not mpv or not peer or peer.closed:
                continue
            try:
                sample = mpv.timed_audio_sample()
                if self.epoch != epoch or self.mpv is not mpv or not self.audio_running.is_set():
                    continue
                anchor = model.add(sample)
                if anchor is None:
                    continue
                if anchor['uncertainty_ms'] > 10:
                    continue
                clock = peer.clock.best(ns())
                if clock is None or clock.uncertainty_ns > 12_000_000:
                    raise RuntimeError('Remote clock uncertainty exceeded its budget')
                if ns() - anchor['host_ns'] > 250_000_000:
                    raise RuntimeError('Source audio samples are too old')
                anchor.update(epoch=epoch)
                self.latest_anchor = anchor
                if not peer.timing or peer.timing.closed:
                    raise RuntimeError('Dedicated timing connection lost')
                peer.timing.send(dict(op='anchor', epoch=epoch, sequence=anchor['sequence'],
                    local_ns=clock.remote(anchor['host_ns']),
                    position_ms=anchor['position_ms'] + self.playback_lead_ms,
                    rate=anchor['rate'] / clock.rate,
                    uncertainty_ms=anchor['uncertainty_ms'] + clock.uncertainty_ns / 1e6))
            except Exception as e:
                if self.epoch == epoch and self.audio_running.is_set():
                    self.timing_error = str(e)

    def action(self, body):
        action = body.get('action')
        if action == 'pause':
            self.cancel.set()  # interrupts a pending start/prepare before taking the operation lock
        with self.op_lock:
            operation_started = ns()
            failed = False
            try:
                if action == 'pause':
                    self.pause_both()
                    self.error = ''
                    return
                self.cancel.clear()
                self.error = ''
                if action == 'load':
                    self.load(body['path'], body.get('aid', 'auto'))
                elif action == 'play':
                    if self.state != 'playing':
                        self.start()
                elif action == 'seek':
                    if not self.mpv:
                        raise RuntimeError('Load a file first')
                    playing = body.get('play_after', self.state == 'playing')
                    if not isinstance(playing, bool):
                        raise ValueError('play_after must be a boolean')
                    duration = self.mpv.get('duration', 86400)
                    self.prepare(finite(body['seconds'], 0, max(0, duration - .1)) * 1000)
                    if playing:
                        self.start(prepared=True)
                elif action == 'offset':
                    value = finite(body['milliseconds'], -2000, 2000)
                    source = 'phone' if body.get('source') == 'phone' else 'manual'
                    context = self.profile_context()
                    temporary = self.offset_file.with_suffix('.tmp')
                    try:
                        temporary.write_text(json.dumps({'video_lead_ms': value, 'source': source,
                                                        'context': context}), encoding='utf-8')
                        os.replace(temporary, self.offset_file)
                    finally:
                        temporary.unlink(missing_ok=True)
                    self.offset_ms = value
                    self.offset_source, self.offset_context = source, context
                    self.servo.reset()
                    self.log(f'Video lead set to {self.offset_ms:.1f} ms')
                elif action == 'track':
                    if not self.mpv:
                        raise RuntimeError('Load a file first')
                    playing = self.state == 'playing'
                    position = self.mpv.get('time-pos', 0) * 1000
                    self.pause_both()
                    self.mpv.command('set_property', 'aid', str(int(body['aid'])))
                    self.prepare(position)
                    if playing:
                        self.start(prepared=True)
                elif action == 'resync':
                    if not self.mpv:
                        raise RuntimeError('Load a file first')
                    playing = self.state == 'playing'
                    self.prepare(self.mpv.get('time-pos', 0) * 1000)
                    if playing:
                        self.start(prepared=True)
                else:
                    raise ValueError('Unknown action')
            except Exception as e:
                failed = True
                self.fail(str(e))
                raise
            finally:
                self.diagnostics.operation(action, (ns() - operation_started) / 1e6, failed)

    def heartbeat(self):
        while not self.stop.wait(.5 if self.sync_mode == 'baseline' else .2):
            p = self.peer
            if p and not p.closed:
                try:
                    if self.sync_mode == 'baseline':
                        p.send({'op': 'ping', 't0': ns()})
                    elif p.timing and not p.timing.closed:
                        p.timing.send({'op': 'ping'})
                    if p.remote_controls:
                        p.send(self.playback_status())
                except OSError:
                    p.close()

    def playback_status(self):
        return {'op': 'coordinator', 'epoch': self.epoch, 'state': self.state,
                'loaded': self.media is not None, 'duration_ms': self.duration_ms,
                'position_ms': self.audio_sample.get('position_ms', self.anchor_ms)
                    if self.state == 'playing' else self.anchor_ms,
                'title': self.media.stem if self.media else '', 'error': self.error}

    def remote_result(self, peer, request_id, error=''):
        peer.send({'op': 'remote_result', 'request': request_id, 'ok': not bool(error),
                   'error': error, 'coordinator': self.playback_status()})

    def enqueue_remote(self, peer, message):
        """The socket reader only enqueues: it must keep receiving barrier ACKs."""
        request_id = message.get('request')
        try:
            if type(request_id) is not int or request_id <= peer.last_remote_id:
                raise ValueError('Duplicate or invalid remote request')
            if not peer.remote_controls:
                raise ValueError('TV remote controls were not negotiated')
            peer.last_remote_id = request_id
            if message.get('action') not in ('toggle', 'play', 'pause', 'seek'):
                raise ValueError('Unsupported remote action')
            if type(message.get('epoch')) is not int:
                raise ValueError('Missing remote playback generation')
            self.remote_queue.put_nowait((peer, dict(message)))
        except (ValueError, queue.Full) as e:
            self.remote_result(peer, request_id, str(e) or 'Player is busy')

    def remote_worker(self):
        while not self.stop.is_set():
            try:
                peer, message = self.remote_queue.get(timeout=.2)
            except queue.Empty:
                continue
            error = ''
            try:
                with self.op_lock:
                    if peer is not self.peer or peer.closed:
                        raise ValueError('Remote session disconnected')
                    if message['epoch'] != self.epoch:
                        raise ValueError('Playback changed; try the remote again')
                    if not self.media or not self.mpv:
                        raise ValueError('Load a movie on Windows first')
                    action = message['action']
                    if action == 'toggle':
                        action = 'pause' if self.state == 'playing' else 'play'
                    body = {'action': action}
                    if action == 'seek':
                        seconds = finite(message.get('seconds'), 0, 864000)
                        if self.duration_ms <= 0:
                            raise ValueError('Movie duration is not available yet')
                        body['seconds'] = min(seconds, max(0, self.duration_ms / 1000 - .1))
                        if message.get('toggle', False):
                            body['play_after'] = self.state != 'playing'
                    self.action(body)
            except Exception as e:
                error = str(e)
            finally:
                self.remote_queue.task_done()
            if not peer.closed:
                try:
                    self.remote_result(peer, message['request'], error)
                except OSError:
                    peer.close()

    def monitor(self):
        verify_at = 0
        while not self.stop.wait(.1):
            now = ns()
            if not self.op_lock.acquire(blocking=False):
                continue
            try:
                if self.state != 'playing':
                    continue
                p = self.tv()
                if self.sync_mode != 'baseline' and self.timing_error:
                    raise RuntimeError(self.timing_error)
                s = p.status
                if s.get('epoch') != self.epoch:
                    raise RuntimeError('TV playback generation changed; reconnect and reload the movie')
                if s.get('error'):
                    raise RuntimeError(s['error'])
                if s.get('state') == 'ended' or self.mpv.get('eof-reached', False):
                    self.pause_both('ended')
                    self.log('End of media')
                    continue
                if s.get('state') == 'buffering' or self.mpv.get('paused-for-cache', False):
                    position = self.mpv.get('time-pos', 0) * 1000
                    self.recover(position, 'Buffer underrun', 'buffering')
                    continue
                if not s.get('playing', False):
                    raise RuntimeError('TV stopped unexpectedly; playback paused')
                sample = self.mpv.audio_sample() if self.sync_mode == 'baseline' else self.latest_anchor
                if sample is None or self.sync_mode != 'baseline' and ns() - sample['host_ns'] > 750_000_000:
                    raise RuntimeError('Source audio timeline expired')
                self.audio_sample = sample
                if sample['position_ms'] is None:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('mpv audio clock unavailable')
                    continue
                if now > verify_at:
                    self.audio_info = self.mpv.verify()
                    verify_at = now + 2_000_000_000
                clock = p.clock.best(now)
                frame = s.get('frame') or {}
                if not clock:
                    raise RuntimeError('Clock synchronization expired')
                if not frame or frame.get('epoch') != self.epoch or not frame.get('valid'):
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Fresh frame timing unavailable; cannot maintain sync')
                    continue
                if self.sync_mode != 'baseline':
                    key = (self.epoch, frame.get('sequence'))
                    if key == self.last_frame_key:
                        if now - self.last_correction > 1_000_000_000:
                            raise RuntimeError('Unique video frame telemetry stalled')
                        continue
                    self.last_frame_key = key
                release_host = (frame['release_ns'] - clock.offset_ns if self.sync_mode == 'baseline'
                                else clock.host(frame.get('presentation_ns', frame['release_ns'])))
                if abs(now - release_host) > 500_000_000:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Video frame telemetry stalled')
                    continue
                if sample['uncertainty_ms'] > 10 or clock.rtt_ns > 30_000_000:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Clock measurements too uncertain to maintain sync')
                    continue
                if self.sync_mode == 'baseline':
                    video_ms = frame['position_ms'] + (sample['host_ns'] - release_host) / 1e6 * s.get('speed', 1)
                else:
                    # Compare media timelines. A codec release may precede VSYNC;
                    # never feed that scheduler lead back as a physical correction.
                    status_host = clock.host(s['sample_ns'])
                    if abs(ns() - status_host) > 500_000_000:
                        raise RuntimeError('Video timeline observation expired')
                    video_ms = s['position_ms'] + (sample['host_ns'] - status_host) / 1e6 * s.get('speed', 1)
                lead = self.playback_lead_ms if self.sync_mode == 'audio-clock' else self.offset_ms
                self.drift_ms = video_ms - (sample['position_ms'] + lead)
                if self.sync_mode == 'baseline':
                    speed, hard = self.servo.update(self.drift_ms)
                elif self.sync_mode == 'audio-clock':
                    remote = s.get('remote_clock', {})
                    if remote.get('state') in ('audio_anchor_expired', 'audio_phase_jump'):
                        raise RuntimeError('TV remote audio clock lost confidence')
                    if not remote.get('reads_recent') or abs(remote.get('renderer_error_ms', 1000)) > 50:
                        raise RuntimeError('TV renderer is not following the remote audio clock')
                    # Independent frame observations are diagnostic only here.
                    speed, hard = 1.0, False
                else:
                    speed, hard = self.servo.update(self.drift_ms, sample['host_ns'],
                        sample['uncertainty_ms'] + clock.uncertainty_ns / 1e6)
                    if speed is None:
                        continue
                self.diagnostics.timing(self.drift_ms, clock.rtt_ns / 1e6, sample['uncertainty_ms'])
                self.csv.writerow([sample['host_ns'], self.epoch, sample['position_ms'], video_ms,
                                   self.drift_ms, speed, clock.rtt_ns / 1e6, sample['uncertainty_ms']])
                self.csv_file.flush()
                self.last_correction = now
                if hard:
                    self.recover(sample['position_ms'], f'Sustained {self.drift_ms:.0f} ms drift', 'drift')
                elif self.sync_mode != 'audio-clock' and abs(speed - self.speed) > .0001:
                    p.request('speed', epoch=self.epoch, value=speed)
                    self.speed = speed
            except Exception as e:
                self.fail(str(e))
            finally:
                self.op_lock.release()

    def recover(self, position_ms, reason, kind='drift'):
        now = ns()
        while self.recoveries and now - self.recoveries[0] > 60_000_000_000:
            self.recoveries.popleft()
        if len(self.recoveries) >= 3:
            raise RuntimeError('Repeated sync/buffer failures; improve network or check timing diagnostics, then resume manually')
        self.recoveries.append(now)
        self.diagnostics.recovery(kind)
        self.log(reason + ': coordinated pause, prepare and restart')
        self.cancel.clear()
        started = ns()
        failed = True
        try:
            self.prepare(position_ms)
            self.start(prepared=True)
            failed = False
        finally:
            self.diagnostics.operation('recovery', (ns() - started) / 1e6, failed)

    def close(self):
        self.stop.set()
        self.cancel.set()
        self.calibration.close()
        with self.op_lock:
            if self.peer:
                self.peer.close()
            if self.mpv:
                self.mpv.close()
            self.csv_file.close()


class ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        app = self.server.app
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.request.settimeout(5)
        peer = None
        try:
            raw_hello = self.rfile.readline(65537)
            if len(raw_hello) > 65536:
                return
            hello = json.loads(raw_hello)
            if not isinstance(hello, dict):
                return
            if hello.get('op') != 'hello' or hello.get('version') != 1:
                return
            if hello.get('role') == 'timing':
                self.handle_timing(hello)
                return
            try:
                trusted_token = app.pairings.authenticate(hello.get('token'), hello.get('client_id'),
                    hello.get('device', 'Android TV'), app.pair_token, app.pair_code, self.client_address[0])
            except (ValueError, OSError) as e:
                self.wfile.write((json.dumps({'op': 'auth_required', 'error': str(e)}) + '\n').encode())
                return
            if hello.get('role') == 'calibration':
                self.handle_calibration(trusted_token)
                return
            if hello.get('role') not in (None, 'tv'):
                return
            if app.peer and not app.peer.closed:
                self.wfile.write(b'{"error":"A TV is already connected"}\n')
                return
            peer = Peer(self.request, self.rfile)
            peer.remote_controls = hello.get('remote_controls') is True
            peer.timing_protocol = hello.get('timing_protocol') == 2
            if app.sync_mode != 'baseline':
                peer.clock = AffineClock()
            app.peer = peer
            welcome = {'op': 'welcome', 'version': 1, 'remote_controls': True,
                       'host_id': app.pairings.host_id, 'host_name': app.host_name,
                       'sync_mode': app.sync_mode, 'timing_token': peer.timing_token}
            if trusted_token:
                welcome['trusted_token'] = trusted_token
            peer.send(welcome)
            app.log('TV connected: ' + str(hello.get('device', 'Android TV')))
            while not app.stop.is_set():
                raw = self.rfile.readline(65537)
                if not raw or len(raw) > 65536:
                    break
                t3 = ns()
                msg = json.loads(raw)
                peer.seen = t3
                if msg.get('op') == 'pong' and app.sync_mode == 'baseline':
                    peer.clock.add(int(msg['t0']), int(msg['t1']), int(msg['t2']), t3)
                elif msg.get('op') == 'status':
                    peer.status = msg
                    peer.status_seen = t3
                elif msg.get('op') == 'remote':
                    app.enqueue_remote(peer, msg)
                elif 'reply' in msg:
                    with peer.lock:
                        waiter = peer.pending.get(msg['reply'])
                    if waiter:
                        waiter.put(msg)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            if peer:
                peer.close()
                app.diagnostics.disconnected()
                app.log('TV disconnected')

    def handle_timing(self, hello):
        app, link = self.server.app, None
        peer = app.peer
        if (not peer or peer.closed or app.sync_mode == 'baseline' or not peer.timing_protocol
            or not isinstance(hello.get('token'), str)
            or not hmac.compare_digest(hello['token'], peer.timing_token)):
            return
        # Only the accepted control session can authorize this stream. Pairing
        # credentials/codes cannot be used to open a free-standing timing role.
        with peer.lock:
            if peer.timing and not peer.timing.closed:
                return
            link = TimingLink(self.request)
            peer.timing = link
        try:
            link.send({'op': 'timing_ready', 'version': 2})
            while not app.stop.is_set() and app.peer is peer and not peer.closed:
                raw = self.rfile.readline(4097)
                if not raw or len(raw) > 4096:
                    break
                t3 = ns()
                msg = json.loads(raw)
                if msg.get('op') != 'pong':
                    break
                # Reject unsolicited future exchanges as well as replay.
                if not t3 - 1_000_000_000 <= msg.get('t0', -1) <= t3:
                    break
                peer.clock.add(msg['t0'], msg['t1'], msg['t2'], t3)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            link.close()
            if app.peer is peer and app.audio_running.is_set():
                app.timing_error = 'Dedicated timing connection lost; reconnect and reload'

    def handle_calibration(self, trusted_token):
        app = self.server.app
        phone = Peer(self.request, self.rfile)
        last_id = 0
        try:
            app.calibration.attach(phone)
            phone.send({'op': 'welcome', 'version': 1, 'role': 'calibration', 'calibration_protocol': 1,
                        'host_id': app.pairings.host_id, 'host_name': app.host_name,
                        'trusted_token': trusted_token, 'calibration': app.calibration.snapshot()})
            while not app.stop.is_set():
                raw = self.rfile.readline(65537)
                if not raw or len(raw) > 65536:
                    break
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError('Invalid calibration message')
                request_id = msg.get('id')
                if type(request_id) is not int or request_id <= last_id:
                    raise ValueError('Invalid calibration request sequence')
                last_id = request_id
                error = ''
                try:
                    if msg.get('op') != 'calibration':
                        raise ValueError('Unsupported phone operation')
                    action = msg.get('action')
                    if action == 'start':
                        app.calibration.start(phone)
                    elif action == 'complete':
                        app.calibration.complete(phone, msg.get('run_id'), msg.get('pairs'))
                    elif action == 'apply':
                        app.calibration.apply(phone, msg.get('run_id'))
                    elif action == 'cancel':
                        app.calibration.cancel(phone)
                    elif action != 'status':
                        raise ValueError('Unsupported calibration action')
                except (ValueError, RuntimeError) as problem:
                    error = str(problem)
                except OSError:
                    error = 'Could not save calibration; check the Windows app and retry'
                phone.send({'reply': request_id, 'ok': not bool(error), 'error': error,
                            'calibration': app.calibration.snapshot()})
        except (OSError, ValueError, TypeError):
            pass
        finally:
            app.calibration.detach(phone)
            phone.close()


class ThreadServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class HttpHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass  # Never log media or pairing tokens.

    def reply(self, code, data, mime='application/json'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def local_allowed(self):
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        return host in allowed and (origin is None or origin in {'http://' + h for h in allowed})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        app = self.server.app
        path = urlsplit(self.path).path
        if self.server.local_ui:
            if not self.local_allowed():
                return self.reply(403, {'error': 'Local UI only'})
            if path == '/':
                page = (Path(__file__).parent / 'controller.html').read_text(encoding='utf-8')
                return self.reply(200, page.replace('__TOKEN__', app.ui_token).encode(), 'text/html; charset=utf-8')
            if path == '/api/status' and hmac.compare_digest(self.headers.get('X-Control-Token', ''), app.ui_token):
                try:
                    return self.reply(200, app.snapshot())
                except Exception as e:
                    return self.reply(503, {'error': str(e)})
            if path == '/api/diagnostics' and hmac.compare_digest(self.headers.get('X-Control-Token', ''), app.ui_token):
                return self.reply(200, app.diagnostic_report())
            return self.reply(404, {'error': 'Not found'})
        expected = f'/media/{app.media_token}/'
        if not app.media or not path.startswith(expected) or path.count('/') != 3:
            return self.reply(404, {'error': 'Not found'})
        # Capture file identity now: a concurrent load cannot change this response.
        media = app.media
        try:
            with media.open('rb', buffering=0) as f:
                size = os.fstat(f.fileno()).st_size
                try:
                    bounds = parse_range(self.headers.get('Range'), size)
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                start, end = bounds if bounds else (0, size - 1)
                self.send_response(206 if bounds else 200)
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Type', mimetypes.guess_type(media)[0] or 'application/octet-stream')
                self.send_header('Cache-Control', 'private, no-transform')
                if bounds:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                if self.command == 'HEAD':
                    return
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = f.read(min(1024 * 1024, remaining))
                    if not block:
                        self.close_connection = True
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (OSError, ConnectionError):
            self.close_connection = True

    def do_POST(self):
        app = self.server.app
        if not self.server.local_ui or not self.local_allowed() or urlsplit(self.path).path != '/api/action':
            return self.reply(403, {'error': 'Local UI only'})
        if not hmac.compare_digest(self.headers.get('X-Control-Token', ''), app.ui_token):
            return self.reply(403, {'error': 'Invalid control token'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                self.close_connection = True
                return self.reply(400, {'error': 'Invalid body length'})
            app.action(json.loads(self.rfile.read(length)))
            self.reply(200, {'ok': True})
        except Exception as e:
            self.reply(400, {'error': str(e)})


def lan_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(('192.0.2.1', 9))  # routing lookup only; no datagram is sent
            return s.getsockname()[0]
        except OSError:
            return '127.0.0.1'


class HostRuntime:
    """Own the same host services for both CLI and desktop, including rollback."""
    def __init__(self, args, mpv_factory=Mpv):
        self.args = args
        self.app = Coordinator(args, mpv_factory)
        self.servers = []
        self.serving = []
        self.discovery = None
        self.closed = False

    def start(self):
        try:
            for address, field, local in [('127.0.0.1', 'ui_port', True),
                                          ('0.0.0.0', 'media_port', False)]:
                server = ThreadingHTTPServer((address, getattr(self.args, field)), HttpHandler)
                server.daemon_threads = True
                server.app, server.local_ui = self.app, local
                self.servers.append(server)
                setattr(self.args, field, server.server_port)
            control = ThreadServer(('0.0.0.0', self.args.control_port), ControlHandler)
            control.app = self.app
            self.servers.append(control)
            self.args.control_port = control.server_address[1]
            for service in self.servers:
                thread = threading.Thread(target=service.serve_forever, daemon=True)
                thread.start()
                self.serving.append(service)
            for target in (self.app.monitor, self.app.heartbeat, self.app.remote_worker, self.app.sample_audio):
                threading.Thread(target=target, daemon=True).start()
            try:
                self.discovery = DiscoveryServer(self.app, port=self.args.discovery_port)
                self.args.discovery_port = self.discovery.socket.getsockname()[1]
                threading.Thread(target=self.discovery.serve, daemon=True).start()
            except OSError as e:
                self.app.log('LAN discovery unavailable; use Advanced connection: ' + str(e))
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.app.close()
        if self.discovery:
            self.discovery.close()
        for service in self.servers:
            if service in self.serving:
                service.shutdown()
            service.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mpv', default='mpv.exe')
    parser.add_argument('--device', help='Exact wasapi/... HDMI name from --list-devices')
    parser.add_argument('--host', default=lan_address(), help='LAN IPv4 advertised to TV')
    parser.add_argument('--ui-port', type=int, default=8764)
    parser.add_argument('--media-port', type=int, default=8765)
    parser.add_argument('--control-port', type=int, default=8766)
    parser.add_argument('--discovery-port', type=int, default=DISCOVERY_PORT)
    parser.add_argument('--data-dir', default=str(Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'DualTheater-RobustSync'),
                        help='Private settings/log directory (default: DualTheater-RobustSync app data)')
    parser.add_argument('--sync-mode', choices=('baseline', 'servo', 'audio-clock'), default='audio-clock',
                        help='Timing algorithm; change only with the host stopped')
    parser.add_argument('--list-devices', action='store_true')
    parser.add_argument('--diagnostic', action='store_true', help='Allow PCM only for development; not an Atmos test')
    args = parser.parse_args()
    if args.list_devices:
        subprocess.run([args.mpv, '--no-config', '--audio-device=help'], check=True)
        return
    runtime = HostRuntime(args)
    app = runtime.app
    try:
        runtime.start()
        print(f'Controller: http://127.0.0.1:{args.ui_port}\n'
              f'TV app: choose {app.host_name}; first-time pairing code: {app.pair_code}\n'
              f'Advanced connection: {args.host}:{args.control_port}; token: {app.pair_token}\n'
              f'Logs: {app.log_dir}\nKeep this terminal open. Ctrl+C stops both players.', flush=True)
        app.stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()


if __name__ == '__main__':
    main()
