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
import re
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
from .library import Library
from .discovery import DiscoveryServer, DISCOVERY_PORT
from .diagnostics import SessionDiagnostics, receiver_report
from .calibration import CalibrationService
from .timing import AffineClock, AudioTimeline, AdaptiveServo, TimingUnavailable
from .datagram_timing import DatagramTimingService
from .session_log import SessionLog
from .end_tail import EndTail

ROOT = Path(__file__).resolve().parent.parent


class TrackSelectionRejected(ValueError):
    """The requested choice failed, but the previous working track was restored."""


def ns():
    return time.perf_counter_ns()


def finite(value, low, high):
    if isinstance(value, bool):
        raise ValueError('A finite number is required')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Value must be between {low} and {high}')
    return value


def safe_client_error(message):
    """Return bounded guidance without leaking host paths or endpoint details."""
    text = str(message or '').lower()
    if not text: return ''
    if 'previous track restored' in text:
        return 'Requested audio track is unavailable. Previous track restored.'
    if 'movie changed' in text or 'media generation' in text or 'epoch changed' in text:
        return 'Movie changed. Reopen playback options and try again.'
    if 'subtitle' in text or 'text track' in text:
        return 'Subtitle selection is unavailable. Refresh playback options.'
    if any(term in text for term in ('audio', 'codec', 'passthrough', 'hdmi')):
        return 'Audio selection is unavailable. Check the Windows player and HDMI output.'
    if any(term in text for term in ('storage', 'library', 'media item', 'browse')):
        return 'Storage item is unavailable. Reconnect storage or browse again.'
    if any(term in text for term in ('tv', 'clock', 'timing', 'sync')):
        return 'Playback synchronization needs attention. Reconnect the TV and retry.'
    return 'Request failed; check Windows.'


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
        self.close_reason = ''
        self.last_remote_id = 0
        self.remote_controls = False
        self.local_host = sock.getsockname()[0]
        self.timing_token = secrets.token_urlsafe(32)
        self.timing = None
        self.timing_protocol = False
        self.timing_datagrams = False
        self.role = 'tv'
        self.client_protocol = 0
        self.last_client_id = 0
        self.client_generation = 0
        self.address = sock.getpeername()[0]
        self.storage = None

    def send(self, msg):
        with self.lock:
            if self.closed:
                raise ConnectionError('TV disconnected')
            self.sock.sendall((json.dumps(msg, separators=(',', ':'), ensure_ascii=False) + '\n').encode())

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

    def close(self, reason='local_close'):
        with self.lock:
            if not self.closed:
                self.close_reason = reason
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
    transport = 'tcp'
    def __init__(self, sock):
        self.sock = sock
        # This is transport liveness, not permission to extrapolate stale audio.
        # A delayed pong must not destroy an otherwise healthy duplex session.
        # Audio-anchor expiry/clock uncertainty still stop playback separately.
        self.sock.settimeout(3)
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
        self.library = Library(self.data_dir / 'library.json')
        self.storage_providers = {}
        self.storage_items = {}
        self.ui_token = secrets.token_urlsafe(24)
        self.media_token = secrets.token_urlsafe(24)
        self.media_lock = threading.RLock()
        self.peer_lock = threading.Lock()
        self.peer = self.mpv = self.media = None
        self.datagram_timing = None
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
        self.media_generation = 0
        self.remote_media = None
        self.media_title = ''
        self.track_catalog = []
        self.raw_track_list = []
        self.audio_badge = ''
        self.selected_subtitle = 'off'
        self.client_queue = queue.Queue(maxsize=16)
        self.browse_queue = queue.Queue(maxsize=4)
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
        self.delivered_anchor = None
        self.anchor_delivery = {}
        self.source_timing = {}
        self.last_failure = None
        self.last_recovery = None
        self.video_buffering_since_ns = 0
        self.timing_error = ''
        self.last_frame_key = None
        self.last_frame_advance_ns = 0
        self.started_ns = 0
        self.end_drain = None
        self.diagnostics = SessionDiagnostics()
        self.calibration = CalibrationService(self, ROOT / 'calibration-phone-SDR-TrueHD.mkv')
        self.recoveries = deque()
        self.op_lock = threading.RLock()
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.remote_queue = queue.Queue(maxsize=8)
        self.logs = deque(maxlen=40)
        self.log_dir = self.data_dir / 'logs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.session_log = SessionLog(self.log_dir)
        self.csv_file = self.csv = self.session_log

    def log(self, text):
        line = datetime.now().strftime('%H:%M:%S') + ' ' + str(text)
        self.logs.append(line)
        self.session_log.event(line)

    def snapshot(self):
        p = self.peer
        best = p.clock.best(ns()) if p else None
        return {'state': self.state, 'error': self.error, 'file': self.media.name if self.media else (self.media_title or None),
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
                'audio_tracks': list(self.raw_track_list), 'media_generation': self.media_generation,
                'audio_badge': self.audio_badge, 'providers': self.provider_list(),
                'subtitle_tracks': self.tv_subtitles(), 'selected_subtitle': self.selected_subtitle,
                'client_state': self.client_state()}

    def provider_list(self):
        providers = self.library.providers()
        for role in ('tv', 'phone'):
            p = self.storage_providers.get(role)
            providers.append({'id': role, 'label': p['label'] if p else ('TV storage' if role == 'tv' else 'Phone storage'),
                              'available': bool(p)})
        return providers

    def tv_subtitles(self):
        p = self.peer
        rows = p.status.get('subtitle_tracks', []) if p and p.status_seen and p.status.get('epoch') == self.epoch else []
        if not isinstance(rows, list): return []
        output = []
        for row in rows[:128]:
            if not isinstance(row, dict): continue
            ident = str(row.get('id', ''))[:24]
            if not ident or (ident != 'off' and not re.fullmatch(r'\d+:\d+', ident)): continue
            output.append({'id': ident, 'label': str(row.get('label', 'Subtitle'))[:120],
                'language': str(row.get('language', ''))[:35], 'codec': str(row.get('codec', ''))[:32],
                'selected': row.get('selected') is True,
                'supported': row.get('supported') is not False,
                'format_label': str(row.get('format_label', 'Subtitle'))[:120]})
        return output

    def client_state(self):
        state = {'state': self.state, 'epoch': self.epoch, 'media_generation': self.media_generation,
                'loaded': bool(self.media or self.remote_media), 'title': self.media.stem if self.media else self.media_title,
                'position_ms': self.audio_sample.get('position_ms', self.anchor_ms) if self.state == 'playing' else self.anchor_ms,
                'duration_ms': self.duration_ms,
                'video_lead_ms': self.offset_ms, 'audio_tracks': list(self.track_catalog),
                'subtitle_tracks': self.tv_subtitles(), 'selected_subtitle': str(self.selected_subtitle)[:24],
                'audio_badge': self.audio_badge, 'providers': self.provider_list(),
                'can_control': bool(self.peer and not self.peer.closed and self.mpv
                    and self.peer.status.get('epoch') == self.epoch and self.state in ('paused', 'playing')),
                'error': safe_client_error(self.error)}
        # Keep a pathological track catalog below the clients' 64 KiB frame
        # limit. Halving is bounded and retains the selected track first.
        for key in ('audio_tracks', 'subtitle_tracks'):
            rows = state[key]
            state[key] = [r for r in rows if r.get('selected')] + [r for r in rows if not r.get('selected')]
        while len(json.dumps(state, ensure_ascii=False).encode()) > 48_000:
            key = max(('audio_tracks', 'subtitle_tracks'), key=lambda field: len(state[field]))
            if len(state[key]) <= 1:
                break
            state[key] = state[key][:max(1, len(state[key]) // 2)]
            state['catalog_truncated'] = True
        return state

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
                         'timing_transport': vocabulary(getattr(getattr(p, 'timing', None), 'transport', None), ('tcp', 'udp')),
                         'offset_profile': self.offset_profile_status(),
                         'active_video_lead_ms': self.playback_lead_ms,
                         'drift_basis': 'scheduled_release' if self.sync_mode == 'baseline' else 'media_timeline',
                         'physical_accuracy': 'unvalidated'}
        source = self.source_timing
        report['sync']['source_sampler'] = {
            'state': vocabulary(source.get('state'),
                ('fresh', 'terminal_tail', 'sample_unavailable', 'input_uncertain', 'fit_uncertain', 'clock_uncertain', 'failed')),
            'input_uncertainty_ms': number(source.get('input_uncertainty_ms'), 0),
            'fit_uncertainty_ms': number(source.get('fit_uncertainty_ms'), 0),
            'consecutive_rejections': number(source.get('consecutive_rejections'), 0),
            'observation_age_ms': number((ns() - source['observed_ns']) / 1e6, 0)
                if type(source.get('observed_ns')) is int else None,
        }
        delivery = self.anchor_delivery
        report['sync']['anchor_delivery'] = {
            'state': vocabulary(delivery.get('state'), ('fresh', 'clock_uncertain', 'sending', 'stale', 'failed')),
            'observation_age_ms': number((ns() - delivery['observed_ns']) / 1e6, 0)
                if type(delivery.get('observed_ns')) is int else None,
            'last_send_duration_ms': number(delivery.get('last_send_duration_ms'), 0),
        }
        clock = p.clock.best(ns()) if p else None
        fresh = (p and not p.closed and status_seen is not None
                 and 0 <= ns() - status_seen <= 2_000_000_000 and p.status.get('epoch') == self.epoch)
        read_ahead = p.status.get('read_ahead') if fresh else None
        read_ahead = read_ahead if isinstance(read_ahead, dict) else {}
        report['telemetry']['read_ahead'] = {
            'state': vocabulary(read_ahead.get('state'),
                ('disabled', 'low_storage', 'idle', 'preparing', 'queued', 'running', 'ready', 'suspended', 'error', 'closing', 'closed')),
            **{key: number(read_ahead.get(key), 0) for key in
               ('ahead_bytes', 'cache_bytes', 'downloaded_bytes', 'failures', 'chunks',
                'cache_budget_bytes', 'lookahead_bytes', 'foreground_wait_ms', 'max_foreground_wait_ms')},
        }
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
            remote_clock_anchor_age_ms=number(remote.get('anchor_age_ms'), 0),
            remote_clock_uncertainty_ms=number(remote.get('uncertainty_ms'), 0),
            rendered_callback_present=bool(observed),
            release_to_render_ms=number((observed['rendered_ns'] - observed['release_ns']) / 1e6, 0, 500)
                if type(observed.get('rendered_ns')) is int and type(observed.get('release_ns')) is int else None)
        report['receiver'] = receiver_report(self.receiver_observations)
        report['last_failure'] = self.last_failure
        report['last_recovery'] = self.last_recovery
        report['logging'] = self.session_log.metrics()
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

    def claim_tv(self, sock, reader, hello):
        # No network write or operation-lock wait while reserving the slot.
        with self.peer_lock:
            if self.peer and not self.peer.closed:
                return None
            peer = Peer(sock, reader)
            peer.client_protocol = 1 if hello.get('client_protocol') == 1 else 0
            peer.remote_controls = hello.get('remote_controls') is True
            peer.timing_protocol = hello.get('timing_protocol') == 2
            peer.timing_datagrams = (hello.get('timing_datagrams') is True
                and self.datagram_timing is not None and self.sync_mode != 'baseline')
            if self.sync_mode != 'baseline':
                peer.clock = AffineClock()
            self.peer = peer
            return peer

    def pause_both(self, reason='paused'):
        latest = self.latest_anchor or self.audio_sample
        self.audio_running.clear()
        self.latest_anchor = None
        self.delivered_anchor = None
        self.end_drain = None
        self.epoch += 1
        errors = []
        if self.mpv:
            if self.state == 'playing':
                self.anchor_ms = max(0, (latest or {}).get('position_ms', self.anchor_ms) or 0)
                try:
                    self.anchor_ms = max(0, (self.mpv.get('time-pos', 0) or 0) * 1000)
                except Exception as error:
                    errors.append(error)
            try:
                self.mpv.pause()
            except Exception as error:
                errors.append(error)
        if self.peer and not self.peer.closed:
            try:
                self.peer.request('pause', epoch=self.epoch)
            except Exception as error:
                errors.append(error)
        self.state = reason
        self.speed = 1.0
        self.servo.reset()
        self.last_frame_key = None
        self.last_frame_advance_ns = 0
        self.video_buffering_since_ns = 0
        if errors:
            raise errors[0]

    def fail(self, message):
        # A coordinated pause resets the TV clock. Preserve only the already
        # allowlisted pre-pause observations, so the cause survives that reset.
        try:
            report = self.diagnostic_report()
            self.last_failure = {key: report[key] for key in ('state', 'telemetry', 'sync')}
            if self.peer and hasattr(self.peer.clock, 'observations'):
                self.last_failure['clock_observations'] = self.peer.clock.observations(ns())
        except Exception:
            pass  # Diagnostics must never delay or prevent pausing both devices.
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

    def ensure_timing(self, seconds=8):
        if self.sync_mode == 'baseline':
            return
        p = self.tv()
        if not p.timing_protocol:
            raise RuntimeError('This sync mode requires the matching DualTheater TV app')
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if self.cancel.is_set() or self.stop.is_set():
                raise RuntimeError('Operation cancelled')
            if self.tv() is not p:
                raise RuntimeError('TV connection changed; reconnect and reload')
            if p.status.get('error') and p.status.get('timing_error_only') is not True:
                raise RuntimeError(p.status['error'])
            if p.timing and not p.timing.closed and p.clock.best(ns()) is not None:
                return
            time.sleep(.05)
        raise TimingUnavailable()

    @staticmethod
    def validate_media(path):
        if not isinstance(path, (str, os.PathLike)):
            raise ValueError('Choose a movie file')
        media = Path(path).expanduser().resolve(strict=True)
        if not media.is_file() or media.suffix.lower() not in ('.mkv', '.mp4', '.m2ts', '.ts'):
            raise ValueError('Choose an MKV, MP4, M2TS or TS file')
        return media

    def load(self, path, aid='auto'):
        self.tv()
        media = self.validate_media(path)
        if not self.args.diagnostic and not self.args.device:
            raise ValueError('Choose an explicit WASAPI HDMI endpoint in Start.ps1 or --device')
        self.pause_both('loading')
        self.ensure_timing()
        if self.mpv:
            self.mpv.close()
        with self.media_lock:
            self.media = media
            self.remote_media = None
            self.media_title = media.stem
            self.media_token = secrets.token_urlsafe(24)
            self.media_generation += 1
            self.raw_track_list = []; self.track_catalog = []; self.audio_badge = ''; self.selected_subtitle = 'off'
        self.video_context = {}
        self.anchor_ms = 0
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
        self.raw_track_list = list(tracks) if isinstance(tracks, list) else []
        self.track_catalog = self.make_track_catalog(tracks)
        self.audio_badge = self.badge_for(self.track_catalog)
        tv_selected = peer.status.get('selected_subtitle', 'off')
        self.selected_subtitle = tv_selected if isinstance(tv_selected, str) and (tv_selected == 'off' or re.fullmatch(r'\d+:\d+', tv_selected)) else 'off'
        self.log('Prepared ' + media.name + '; audio=' + json.dumps(self.audio_info))
        self.log('Audio tracks: ' + json.dumps([t for t in tracks if t.get('type') == 'audio']))
        self.state = 'paused'

    def validate_request(self, body):
        action = body.get('action')
        if action == 'load':
            self.validate_media(body.get('path'))
        elif action == 'offset':
            finite(body.get('milliseconds'), -2000, 2000)
        elif action == 'seek':
            if not self.mpv:
                raise ValueError('Load a file first')
            duration = self.duration_ms / 1000 if self.duration_ms > 0 else (self.mpv.get('duration', 86400) or 0)
            finite(body.get('seconds'), 0, max(0, duration - .1))
            if not isinstance(body.get('play_after', self.state == 'playing'), bool):
                raise ValueError('play_after must be a boolean')

    @staticmethod
    def make_track_catalog(tracks):
        rows = []
        allowed = {'truehd', 'ac3', 'eac3', 'dts', 'dts-hd', 'dts-hd-ma'}
        codec_names = {'truehd': 'Dolby TrueHD', 'ac3': 'Dolby Digital', 'eac3': 'Dolby Digital Plus',
                       'dts': 'DTS', 'dts-hd': 'DTS-HD', 'dts-hd-ma': 'DTS-HD MA'}
        language_names = {'eng': 'English', 'en': 'English', 'tel': 'Telugu', 'te': 'Telugu',
            'hin': 'Hindi', 'hi': 'Hindi', 'spa': 'Spanish', 'es': 'Spanish', 'fra': 'French',
            'fre': 'French', 'fr': 'French', 'deu': 'German', 'ger': 'German', 'de': 'German',
            'ita': 'Italian', 'it': 'Italian', 'jpn': 'Japanese', 'ja': 'Japanese',
            'por': 'Portuguese', 'pt': 'Portuguese', 'rus': 'Russian', 'ru': 'Russian',
            'ara': 'Arabic', 'ar': 'Arabic'}
        for track in tracks if isinstance(tracks, list) else []:
            if not isinstance(track, dict) or track.get('type') != 'audio':
                continue
            codec = str(track.get('codec', '')).lower().replace('_', '-')[:32]
            profile = str(track.get('codec-profile', '')).lower().replace(' ', '-')
            if codec == 'dts' and 'dts-hd' in profile:
                codec = 'dts-hd-ma' if profile.endswith('ma') else 'dts-hd'
            title = str(track.get('title') or '')[:100]
            language_raw = str(track.get('lang') or track.get('language') or '')[:35]
            language = language_names.get(language_raw.lower(), language_raw)
            layout = str(track.get('demux-channels') or track.get('demux-channel-layout')
                         or track.get('channel-layout') or '').strip()[:32]
            if not layout:
                channels = track.get('demux-channel-count', track.get('channels'))
                if isinstance(channels, (int, float)) and not isinstance(channels, bool) and channels > 0:
                    layout = f'{int(channels)} channels'
                elif isinstance(channels, str) and channels.isdigit() and int(channels) > 0:
                    layout = f'{int(channels)} channels'
            codec_label = codec_names.get(codec, codec.upper() if codec else 'Unknown audio')
            tags = title.lower()
            atmos_positive = bool(re.search(r'\batmos\b', tags))
            atmos_negative = bool(re.search(r'\b(?:no|without|non[- ]?)\s*atmos\b', tags))
            dtsx_positive = bool(re.search(r'\bdts\s*:?\s*x\b|\bdtsx\b', tags))
            dtsx_negative = bool(re.search(r'\b(?:no|without|non[- ]?)\s*dts\s*:?\s*x\b', tags))
            qualification = ('Atmos' if atmos_positive and not atmos_negative else
                             ('DTS:X' if dtsx_positive and not dtsx_negative else ''))
            details = [codec_label]
            if layout: details.append(layout)
            format_label = ' · '.join(details)
            if qualification: format_label += ' · ' + qualification + ' (track title)'
            label = ' · '.join(part for part in (title, language, format_label) if part)
            rows.append({'id': str(track.get('id', '')), 'label': label[:200], 'language': language,
                         'codec': codec, 'selected': bool(track.get('selected')),
                         'supported': codec in allowed, 'format_label': format_label[:120]})
        return rows[:128]

    @staticmethod
    def badge_for(tracks):
        selected = next((row for row in tracks if row.get('selected')), None)
        return ' · '.join(part for part in (selected.get('language'), selected.get('format_label')) if part)[:120] if selected else ''

    def storage_register(self, peer, message):
        if peer.client_protocol != 1:
            raise ValueError('Storage sharing requires client protocol 1')
        port, token = message.get('port'), message.get('token')
        label = message.get('label', 'Android storage')
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Invalid Android storage port')
        if not isinstance(token, str) or not 16 <= len(token) <= 128 or not all(c.isalnum() or c in '-_' for c in token):
            raise ValueError('Invalid Android storage capability')
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError('Invalid Android storage label')
        role = peer.role
        with self.media_lock:
            prior = self.storage_providers.get(role)
            if prior and prior.get('peer') is peer and prior.get('token') == token and prior.get('port') == port:
                prior['label'] = label.strip()
                peer.storage = role
                return
            if prior and self.remote_media and self.remote_media.get('source', {}).get('peer') is prior.get('peer'):
                self.remote_media['detached'] = True
            self.storage_items = {key: item for key, item in self.storage_items.items() if item['provider'] != role}
            self.storage_providers[role] = {'address': peer.address, 'port': port, 'token': token,
                                            'label': label.strip(), 'peer': peer}
            peer.storage = role

    def storage_detach(self, peer):
        with self.media_lock:
            role = peer.storage
            if role and self.storage_providers.get(role, {}).get('peer') is peer:
                self.storage_providers.pop(role, None)
                self.storage_items = {key: item for key, item in self.storage_items.items() if item['provider'] != role}
                peer.storage = None
                if self.remote_media and self.remote_media.get('provider') == role:
                    self.remote_media['detached'] = True

    def storage_unregister(self, peer):
        role = peer.role
        current = self.storage_providers.get(role)
        if current and current.get('peer') is peer:
            self.storage_detach(peer)
        return {'removed': True}

    def android_request(self, provider, path, headers=None, max_bytes=1_048_576):
        import http.client
        with self.media_lock: source = self.storage_providers.get(provider)
        if not source or source.get('peer') is None or source['peer'].closed:
            raise ValueError('Android storage is disconnected; reconnect and share it again')
        conn = http.client.HTTPConnection(source['address'], source['port'], timeout=8)
        try:
            conn.request('GET', '/' + source['token'] + path, headers=headers or {})
            response = conn.getresponse()
            if response.status not in (200, 206):
                raise ValueError('Android storage could not serve this item')
            length = response.getheader('Content-Length')
            if length and int(length) > max_bytes:
                raise ValueError('Android storage response exceeds limit')
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError('Android storage response exceeds limit')
            return response.status, dict(response.getheaders()), data
        except (OSError, http.client.HTTPException):
            raise ValueError('Android storage is unavailable; reconnect and retry') from None
        finally:
            conn.close()

    @staticmethod
    def _safe_android_entry(entry):
        if not isinstance(entry, str) or len(entry) > 128 or not entry or not all(c.isalnum() or c in '-_' for c in entry):
            raise ValueError('Invalid Android storage entry')
        return entry

    def browse_provider(self, provider, entry='', cursor=0):
        if provider == 'windows': return self.library.browse(entry, cursor)
        if provider not in ('tv', 'phone'): raise ValueError('Unknown library provider')
        if type(cursor) is not int or not 0 <= cursor <= 1_000_000: raise ValueError('Invalid browse cursor')
        if entry: entry = self._safe_android_entry(entry)
        from urllib.parse import quote
        with self.media_lock: expected_source = self.storage_providers.get(provider)
        path = '/browse?entry=' + quote(entry, safe='') + '&cursor=' + str(cursor)
        _, _, data = self.android_request(provider, path)
        try:
            result = json.loads(data)
            if not isinstance(result, dict) or not isinstance(result.get('entries'), list): raise ValueError()
            parent = result.get('parent', '')
            parent = self._safe_android_entry(parent) if parent else ''
            label = str(result.get('label', 'Android storage'))[:120]
            clean_entries = []
            with self.media_lock: source = self.storage_providers.get(provider)
            if not source or source is not expected_source or source['peer'].closed:
                raise ValueError('Android storage disconnected; browse again')
            for row in result['entries'][:100]:
                if not isinstance(row, dict) or not isinstance(row.get('id'), str): continue
                ident = self._safe_android_entry(row['id'])
                name = str(row.get('name', ''))[:255]
                directory = row.get('directory') is True
                if not name or '/' in name or '\\' in name or name in ('.', '..'): continue
                clean = {'id': ident, 'name': name, 'directory': directory}
                if not directory and type(row.get('size')) is int and row['size'] > 0:
                    clean['size'] = row['size']
                    clean['seekable'] = row.get('seekable') is True
                clean_entries.append(clean)
                if not directory and clean.get('seekable'):
                    if len(self.storage_items) >= 20000:
                        self.storage_items.pop(next(iter(self.storage_items)))
                    self.storage_items[(provider, ident)] = {'provider': provider, 'source': source.copy(),
                        'name': name, 'size': clean['size']}
            next_cursor = result.get('next_cursor')
            if type(next_cursor) is not int or not 0 <= next_cursor <= 1_000_000: next_cursor = None
            result = {'provider': provider, 'entry': entry, 'parent': parent, 'label': label,
                      'entries': clean_entries, 'next_cursor': next_cursor}
            return result
        except (ValueError, TypeError):
            raise ValueError('Android storage returned an invalid browse page')

    def load_library_entry(self, provider, entry, autoplay=False):
        if not isinstance(autoplay, bool): raise ValueError('autoplay must be a boolean')
        if provider == 'windows':
            path = self.library.resolve_file(entry)
            self.action({'action': 'load', 'path': str(path)})
            if autoplay: self.action({'action': 'play'})
            return {'loaded': True, 'title': path.stem}
        if provider not in ('tv', 'phone'): raise ValueError('Unknown library provider')
        entry = self._safe_android_entry(entry)
        info = self.storage_items.get((provider, entry))
        if not info or info['provider'] != provider: raise ValueError('Android item expired; browse again')
        with self.media_lock: active = self.storage_providers.get(provider)
        if not active or active.get('peer') is not info['source'].get('peer') or active.get('token') != info['source'].get('token'):
            raise ValueError('Android storage session changed; browse again')
        name = str(info.get('name', 'media.mkv'))[:255]
        suffix = Path(name).suffix.lower()
        if suffix not in ('.mkv', '.mp4', '.m2ts', '.ts'): raise ValueError('Choose an MKV, MP4, M2TS or TS file')
        self.tv()
        if not self.args.diagnostic and not self.args.device: raise ValueError('Choose an explicit WASAPI HDMI endpoint')
        self.pause_both('loading'); self.ensure_timing()
        if self.mpv: self.mpv.close()
        with self.media_lock: active = self.storage_providers.get(provider)
        if not active or active.get('peer') is not info['source'].get('peer') or active.get('token') != info['source'].get('token'):
            raise ValueError('Android storage disconnected; browse again')
        with self.media_lock:
            self.media = None
            self.media_title = Path(name).stem
            self.remote_media = {'provider': provider, 'entry': entry, 'size': info['size'], 'name': name,
                                 'source': info['source'], 'suffix': suffix[1:], 'detached': False}
            self.media_generation += 1
            self.media_token = secrets.token_urlsafe(24)
            self.raw_track_list = []; self.track_catalog = []; self.audio_badge = ''; self.selected_subtitle = 'off'
        self.video_context = {}; self.anchor_ms = 0
        url = f'http://127.0.0.1:{self.args.media_port}/media/{self.media_token}/{suffix[1:]}'
        self.mpv = self.mpv_factory(self.args.mpv, self.args.device, self.log_dir, self.args.diagnostic)
        self.mpv.launch(); self.mpv.command('set_property', 'user-data/dualtheater-aid', 'auto')
        self.mpv.command('loadfile', url, 'replace')
        self.epoch += 1; peer = self.tv()
        peer.request('load', epoch=self.epoch,
            url=f'http://{peer.local_host}:{self.args.media_port}/media/{self.media_token}/{suffix[1:]}', position_ms=0)
        self.wait_for(lambda p: self.ready(p, 0))
        self.audio_info = self.mpv.verify(); self.duration_ms = (self.mpv.get('duration', 0) or 0) * 1000
        tracks = self.mpv.get('track-list', [])
        self.raw_track_list = list(tracks) if isinstance(tracks, list) else []
        self.track_catalog = self.make_track_catalog(tracks)
        self.audio_badge = self.badge_for(self.track_catalog)
        tv_selected = peer.status.get('selected_subtitle', 'off')
        self.selected_subtitle = tv_selected if isinstance(tv_selected, str) and (tv_selected == 'off' or re.fullmatch(r'\d+:\d+', tv_selected)) else 'off'
        self.state = 'paused'
        if autoplay: self.start()

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
        if not self.mpv or not (self.media or self.remote_media):
            raise RuntimeError('Load a file first')
        p = self.tv()
        if self.sync_mode != 'baseline':
            self.ensure_timing()
            self.timing_error = ''
        else:
            self.wait_for(lambda p: p.clock.best(ns()) is not None, seconds=8)
        self.audio_info = self.mpv.verify()
        if not prepared:
            self.prepare(self.anchor_ms)
        self.wait_for(lambda q: q.status.get('epoch') == self.epoch and q.status.get('state') == 'ready'
                      and not q.status.get('seek_pending', True), seconds=10)
        clock = p.clock.best(ns())
        if not clock or (self.sync_mode == 'baseline' and clock.rtt_ns > 30_000_000):
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
            anchor = self.delivered_anchor
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
                    if self.sync_mode == 'audio-clock' and (not s.get('remote_clock', {}).get('reads_recent')
                            or s.get('remote_clock', {}).get('state') not in ('locked', 'slewing', 'holdover')):
                        continue
                    return
        raise RuntimeError('Scheduled start did not produce fresh audio and video progress')


    def sample_audio(self):
        """Local source observations must never wait for a TV socket write."""
        model, model_epoch, rejected = AudioTimeline(), -1, 0
        while not self.stop.wait(.04):
            if self.sync_mode == 'baseline' or not self.audio_running.is_set():
                model.reset()
                continue
            epoch, mpv, peer = self.epoch, self.mpv, self.peer
            if epoch != model_epoch:
                model.reset(); model_epoch = epoch; rejected = 0
            if not mpv or not peer or peer.closed:
                continue
            try:
                tail = self.end_drain
                if tail and tail.epoch == epoch and tail.peer is peer and tail.audio_done:
                    model.sequence += 1
                    anchor = tail.project(ns(), model.sequence)
                    if self.epoch == epoch and self.end_drain is tail and self.audio_running.is_set():
                        self.latest_anchor = anchor
                        self.source_timing = {'state': 'terminal_tail', 'observed_ns': ns(),
                            'fit_uncertainty_ms': anchor['uncertainty_ms'], 'consecutive_rejections': 0}
                    continue
                sample = mpv.timed_audio_sample()
                if self.epoch != epoch or self.mpv is not mpv or not self.audio_running.is_set():
                    continue
                if self.end_drain and self.end_drain.audio_done:
                    continue  # EOF may have been observed during the IPC call.
                anchor = model.add(sample)
                if anchor is None:
                    rejected += 1
                    self.source_timing = {'state': 'sample_unavailable' if sample.get('position_ms') is None else 'input_uncertain',
                        'observed_ns': ns(), 'input_uncertainty_ms': sample.get('uncertainty_ms'),
                        'consecutive_rejections': rejected}
                    continue
                if anchor['uncertainty_ms'] > 10:
                    rejected += 1
                    self.source_timing = {'state': 'fit_uncertain', 'observed_ns': ns(),
                        'input_uncertainty_ms': sample.get('uncertainty_ms'),
                        'fit_uncertainty_ms': anchor['uncertainty_ms'], 'consecutive_rejections': rejected}
                    continue
                if ns() - anchor['host_ns'] > 250_000_000:
                    raise RuntimeError('Source audio samples are too old')
                anchor.update(epoch=epoch)
                self.latest_anchor = anchor
                self.source_timing = {'state': 'fresh', 'observed_ns': ns(),
                    'input_uncertainty_ms': sample.get('uncertainty_ms'),
                    'fit_uncertainty_ms': anchor['uncertainty_ms'], 'consecutive_rejections': 0}
                rejected = 0
            except TimeoutError:
                # A single missed IPC observation is not a timeline jump. The
                # unchanged 750 ms last-good-source guard bounds any retry.
                if self.epoch == epoch and self.audio_running.is_set():
                    rejected += 1
                    self.source_timing = {'state': 'sample_unavailable', 'observed_ns': ns(),
                                          'consecutive_rejections': rejected}
            except Exception as e:
                if self.epoch == epoch and self.audio_running.is_set():
                    self.source_timing = {'state': 'failed', 'observed_ns': ns()}
                    self.timing_error = str(e)

    def send_audio_anchors(self):
        """One pending latest value: socket backpressure cannot stall sampling."""
        last_key = None
        while not self.stop.wait(.01):
            if self.sync_mode == 'baseline' or not self.audio_running.is_set():
                continue
            epoch, peer, anchor = self.epoch, self.peer, self.latest_anchor
            if not anchor or anchor.get('epoch') != epoch or not peer or peer.closed:
                continue
            key = (peer, epoch, anchor['sequence'])
            if key == last_key or ns() - anchor['host_ns'] > 250_000_000:
                continue
            try:
                clock = peer.clock.best(ns())
                if clock is None or clock.uncertainty_ns > 12_000_000:
                    self.anchor_delivery = {'state': 'clock_uncertain', 'observed_ns': ns()}
                    continue
                link = peer.timing
                if not link or link.closed:
                    raise RuntimeError('Dedicated timing connection lost')
                started = ns()
                self.anchor_delivery = {'state': 'sending', 'observed_ns': started}
                accepted = link.send(dict(op='anchor', epoch=epoch, sequence=anchor['sequence'],
                    local_ns=clock.remote(anchor['host_ns']),
                    position_ms=anchor['position_ms'] + self.playback_lead_ms,
                    rate=anchor['rate'] / clock.rate,
                    uncertainty_ms=anchor['uncertainty_ms'] + clock.uncertainty_ns / 1e6))
                last_key = key
                if accepted is False:
                    self.anchor_delivery = {'state': 'stale', 'observed_ns': ns()}
                    continue
                if self.epoch == epoch and self.peer is peer and self.audio_running.is_set():
                    fresh = ns() - anchor['host_ns'] <= 250_000_000
                    self.anchor_delivery = {'state': 'fresh' if fresh else 'stale', 'observed_ns': ns(),
                        'last_send_duration_ms': (ns() - started) / 1e6}
                    if fresh: self.delivered_anchor = anchor
            except Exception as e:
                if self.epoch == epoch and self.peer is peer and self.audio_running.is_set():
                    self.anchor_delivery = {'state': 'failed', 'observed_ns': ns()}
                    self.timing_error = str(e)


    def action(self, body):
        action = body.get('action')
        if action == 'library_add':
            ident = self.library.add(body.get('path', ''))
            return {'root_id': ident, 'name': Path(body.get('path', '')).name}
        if action == 'library_remove':
            self.library.remove(body.get('root_id'))
            return {'removed': True}
        if action == 'providers': return {'providers': self.provider_list()}
        if action == 'browse': return self.browse_provider(body.get('provider'), body.get('entry', ''), body.get('cursor', 0))
        if action == 'load_entry':
            with self.op_lock:
                # A rejected/expired browser choice must not interrupt the movie
                # currently playing. Validate grants before the load owns state.
                provider, entry = body.get('provider'), body.get('entry')
                if not isinstance(body.get('autoplay', False), bool) or not isinstance(entry, str):
                    raise ValueError('Invalid library selection')
                if provider == 'windows':
                    self.library.resolve_file(entry)
                elif provider in ('phone', 'tv'):
                    self._safe_android_entry(entry)
                    info = self.storage_items.get((provider, entry))
                    with self.media_lock:
                        current = self.storage_providers.get(provider)
                    if (not info or not current or info['source'].get('peer') is not current.get('peer')
                        or info['source'].get('token') != current.get('token') or current['peer'].closed):
                        raise ValueError('Android storage item expired; browse again')
                    if Path(info.get('name', '')).suffix.lower() not in ('.mkv', '.mp4', '.m2ts', '.ts'):
                        raise ValueError('Choose a supported movie from the library')
                else:
                    raise ValueError('Unknown library provider')
                self.cancel.clear(); self.error = ''
                try:
                    return self.load_library_entry(body.get('provider'), body.get('entry'), body.get('autoplay', False))
                except Exception as exc:
                    self.fail(str(exc))
                    raise
        if action == 'pause':
            self.cancel.set()  # interrupts a pending start/prepare before taking the operation lock
        with self.op_lock:
            # Reject input before taking ownership of the current playback.
            # Failures after mutation still use the coordinated failure path.
            try:
                self.validate_request(body)
            except (ValueError, TypeError, OSError):
                self.diagnostics.operation(action, 0, True)
                raise
            if action in ('track', 'subtitle'):
                if 'epoch' in body or 'media_generation' in body:
                    if (type(body.get('epoch')) is not int or type(body.get('media_generation')) is not int
                        or body['epoch'] != self.epoch or body['media_generation'] != self.media_generation):
                        raise ValueError('Movie changed; reopen playback options')
                if action == 'track':
                    aid = body.get('aid')
                    if isinstance(aid, bool) or not str(aid).isdigit(): raise ValueError('Invalid audio track ID')
                    catalog_track = next((item for item in self.track_catalog if item['id'] == str(aid)), None)
                    if not catalog_track: raise ValueError('Audio track expired; reload track catalog')
                    if not catalog_track.get('supported'):
                        raise ValueError('This audio codec cannot be passed through by the selected HDMI output')
                else:
                    sid = body.get('sid')
                    if sid != 'off' and (not isinstance(sid, str) or len(sid) > 24 or not re.fullmatch(r'\d+:\d+', sid)):
                        raise ValueError('Invalid subtitle selection')
                    if sid != 'off':
                        row = next((item for item in self.tv_subtitles() if item['id'] == sid), None)
                        if not row or not row.get('supported'):
                            raise ValueError('Subtitle track expired or unsupported; refresh playback options')
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
                    self.switch_track(str(int(body['aid'])))
                elif action == 'subtitle':
                    sid = body.get('sid')
                    self.peer.request('subtitle', epoch=self.epoch, sid=sid)
                    self.selected_subtitle = sid
                    return {'selected_subtitle': sid}
                elif action == 'resync':
                    if not self.mpv:
                        raise RuntimeError('Load a file first')
                    playing = self.state == 'playing'
                    self.prepare(self.mpv.get('time-pos', 0) * 1000)
                    if playing:
                        self.start(prepared=True)
                else:
                    raise ValueError('Unknown action')
            except TrackSelectionRejected:
                failed = True
                raise
            except Exception as e:
                failed = True
                self.fail(str(e))
                raise
            finally:
                self.diagnostics.operation(action, (ns() - operation_started) / 1e6, failed)

    def refresh_audio(self):
        self.audio_info = self.mpv.verify()
        tracks = self.mpv.get('track-list', [])
        self.raw_track_list = list(tracks) if isinstance(tracks, list) else []
        self.track_catalog = self.make_track_catalog(tracks)
        self.audio_badge = self.badge_for(self.track_catalog)

    def switch_track(self, aid):
        if not self.mpv:
            raise RuntimeError('Load a file first')
        playing, previous = self.state == 'playing', self.mpv.get('aid')
        position = (self.mpv.get('time-pos', 0) or 0) * 1000
        self.pause_both()
        try:
            self.mpv.command('set_property', 'aid', aid)
            self.prepare(position)
            self.refresh_audio()
            if playing:
                self.start(prepared=True)
        except Exception:
            self.pause_both()
            if previous is None:
                raise RuntimeError('Previous audio selection is unavailable; reload the movie')
            self.mpv.command('set_property', 'aid', str(previous))
            # An explicit Pause/cancel must never be overridden by rollback.
            if self.cancel.is_set() or self.stop.is_set():
                raise RuntimeError('Track change cancelled; previous selection restored while paused')
            self.prepare(position)
            self.refresh_audio()
            if playing:
                self.start(prepared=True)
            raise TrackSelectionRejected('Requested audio track is unavailable. Previous track restored.') from None

    def heartbeat(self):
        """TV control liveness cannot depend on optional phone/timing writes."""
        previous_peer, last_sent, last_catalog = None, 0, 0
        catalog_key = None
        while not self.stop.wait(.5 if self.sync_mode == 'baseline' else .2):
            p = self.peer
            if p and not p.closed:
                try:
                    if self.sync_mode == 'baseline':
                        p.send({'op': 'ping', 't0': ns()})
                    if p.remote_controls:
                        p.send(self.playback_status())
                    key = (p, self.epoch, self.media_generation, self.state,
                           self.selected_subtitle, self.audio_badge)
                    if p.client_protocol == 1 and (key != catalog_key or ns() - last_catalog >= 1_000_000_000):
                        p.send({'op': 'client_state', 'state': self.client_state()})
                        catalog_key, last_catalog = key, ns()
                    now = ns()
                    if previous_peer is p and now - last_sent > 1_000_000_000:
                        self.log(f'TV control send gap: {(now - last_sent) / 1e6:.0f} ms')
                    previous_peer, last_sent = p, now
                except OSError as problem:
                    p.close('control_send_timeout' if isinstance(problem, TimeoutError) else 'control_send_error')


    def timing_heartbeat(self):
        # Keep client-state broadcasts independent; v1.0 timing exchanges and
        # source-anchor delivery otherwise retain their original behavior.
        while not self.stop.wait(.2):
            p = self.peer
            link = p.timing if p and not p.closed else None
            if self.sync_mode != 'baseline' and link and not link.closed:
                try:
                    link.send({'op': 'ping'})
                except OSError as problem:
                    link.close()
                    self.log('Timing send failed: ' + type(problem).__name__)
                    if self.peer is p and p.timing is link:
                        self.timing_error = 'Dedicated timing connection lost; reconnect and reload'


    def phone_heartbeat(self):
        # Send only the current snapshot; no queue/backlog when a phone is slow.
        while not self.stop.wait(.5):
            phone = self.calibration.owner
            if phone and not phone.closed and phone.client_protocol == 1:
                try:
                    phone.send({'op': 'client_state', 'state': self.client_state()})
                except OSError:
                    phone.close()

    def playback_status(self):
        return {'op': 'coordinator', 'epoch': self.epoch, 'state': self.state,
                'loaded': self.media is not None or self.remote_media is not None, 'duration_ms': self.duration_ms,
                'position_ms': self.audio_sample.get('position_ms', self.anchor_ms)
                    if self.state == 'playing' else self.anchor_ms,
                'title': self.media.stem if self.media else self.media_title, 'error': self.error,
                'media_generation': self.media_generation}

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

    def enqueue_client(self, peer, message):
        request_id = message.get('id')
        try:
            if peer.client_protocol != 1: raise ValueError('Client protocol was not negotiated')
            if peer.closed or peer not in (self.peer, self.calibration.owner):
                raise ValueError('Client session disconnected')
            if type(request_id) is not int or request_id <= peer.last_client_id:
                raise ValueError('Duplicate or invalid client request')
            if message.get('action') not in ('providers', 'browse', 'load_entry', 'track', 'subtitle',
                                             'play', 'pause', 'seek', 'resync', 'storage_unregister'):
                raise ValueError('Unsupported client action')
            if message['action'] in ('track', 'subtitle', 'play', 'pause', 'seek', 'resync'):
                if type(message.get('epoch')) is not int or type(message.get('media_generation')) is not int:
                    raise ValueError('Missing media generation; refresh player state')
                if message['action'] == 'pause' and (message['epoch'] != self.epoch
                    or message['media_generation'] != self.media_generation):
                    raise ValueError('Movie changed; refresh player state')
            self.client_queue.put_nowait((peer, dict(message)))
            peer.last_client_id = request_id
            if (message.get('action') == 'pause' and peer not in (self.peer, self.calibration.owner)):
                return
            if (message.get('action') == 'pause' and message.get('epoch') == self.epoch
                and message.get('media_generation') == self.media_generation):
                self.cancel.set()
        except (ValueError, queue.Full) as exc:
            try: peer.send({'op': 'client_response', 'reply': request_id, 'ok': False,
                            'error': str(exc) or 'Player is busy', 'result': {}})
            except OSError: peer.close()

    def client_worker(self):
        while not self.stop.is_set():
            try: peer, message = self.client_queue.get(timeout=.2)
            except queue.Empty: continue
            result, error = {}, ''
            if message.get('action') in ('browse', 'providers'):
                try:
                    self.browse_queue.put_nowait((peer, message))
                except queue.Full:
                    if not peer.closed:
                        try: peer.send({'op': 'client_response', 'reply': message.get('id'), 'ok': False,
                                        'error': 'Library is busy; retry shortly.', 'result': {}})
                        except OSError: peer.close()
                finally:
                    self.client_queue.task_done()
                continue
            try:
                with self.op_lock:
                    if peer.closed or peer not in (self.peer, self.calibration.owner):
                        raise ValueError('Client session disconnected')
                    action = message['action']
                    if action in ('track', 'subtitle', 'play', 'pause', 'seek', 'resync'):
                        if message.get('epoch') != self.epoch or message.get('media_generation') != self.media_generation:
                            raise ValueError('Movie changed; reopen the player menu')
                    if action == 'providers': result = {'providers': self.provider_list()}
                    elif action == 'storage_unregister': result = self.storage_unregister(peer)
                    elif action == 'browse':
                        result = self.browse_provider(message.get('provider'), message.get('entry', ''), message.get('cursor', 0))
                    elif action == 'load_entry':
                        result = self.action({'action': 'load_entry', 'provider': message.get('provider'),
                                              'entry': message.get('entry'), 'autoplay': message.get('autoplay', False)}) or {}
                    elif action == 'track':
                        aid = message.get('aid')
                        row = next((item for item in self.track_catalog if item.get('id') == str(aid)), None)
                        if not row: raise ValueError('Audio track expired; reopen the track menu')
                        if not row.get('supported'): raise ValueError('This audio codec cannot be passed through by the selected HDMI output')
                        result = self.action({'action': 'track', 'aid': aid, 'epoch': message['epoch'],
                                              'media_generation': message['media_generation']}) or {}
                    elif action == 'subtitle':
                        result = self.action({'action': 'subtitle', 'sid': message.get('sid'),
                                              'epoch': message['epoch'], 'media_generation': message['media_generation']}) or {}
                    elif action in ('play', 'pause', 'resync'): self.action({'action': action})
                    elif action == 'seek':
                        result = self.action({'action': 'seek', 'seconds': message.get('seconds'),
                                              'play_after': message.get('play_after', self.state == 'playing')}) or {}
            except ValueError as exc:
                error = safe_client_error(exc)
            except Exception:
                error = 'Request failed; check Windows.'
            finally:
                self.client_queue.task_done()
            if not peer.closed:
                try: peer.send({'op': 'client_response', 'reply': message.get('id'), 'ok': not bool(error),
                                'error': error, 'result': result if not error else {}})
                except OSError: peer.close()

    def browse_worker(self):
        """Read-only provider I/O cannot hold transport's operation lock/worker."""
        while not self.stop.is_set():
            try: peer, message = self.browse_queue.get(timeout=.2)
            except queue.Empty: continue
            result, error = {}, ''
            try:
                if peer.closed or peer not in (self.peer, self.calibration.owner):
                    raise ValueError('Client session disconnected')
                if message['action'] == 'providers': result = {'providers': self.provider_list()}
                else: result = self.browse_provider(message.get('provider'), message.get('entry', ''), message.get('cursor', 0))
                if peer.closed or peer not in (self.peer, self.calibration.owner):
                    continue
            except ValueError as exc:
                error = safe_client_error(exc)
            except Exception:
                error = 'Cannot browse this source; check Windows and reconnect it.'
            finally:
                self.browse_queue.task_done()
            if not peer.closed:
                try: peer.send({'op': 'client_response', 'reply': message.get('id'), 'ok': not bool(error),
                                'error': error, 'result': result if not error else {}})
                except OSError: peer.close()

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
                    if not (self.media or self.remote_media) or not self.mpv:
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
                status_seen = p.status_seen
                s = p.status
                if status_seen is None or ns() - status_seen > 2_000_000_000:
                    raise RuntimeError('TV video status is stale')
                if s.get('epoch') != self.epoch:
                    raise RuntimeError('TV playback generation changed; reconnect and reload the movie')
                if s.get('error'):
                    raise RuntimeError(s['error'])
                # Do not act on a queued old buffer-state report. The source
                # timeline remains independently bounded while TV reports lag.
                video_fresh = status_seen is not None and ns() - status_seen <= 500_000_000
                if self.sync_mode == 'audio-clock' and video_fresh and s.get('remote_clock', {}).get('state') in (
                        'audio_anchor_expired', 'audio_phase_jump'):
                    raise RuntimeError('TV remote audio clock lost confidence')
                if self.monitor_end(p, s):
                    continue
                sample = self.mpv.audio_sample() if self.sync_mode == 'baseline' else self.latest_anchor
                if sample is None or self.sync_mode != 'baseline' and ns() - sample['host_ns'] > 750_000_000:
                    raise RuntimeError('Source audio timeline expired')
                if self.sync_mode != 'baseline' and (not self.delivered_anchor
                        or self.delivered_anchor.get('epoch') != self.epoch
                        or ns() - self.delivered_anchor['host_ns'] > 2_000_000_000):
                    raise RuntimeError('Audio timing delivery expired')
                video_buffering = video_fresh and s.get('state') == 'buffering'
                audio_buffering = self.mpv.get('paused-for-cache', False)
                if video_buffering and not audio_buffering and self.sync_mode == 'audio-clock':
                    if not self.video_buffering_since_ns: self.video_buffering_since_ns = ns()
                    if ns() - self.video_buffering_since_ns < 200_000_000:
                        continue  # The external master clock keeps advancing on TV.
                elif not video_buffering:
                    self.video_buffering_since_ns = 0
                if video_buffering or audio_buffering:
                    report = self.diagnostic_report()
                    self.last_recovery = {'source': 'both' if video_buffering and audio_buffering else
                        'video' if video_buffering else 'audio',
                        **{key: report[key] for key in ('telemetry', 'sync')}}
                    position = self.mpv.get('time-pos', 0) * 1000
                    self.recover(position, 'TV video buffer underrun' if video_buffering else 'HDMI player cache underrun', 'buffering')
                    continue
                if video_fresh and not s.get('playing', False):
                    raise RuntimeError('TV stopped unexpectedly; playback paused')
                self.audio_sample = sample
                if sample['position_ms'] is None:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('mpv audio clock unavailable')
                    continue
                if now > verify_at:
                    self.audio_info = self.mpv.verify()
                    verify_at = now + 2_000_000_000
                now = ns()
                # A delayed status packet is not evidence that the renderer
                # stopped. tv() still enforces the existing 2 s telemetry limit;
                # source/TV anchor expiry is independently enforced above/on TV.
                if status_seen is None or now - status_seen > 500_000_000:
                    continue
                frame = s.get('frame') or {}
                if not frame or frame.get('epoch') != self.epoch or not frame.get('valid'):
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Fresh frame timing unavailable; cannot maintain sync')
                    continue
                if self.sync_mode != 'baseline':
                    key = (self.epoch, frame.get('sequence'))
                    if key == self.last_frame_key:
                        if now - self.last_frame_advance_ns > 1_000_000_000:
                            raise RuntimeError('Unique video frame telemetry stalled')
                        continue
                    self.last_frame_key = key
                    self.last_frame_advance_ns = now
                clock = p.clock.best(now)
                if not clock:
                    if self.sync_mode == 'baseline':
                        raise RuntimeError('Clock synchronization expired')
                    continue  # Fresh-anchor guard above enforces the same 750 ms deadline.
                if self.sync_mode != 'baseline' and clock.uncertainty_ns > 12_000_000:
                    continue
                release_host = (frame['release_ns'] - clock.offset_ns if self.sync_mode == 'baseline'
                                else clock.host(frame.get('presentation_ns', frame['release_ns'])))
                if abs(now - release_host) > 500_000_000:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Video frame telemetry stalled')
                    continue
                # Affine modes already validate the causal phase uncertainty
                # above. A delayed exchange can still support a narrow valid
                # interval; do not impose the baseline's RTT heuristic too.
                if sample['uncertainty_ms'] > 10 or (self.sync_mode == 'baseline' and clock.rtt_ns > 30_000_000):
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

    def monitor_end(self, peer, status):
        audio_done = bool(self.mpv.get('eof-reached', False))
        video_done = status.get('state') == 'ended'
        if not (audio_done or video_done or self.end_drain):
            return False
        if audio_done and video_done:
            self.pause_both('ended')
            self.log('End of media')
            return True
        now = ns()
        tail = self.end_drain
        if tail is None:
            audio_ms = self.mpv.get('time-pos')
            audio_ms = audio_ms * 1000 if audio_ms is not None else (self.latest_anchor or self.audio_sample).get('position_ms', self.anchor_ms)
            tail = EndTail(self.epoch, peer, now, self.duration_ms, audio_ms,
                           status.get('position_ms', -1), self.playback_lead_ms)
            if audio_done and self.sync_mode != 'baseline':
                tail.audio_ended(self.latest_anchor, now)
            elif audio_done:
                tail.audio_done = True
            self.end_drain = tail
        if tail.epoch != self.epoch or tail.peer is not peer or now > tail.deadline_ns:
            raise RuntimeError('Final media tail did not complete in time')
        if audio_done and not tail.audio_done:
            if self.sync_mode != 'baseline':
                tail.audio_ended(self.latest_anchor, now)
            else:
                tail.audio_done = True
        if not audio_done:
            if self.mpv.get('paused-for-cache', False):
                raise RuntimeError('Audio stalled during the final media tail')
            if self.sync_mode != 'baseline':
                anchor = self.latest_anchor
                if not anchor or anchor.get('epoch') != self.epoch or now - anchor['host_ns'] > 750_000_000:
                    raise RuntimeError('Source audio timeline expired')
        if self.sync_mode != 'baseline':
            delivered = self.delivered_anchor
            if not delivered or delivered.get('epoch') != self.epoch or now - delivered['host_ns'] > 2_000_000_000:
                raise RuntimeError('Audio timing delivery expired')
        if not video_done and status.get('state') != 'buffering':
            if not status.get('playing'):
                raise RuntimeError('Video stopped during the final media tail')
            frame = status.get('frame') or {}
            key = (self.epoch, frame.get('sequence', frame.get('release_ns')))
            if frame.get('valid') and key != self.last_frame_key:
                self.last_frame_key, self.last_frame_advance_ns = key, now
            elif now - (self.last_frame_advance_ns or self.started_ns) > 1_000_000_000:
                raise RuntimeError('Video stalled during the final media tail')
        return True


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
        reason = 'server_stopped'
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
                self.handle_calibration(trusted_token, hello.get('client_protocol') == 1)
                return
            if hello.get('role') not in (None, 'tv'):
                return
            peer = app.claim_tv(self.request, self.rfile, hello)
            if peer is None:
                self.wfile.write(b'{"error":"A TV is already connected"}\n')
                return
            welcome = {'op': 'welcome', 'version': 1, 'remote_controls': True,
                       'host_id': app.pairings.host_id, 'host_name': app.host_name,
                       'sync_mode': app.sync_mode, 'timing_token': peer.timing_token}
            if peer.timing_datagrams:
                welcome.update(timing_transport='udp', timing_udp_port=app.datagram_timing.port)
            if peer.client_protocol: welcome['client_protocol'] = 1
            if trusted_token:
                welcome['trusted_token'] = trusted_token
            peer.send(welcome)
            app.log('TV connected: ' + str(hello.get('device', 'Android TV')))
            while not app.stop.is_set():
                raw = self.rfile.readline(65537)
                if not raw or len(raw) > 65536:
                    reason = 'eof' if not raw else 'oversized_frame'
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
                elif msg.get('op') == 'client_request':
                    app.enqueue_client(peer, msg)
                elif msg.get('op') == 'storage_register':
                    request_id = msg.get('id')
                    try:
                        if type(request_id) is not int or request_id <= peer.last_client_id:
                            raise ValueError('Invalid storage registration sequence')
                        peer.last_client_id = request_id
                        app.storage_register(peer, msg)
                        peer.send({'op': 'client_response', 'reply': request_id, 'ok': True, 'error': '',
                                   'result': {'provider': peer.role, 'available': True}})
                    except ValueError as exc:
                        peer.send({'op': 'client_response', 'reply': request_id, 'ok': False,
                                   'error': str(exc)[:200], 'result': {}})
                elif 'reply' in msg:
                    with peer.lock:
                        waiter = peer.pending.get(msg['reply'])
                    if waiter:
                        waiter.put(msg)
        except (OSError, ValueError, KeyError, TypeError) as problem:
            if not app.stop.is_set():
                reason = ('read_timeout' if isinstance(problem, TimeoutError) else
                          'socket_error' if isinstance(problem, OSError) else 'invalid_message')
        finally:
            if peer:
                app.storage_detach(peer)
                peer.close(reason)
                app.diagnostics.disconnected()
                app.log('TV disconnected: ' + peer.close_reason)

    def handle_timing(self, hello):
        app, link = self.server.app, None
        reason = 'session_closed'
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
            clock = AffineClock()
            peer.clock = clock
        try:
            link.send({'op': 'timing_ready', 'version': 2})
            while not app.stop.is_set() and app.peer is peer and not peer.closed:
                raw = self.rfile.readline(4097)
                if not raw or len(raw) > 4096:
                    reason = 'eof' if not raw else 'oversized_frame'
                    break
                t3 = ns()
                msg = json.loads(raw)
                if msg.get('op') != 'pong':
                    reason = 'unexpected_operation'
                    break
                t0 = msg.get('t0')
                if type(t0) is not int or t0 > t3:
                    reason = 'invalid_reply'
                    break
                # TCP can deliver old replies after a brief network stall. They
                # are unusable clock observations, not a broken connection.
                if t0 < t3 - 1_000_000_000:
                    continue
                clock.add(msg['t0'], msg['t1'], msg['t2'], t3)
        except (OSError, ValueError, KeyError, TypeError) as problem:
            reason = type(problem).__name__
        finally:
            link.close()
            app.log('Timing connection closed: ' + reason)
            if app.peer is peer and peer.timing is link and app.audio_running.is_set():
                app.timing_error = 'Dedicated timing connection lost; reconnect and reload'

    def handle_calibration(self, trusted_token, client_protocol=False):
        app = self.server.app
        phone = Peer(self.request, self.rfile)
        phone.role = 'phone'
        phone.client_protocol = 1 if client_protocol else 0
        last_id = 0
        try:
            app.calibration.attach(phone)
            welcome = {'op': 'welcome', 'version': 1, 'role': 'calibration', 'calibration_protocol': 1,
                        'capture_diagnostics': True,
                        'host_id': app.pairings.host_id, 'host_name': app.host_name,
                        'trusted_token': trusted_token, 'calibration': app.calibration.snapshot()}
            if phone.client_protocol: welcome['client_protocol'] = 1
            phone.send(welcome)
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
                if msg.get('op') == 'storage_register':
                    try:
                        app.storage_register(phone, msg)
                        phone.send({'op': 'client_response', 'reply': request_id, 'ok': True, 'error': '',
                                    'result': {'provider': 'phone', 'available': True}})
                    except ValueError as problem:
                        phone.send({'op': 'client_response', 'reply': request_id, 'ok': False,
                                    'error': str(problem)[:200], 'result': {}})
                    continue
                if msg.get('op') == 'client_request':
                    app.enqueue_client(phone, msg)
                    continue
                error = ''
                try:
                    if msg.get('op') != 'calibration':
                        raise ValueError('Unsupported phone operation')
                    action = msg.get('action')
                    if action == 'start':
                        app.calibration.start(phone)
                    elif action == 'complete':
                        app.calibration.complete(phone, msg.get('run_id'), msg.get('pairs'))
                    elif action == 'capture_progress':
                        app.calibration.progress(phone, msg.get('run_id'), msg.get('capture'))
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
            app.storage_detach(phone)
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
        media_lock = getattr(app, 'media_lock', None)
        if media_lock:
            with media_lock:
                active_token, media, remote_media = app.media_token, app.media, getattr(app, 'remote_media', None)
        else:
            active_token, media, remote_media = app.media_token, app.media, None
        expected = f'/media/{active_token}/'
        if not (media or remote_media) or not path.startswith(expected) or path.count('/') != 3:
            return self.reply(404, {'error': 'Not found'})
        if remote_media:
            return self._proxy_android(app, remote_media)
        # Capture file identity now: a concurrent load cannot change this response.
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

    def _proxy_android(self, app, media):
        import http.client
        import urllib.parse
        if media.get('detached'):
            self.close_connection = True
            return self.reply(410, {'error': 'Android storage disconnected'})
        source = media.get('source') or {}
        peer = source.get('peer')
        if not self._android_source_active(app, media, source):
            self.close_connection = True
            return self.reply(410, {'error': 'Android storage disconnected'})
        conn = http.client.HTTPConnection(source['address'], source['port'], timeout=15)
        path = '/' + source['token'] + '/file/' + urllib.parse.quote(media['entry'], safe='')
        headers = {}
        if self.headers.get('Range'): headers['Range'] = self.headers['Range']
        try:
            conn.request(self.command, path, headers=headers)
            upstream = conn.getresponse()
            if upstream.status not in (200, 206, 416):
                self.close_connection = True
                return self.reply(502, {'error': 'Android storage could not serve media'})
            length = upstream.getheader('Content-Length')
            content_range = upstream.getheader('Content-Range')
            if upstream.status == 416:
                self.send_response(416)
                if content_range: self.send_header('Content-Range', content_range)
                self.send_header('Content-Length', '0'); self.end_headers(); return
            if not length or not length.isdigit() or int(length) > media['size']:
                self.close_connection = True
                return self.reply(502, {'error': 'Invalid Android media response'})
            requested = self.headers.get('Range')
            if requested:
                try: expected = parse_range(requested, media['size'])
                except ValueError:
                    self.send_response(416); self.send_header('Content-Range', f"bytes */{media['size']}")
                    self.send_header('Content-Length', '0'); self.end_headers(); return
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range or '')
                if upstream.status != 206 or not match or tuple(map(int, match.groups())) != (*expected, media['size']):
                    self.close_connection = True
                    return self.reply(502, {'error': 'Android storage returned an invalid byte range'})
                if int(length) != expected[1] - expected[0] + 1:
                    self.close_connection = True
                    return self.reply(502, {'error': 'Android storage returned an invalid byte count'})
            elif upstream.status != 200 or int(length) != media['size']:
                self.close_connection = True
                return self.reply(502, {'error': 'Android storage did not serve the original file'})
            if not self._android_source_active(app, media, source):
                self.close_connection = True
                return self.reply(410, {'error': 'Android storage disconnected'})
            self.send_response(upstream.status)
            self.send_header('Content-Length', length)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Type', mimetypes.guess_type(media['name'])[0] or 'application/octet-stream')
            self.send_header('Cache-Control', 'private, no-transform')
            if content_range: self.send_header('Content-Range', content_range)
            self.end_headers()
            if self.command == 'HEAD': return
            remaining = int(length)
            while remaining:
                if not self._android_source_active(app, media, source):
                    self.close_connection = True; break
                block = upstream.read(min(256 * 1024, remaining))
                if not block:
                    self.close_connection = True; break
                self.wfile.write(block); remaining -= len(block)
        except (OSError, http.client.HTTPException, ConnectionError):
            self.close_connection = True
        finally:
            conn.close()

    @staticmethod
    def _android_source_active(app, media, source):
        peer = source.get('peer')
        lock = getattr(app, 'media_lock', None)
        if lock:
            with lock:
                active = app.storage_providers.get(media.get('provider'))
                return (not media.get('detached') and peer is not None and not peer.closed
                        and active is not None and active.get('peer') is peer
                        and active.get('token') == source.get('token'))
        active = app.storage_providers.get(media.get('provider'), {})
        return (not media.get('detached') and peer is not None and not peer.closed
                and active.get('peer') is peer and active.get('token') == source.get('token'))

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
            result = app.action(json.loads(self.rfile.read(length)))
            self.reply(200, {'ok': True, 'result': result})
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
        self.datagram_timing = None
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
            try:
                self.datagram_timing = DatagramTimingService(self.app, ('0.0.0.0', self.args.control_port))
                self.app.datagram_timing = self.datagram_timing
                threading.Thread(target=self.datagram_timing.serve, daemon=True).start()
            except OSError:
                self.app.log('UDP timing unavailable; dedicated TCP timing retained')
            for service in self.servers:
                thread = threading.Thread(target=service.serve_forever, daemon=True)
                thread.start()
                self.serving.append(service)
            for target in (self.app.monitor, self.app.heartbeat, self.app.timing_heartbeat,
                           self.app.phone_heartbeat, self.app.remote_worker,
                           self.app.client_worker, self.app.browse_worker, self.app.browse_worker,
                           self.app.sample_audio, self.app.send_audio_anchors):
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
        if self.datagram_timing:
            self.datagram_timing.close()
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
