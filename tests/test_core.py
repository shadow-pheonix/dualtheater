import argparse
import hashlib
import http.client
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from host import server
from host.sync import ClockFilter, VideoServo, parse_range
from host.mpv import Mpv


class ClockTests(unittest.TestCase):
    def test_offset_and_outlier_filter(self):
        clock = ClockFilter()
        base, offset = 10_000_000_000, 4_000_000_000
        for i in range(3):
            t = base + i * 100_000_000
            self.assertTrue(clock.add(t, t + offset + 1_000_000,
                                      t + offset + 1_100_000, t + 2_100_000))
        best = clock.best(base + 500_000_000)
        self.assertEqual(best.offset_ns, offset)
        self.assertEqual(best.rtt_ns, 2_000_000)
        clock.add(base, base + offset + 50_000_000, base + offset + 50_000_000, base + 80_000_000)
        self.assertEqual(clock.best(base + 500_000_000).offset_ns, offset)
        self.assertIsNone(clock.best(base + 20_000_000_000))
        self.assertFalse(clock.add(10, 20, 30, 15))

    def test_servo_converges_under_200ppm_clock_drift(self):
        servo = VideoServo()
        error, speed = 80.0, 1.0
        for _ in range(6000):  # ten simulated minutes at 10 Hz
            error += (speed - 1 + .0002) * 100
            speed, hard = servo.update(error)
            self.assertFalse(hard)
            self.assertTrue(.995 <= speed <= 1.005)
        self.assertLess(abs(error), 20)

    def test_servo_sign_and_hard_recovery(self):
        servo = VideoServo()
        for _ in range(6): speed, hard = servo.update(80)
        self.assertLess(speed, 1)
        servo.reset()
        for _ in range(6): speed, hard = servo.update(-80)
        self.assertGreater(speed, 1)
        for _ in range(25): speed, hard = servo.update(300)
        self.assertTrue(hard)

    def test_range_boundaries(self):
        for value, expected in [('bytes=0-0', (0, 0)), ('bytes=90-', (90, 99)),
                                ('bytes=-10', (90, 99)), ('bytes=-200', (0, 99)),
                                ('bytes=0-200', (0, 99))]:
            self.assertEqual(parse_range(value, 100), expected)
        for value in ['bytes=-0', 'bytes=100-', 'bytes=20-10', 'bytes=0-1,2-3', 'bytes=a-b']:
            with self.assertRaises(ValueError): parse_range(value, 100)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = bytes(range(256)) * 16384
        self.path = Path(self.tmp.name) / 'movie.mkv'
        self.path.write_bytes(self.data)
        self.app = argparse.Namespace(media=self.path, media_token='test-secret', ui_token='control-secret')
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.HttpHandler)
        self.http.app, self.http.local_ui = self.app, False
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.tmp.cleanup()

    def request(self, path='/media/test-secret/mkv', method='GET', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_original_bytes_and_concurrent_ranges(self):
        code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(hashlib.sha256(body).digest(), hashlib.sha256(self.data).digest())
        results = []
        def part(a, b):
            c, h, data = self.request(headers={'Range': f'bytes={a}-{b}'})
            results.append((c, h['Content-Range'], data, a, b))
        threads = [threading.Thread(target=part, args=(i * 1000, i * 1000 + 499)) for i in range(12)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(results), 12)
        for c, h, data, a, b in results:
            self.assertEqual(c, 206); self.assertEqual(data, self.data[a:b+1])
            self.assertEqual(h, f'bytes {a}-{b}/{len(self.data)}')

    def test_head_unsatisfiable_and_auth(self):
        code, headers, body = self.request(method='HEAD')
        self.assertEqual((code, len(body)), (200, 0))
        self.assertEqual(int(headers['Content-Length']), len(self.data))
        code, h, body = self.request(headers={'Range': f'bytes={len(self.data)}-'})
        self.assertEqual(code, 416)
        self.assertEqual(h['Content-Range'], f'bytes */{len(self.data)}')
        self.assertEqual(self.request('/media/wrong/mkv')[0], 404)
        self.assertEqual(self.request('/api/status')[0], 404)

    def test_control_host_origin_and_token(self):
        self.http.local_ui = True
        self.assertEqual(self.request('/api/status', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.request('/api/status', headers={'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/status')[0], 404)


class FakeMpv:
    def __init__(self, *args):
        self.position = 0; self.start_ns = 0; self.paused = True; self.loaded = False
        self.commands = []; self.aid = 1
    def launch(self): pass
    def command(self, *args):
        self.commands.append(args)
        if args[0] == 'loadfile': self.loaded = True
        if args[:2] == ('set_property', 'aid'): self.aid = args[2]
    def current(self):
        return self.position + (0 if self.paused else (server.ns() - self.start_ns) / 1e6)
    def pause(self, value=True):
        self.position = self.current(); self.start_ns = server.ns(); self.paused = value
    def seek(self, seconds): self.position = seconds * 1000; self.start_ns = server.ns()
    def get(self, name, default=None):
        return {'idle-active': not self.loaded, 'seeking': False, 'time-pos': self.current() / 1000,
                'duration': 300, 'track-list': [{'type': 'audio', 'codec': 'truehd', 'id': 1}],
                'audio-out-params': {'format': 'spdif-truehd'},
                'paused-for-cache': False, 'eof-reached': False}.get(name, default)
    def verify(self): return {'valid': True}
    def audio_sample(self): return {'position_ms': self.current(), 'host_ns': server.ns(), 'uncertainty_ms': 0}
    def close(self): self.pause()


class SimulatedTV:
    def __init__(self, port, token, remote_controls=True):
        self.sock = socket.create_connection(('127.0.0.1', port))
        self.file = self.sock.makefile('rb')
        self.lock = threading.Lock(); self.closed = False
        self.epoch = 0; self.position = 0; self.start_ns = server.ns(); self.playing = False
        self.speed = 1; self.state = 'idle'; self.offset_ns = 8_000_000_000
        self.armed = None
        self.timing_valid = True
        self.remote_results = {}; self.remote_sequence = 0; self.coordinator = {}
        self.send({'op': 'hello', 'version': 1, 'token': token, 'device': 'Protocol test peer',
                   'remote_controls': remote_controls})
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.telemetry, daemon=True).start()
    def current(self): return self.position + ((server.ns() - self.start_ns) / 1e6 * self.speed if self.playing else 0)
    def send(self, msg):
        with self.lock:
            if not self.closed: self.sock.sendall((json.dumps(msg) + '\n').encode())
    def read(self):
        try:
            for raw in self.file:
                msg = json.loads(raw); op = msg['op']
                if op == 'welcome': continue
                if op == 'coordinator': self.coordinator = msg; continue
                if op == 'remote_result': self.remote_results[msg['request']] = msg; continue
                if op == 'ping':
                    now = server.ns() + self.offset_ns
                    self.send(dict(op='pong', t0=msg['t0'], t1=now, t2=now)); continue
                if msg.get('epoch', 0) < self.epoch: continue
                self.epoch = msg.get('epoch', self.epoch)
                if op == 'pause':
                    self.position = self.current(); self.playing = False; self.armed = None
                if op in ('load', 'seek'):
                    self.playing = False; self.position = msg['position_ms']; self.state = 'ready'; self.armed = None
                if op == 'arm': self.armed = msg['host_ns']
                if op == 'speed':
                    self.position = self.current(); self.start_ns = server.ns(); self.speed = msg['value']
                self.send({'reply': msg['id'], 'epoch': self.epoch})
        except (OSError, ValueError): pass
    def telemetry(self):
        try:
            while not self.closed:
                now = server.ns()
                if self.armed and now >= self.armed:
                    self.start_ns = self.armed; self.armed = None; self.playing = True
                self.send({'op': 'status', 'epoch': self.epoch, 'state': self.state, 'position_ms': self.current(),
                           'seek_pending': False, 'playing': self.playing, 'speed': self.speed,
                           'frame': {'epoch': self.epoch, 'position_ms': self.current(),
                                     'release_ns': now + self.offset_ns, 'valid': self.playing and self.timing_valid}})
                time.sleep(.025)
        except OSError: pass
    def remote(self, action, seconds=None, toggle=False, epoch=None, request=None):
        self.remote_sequence += 1
        request = self.remote_sequence if request is None else request
        body = {'op': 'remote', 'request': request, 'epoch': self.epoch if epoch is None else epoch,
                'action': action}
        if seconds is not None: body['seconds'] = seconds
        if toggle: body['toggle'] = True
        self.send(body)
        return request
    def close(self):
        self.closed = True
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.sock.close()


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root_patch = patch.object(server, 'ROOT', Path(self.tmp.name)); self.root_patch.start()
        args = argparse.Namespace(host='127.0.0.1', media_port=8765, mpv='fake', device='wasapi/test', diagnostic=False)
        self.app = server.Coordinator(args, mpv_factory=FakeMpv)
        self.control = server.ThreadServer(('127.0.0.1', 0), server.ControlHandler); self.control.app = self.app
        threading.Thread(target=self.control.serve_forever, daemon=True).start()
        threading.Thread(target=self.app.heartbeat, daemon=True).start()
        threading.Thread(target=self.app.monitor, daemon=True).start()
        threading.Thread(target=self.app.remote_worker, daemon=True).start()
        self.tv = SimulatedTV(self.control.server_address[1], self.app.pair_token)
        self.wait(lambda: self.app.peer and bool(self.app.peer.status))
        self.path = Path(self.tmp.name) / 'movie.mkv'; self.path.write_bytes(b'fixture')
    def tearDown(self):
        self.tv.close(); self.app.close(); self.control.shutdown(); self.control.server_close()
        self.root_patch.stop(); self.tmp.cleanup()
    def wait(self, predicate, seconds=5):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(.02)
        self.fail('Condition timed out: ' + self.app.state + ' ' + self.app.error)
    def test_load_start_pause_seek_track_and_disconnect(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        self.assertEqual(self.app.state, 'paused')
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertLess(abs(self.app.drift_ms), 50)
        self.app.action({'action': 'pause'})
        self.assertTrue(self.app.mpv.paused)
        self.app.action({'action': 'seek', 'seconds': 90})
        self.assertAlmostEqual(self.app.mpv.current(), 90000, delta=1)
        self.app.action({'action': 'track', 'aid': 1})
        self.app.action({'action': 'play'})
        self.tv.close()
        self.wait(lambda: self.app.state == 'error')
        self.assertTrue(self.app.mpv.paused)
    def test_calibration_deadline_sign_and_cancel(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        self.app.action({'action': 'offset', 'milliseconds': 150})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertLess(abs(self.app.drift_ms), 50)
        self.app.action({'action': 'pause'})
        self.app.action({'action': 'offset', 'milliseconds': -150})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        time.sleep(.3)
        self.assertLess(abs(self.app.drift_ms), 50)
        self.app.action({'action': 'pause'})
        errors = []
        def start():
            try: self.app.action({'action': 'play'})
            except RuntimeError as e: errors.append(str(e))
        thread = threading.Thread(target=start); thread.start()
        self.wait(lambda: self.app.state == 'armed')
        self.app.action({'action': 'pause'}); thread.join(5)
        self.assertEqual(self.app.state, 'paused')
        self.assertTrue(self.app.mpv.paused)
        self.assertTrue(errors)

    def test_buffering_recovery_and_stale_timing_watchdog(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        self.app.action({'action': 'play'})
        old_epoch = self.app.epoch
        self.tv.state = 'buffering'
        self.wait(lambda: self.app.epoch > old_epoch and self.app.state == 'playing')
        self.assertTrue(self.app.recoveries)
        self.assertEqual(self.app.diagnostic_report()['recoveries']['buffering'], 1)
        self.tv.timing_valid = False
        self.wait(lambda: self.app.state == 'error', seconds=5)
        self.assertTrue(self.app.mpv.paused)
        self.assertIn('timing unavailable', self.app.error)

    def remote(self, action, seconds=None, **values):
        request = self.tv.remote(action, seconds, **values)
        self.wait(lambda: request in self.tv.remote_results, seconds=8)
        return self.tv.remote_results[request]

    def test_tv_remote_seek_and_toggle_share_sync_barrier(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        self.assertTrue(self.remote('toggle')['ok'])
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertLess(abs(self.app.drift_ms), 50)
        old_epoch = self.app.epoch
        self.assertTrue(self.remote('seek', 90)['ok'])
        self.assertGreater(self.app.epoch, old_epoch)
        self.assertEqual(self.app.state, 'playing')
        self.assertAlmostEqual(self.app.mpv.current(), 90000, delta=500)
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertLess(abs(self.app.drift_ms), 50)
        self.assertTrue(self.remote('toggle')['ok'])
        self.assertEqual(self.app.state, 'paused')
        self.assertTrue(self.app.mpv.paused)
        self.assertTrue(self.remote('seek', 20)['ok'])
        self.assertEqual(self.app.state, 'paused')
        self.assertAlmostEqual(self.app.mpv.current(), 20000, delta=1)
        self.assertTrue(self.remote('toggle')['ok'])
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertLess(abs(self.app.drift_ms), 50)
        self.assertFalse(any(command[:2] == ('set_property', 'speed') for command in self.app.mpv.commands))

    def test_tv_remote_rejects_stale_duplicate_and_unsupported_commands(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        epoch = self.app.epoch
        stale = self.remote('seek', 90, epoch=epoch - 1)
        self.assertFalse(stale['ok'])
        self.assertEqual(self.app.epoch, epoch)
        bad = self.remote('run')
        self.assertFalse(bad['ok'])
        self.assertEqual(self.app.state, 'paused')
        self.tv.remote_results.pop(1)
        duplicate = self.remote('toggle', request=1)
        self.assertFalse(duplicate['ok'])
        self.assertEqual(self.app.state, 'paused')

    def test_tv_remote_seek_preview_and_center_toggle_are_atomic(self):
        self.app.action({'action': 'load', 'path': str(self.path)})
        # Middle button during a seek preview also toggles the intended play state.
        self.assertTrue(self.remote('seek', 299.999, toggle=True)['ok'])
        self.assertEqual(self.app.state, 'playing')
        self.assertEqual(self.app.anchor_ms, 299900)
        self.assertTrue(self.remote('seek', 100, toggle=True)['ok'])
        self.assertEqual(self.app.state, 'paused')
        self.assertAlmostEqual(self.app.mpv.current(), 100000, delta=1)

    def test_old_tv_client_does_not_receive_new_control_messages(self):
        self.tv.close()
        self.wait(lambda: self.app.peer.closed)
        self.tv = SimulatedTV(self.control.server_address[1], self.app.pair_token, remote_controls=False)
        self.wait(lambda: self.app.peer and not self.app.peer.closed and bool(self.app.peer.status))
        self.assertFalse(self.app.peer.remote_controls)
        time.sleep(.6)
        self.assertEqual(self.tv.coordinator, {})
        self.app.action({'action': 'load', 'path': str(self.path)})
        rejected = self.remote('toggle')
        self.assertFalse(rejected['ok'])
        self.assertIn('not negotiated', rejected['error'])
        self.assertEqual(self.app.state, 'paused')


class PassthroughTests(unittest.TestCase):
    def test_pcm_is_rejected(self):
        audio = Mpv('unused', 'unused', Path('.'))
        values = {'current-ao': 'wasapi', 'audio-out-params': {'format': 'float'},
                  'audio-codec-name': 'truehd', 'audio-decoder': 'truehd'}
        audio.get = lambda name, default=None: values.get(name, default)
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'): audio.verify()
        values['audio-out-params'] = {'format': 'spdif-truehd'}
        self.assertTrue(audio.verify()['valid'])


if __name__ == '__main__': unittest.main()
