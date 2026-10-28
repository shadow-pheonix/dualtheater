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
from .diagnostics import SessionDiagnostics

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


class Coordinator:
    def __init__(self, args, mpv_factory=Mpv):
        self.args, self.mpv_factory = args, mpv_factory
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
        self.anchor_ms = 0.0
        self.duration_ms = 0.0
        self.offset_file = self.data_dir / 'calibration.json'
        if self.offset_file.exists():
            try:
                self.offset_ms = finite(json.loads(self.offset_file.read_text())['video_lead_ms'], -2000, 2000)
            except (ValueError, KeyError, OSError):
                pass
        self.audio_info = {}
        self.audio_sample = {}
        self.drift_ms = None
        self.speed = 1.0
        self.last_correction = 0
        self.servo = VideoServo()
        self.diagnostics = SessionDiagnostics()
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
                'audio_tracks': self.mpv.get('track-list', []) if self.mpv and self.state not in ('loading', 'seeking') else []}

    def diagnostic_report(self):
        # This path performs no mpv IPC and never copies a raw snapshot/log.
        p = self.peer
        status_seen = p.status_seen if p else None
        return self.diagnostics.report(
            state=self.state, connected=bool(p and not p.closed), status=p.status if p else {},
            status_age_ms=(ns() - status_seen) / 1e6 if status_seen is not None else None,
            epoch=self.epoch, audio=self.audio_info, video_lead_ms=self.offset_ms)

    def tv(self):
        if not self.peer or self.peer.closed:
            raise RuntimeError('Connect the TV companion first')
        if ns() - self.peer.seen > 2_000_000_000:
            raise RuntimeError('TV telemetry is stale')
        return self.peer

    def pause_both(self, reason='paused'):
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
        video_at = start_at + round(max(0, -self.offset_ms) * 1e6)
        audio_at = start_at + round(max(0, self.offset_ms) * 1e6)
        p.request('arm', epoch=self.epoch, host_ns=video_at, offset_ns=clock.offset_ns)
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
                audio_started = True
            if self.cancel.wait(.002 if ns() >= start_at else .01):
                raise RuntimeError('Start cancelled')
            if p.closed or ns() - p.seen > 1_000_000_000:
                raise RuntimeError('TV disconnected before start')
            if p.status.get('state') in ('buffering', 'error'):
                raise RuntimeError('TV became unready before start')
        if not audio_started:
            self.mpv.pause(False)
        self.state = 'playing'
        self.last_correction = ns()
        self.log('Started epoch ' + str(self.epoch))

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
                    self.offset_ms = finite(body['milliseconds'], -2000, 2000)
                    self.offset_file.write_text(json.dumps({'video_lead_ms': self.offset_ms}), encoding='utf-8')
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
        while not self.stop.wait(.5):
            p = self.peer
            if p and not p.closed:
                try:
                    p.send({'op': 'ping', 't0': ns()})
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
                sample = self.mpv.audio_sample()
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
                release_host = frame['release_ns'] - clock.offset_ns
                if abs(now - release_host) > 500_000_000:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Video frame telemetry stalled')
                    continue
                if sample['uncertainty_ms'] > 10 or clock.rtt_ns > 30_000_000:
                    if now - self.last_correction > 3_000_000_000:
                        raise RuntimeError('Clock measurements too uncertain to maintain sync')
                    continue
                video_ms = frame['position_ms'] + (sample['host_ns'] - release_host) / 1e6 * s.get('speed', 1)
                self.drift_ms = video_ms - (sample['position_ms'] + self.offset_ms)
                speed, hard = self.servo.update(self.drift_ms)
                self.diagnostics.timing(self.drift_ms, clock.rtt_ns / 1e6, sample['uncertainty_ms'])
                self.csv.writerow([sample['host_ns'], self.epoch, sample['position_ms'], video_ms,
                                   self.drift_ms, speed, clock.rtt_ns / 1e6, sample['uncertainty_ms']])
                self.csv_file.flush()
                self.last_correction = now
                if hard:
                    self.recover(sample['position_ms'], f'Sustained {self.drift_ms:.0f} ms drift', 'drift')
                elif abs(speed - self.speed) > .0001:
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
            hello = json.loads(self.rfile.readline(65537))
            if hello.get('op') != 'hello' or hello.get('version') != 1:
                return
            try:
                trusted_token = app.pairings.authenticate(hello.get('token'), hello.get('client_id'),
                    hello.get('device', 'Android TV'), app.pair_token, app.pair_code, self.client_address[0])
            except (ValueError, OSError) as e:
                self.wfile.write((json.dumps({'op': 'auth_required', 'error': str(e)}) + '\n').encode())
                return
            if app.peer and not app.peer.closed:
                self.wfile.write(b'{"error":"A TV is already connected"}\n')
                return
            peer = Peer(self.request, self.rfile)
            peer.remote_controls = hello.get('remote_controls') is True
            app.peer = peer
            welcome = {'op': 'welcome', 'version': 1, 'remote_controls': True,
                       'host_id': app.pairings.host_id, 'host_name': app.host_name}
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
                if msg.get('op') == 'pong':
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
            for target in (self.app.monitor, self.app.heartbeat, self.app.remote_worker):
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
    parser.add_argument('--data-dir', help='Private settings/log directory (default: source folder)')
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
