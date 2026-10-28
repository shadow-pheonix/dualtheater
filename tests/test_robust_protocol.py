"""Real coordinator/socket failure tests with simulated endpoints, no HDMI."""
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from host.desktop_support import runtime_args
from host.server import HostRuntime, ns
import test_core


class TimedMpv(test_core.FakeMpv):
    def timed_audio_sample(self):
        return self.audio_sample() | {'source': 'mpv_source_clock'}


class TimingTV:
    def __init__(self, port, token, progress=True):
        self.port, self.progress = port, progress
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.reader = self.sock.makefile('rb')
        self.lock = threading.Lock()
        self.closed = False; self.timing = None; self.speed_commands = 0
        self.offset = 8_000_000_000; self.epoch = 0; self.position = 0
        self.started = ns(); self.playing = False; self.state = 'idle'; self.armed = None
        self.anchor = None; self.frame_sequence = 0; self.mode = ''; self.speed = 1
        self.send({'op': 'hello', 'version': 1, 'token': token, 'timing_protocol': 2})
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.telemetry, daemon=True).start()

    def current(self):
        if not self.playing: return self.position
        if self.anchor and self.mode == 'audio-clock':
            return self.anchor['position_ms'] + (ns() + self.offset - self.anchor['local_ns']) / 1e6 * self.anchor['rate']
        return self.position + (ns() - self.started) / 1e6 * self.speed

    def send(self, msg):
        with self.lock:
            if not self.closed: self.sock.sendall((json.dumps(msg) + '\n').encode())

    def timing_read(self, token):
        try:
            self.timing = socket.create_connection(('127.0.0.1', self.port), timeout=5)
            self.timing.sendall((json.dumps({'op': 'hello', 'version': 1, 'role': 'timing', 'token': token}) + '\n').encode())
            for raw in self.timing.makefile('rb'):
                m = json.loads(raw)
                if m['op'] == 'ping':
                    now = ns() + self.offset
                    self.timing.sendall((json.dumps({'op': 'pong', 't0': m['t0'], 't1': now, 't2': now}) + '\n').encode())
                elif m['op'] == 'anchor' and m['epoch'] == self.epoch:
                    self.anchor = m
        except (OSError, ValueError): pass

    def read(self):
        try:
            for raw in self.reader:
                m = json.loads(raw); op = m['op']
                if op == 'welcome':
                    self.mode = m['sync_mode']
                    threading.Thread(target=self.timing_read, args=(m['timing_token'],), daemon=True).start(); continue
                if op in ('coordinator', 'remote_result'): continue
                if m.get('epoch', 0) < self.epoch: continue
                self.epoch = m.get('epoch', self.epoch)
                if op == 'pause':
                    self.position = self.current(); self.playing = False; self.armed = None; self.anchor = None
                elif op in ('load', 'seek'):
                    self.position = m['position_ms']; self.state = 'ready'; self.anchor = None
                elif op == 'arm': self.armed = m['video_ns'] - self.offset
                elif op == 'speed':
                    self.speed_commands += 1; self.position = self.current(); self.started = ns(); self.speed = m['value']
                self.send({'reply': m['id'], 'epoch': self.epoch})
        except (OSError, ValueError): pass

    def telemetry(self):
        try:
            while not self.closed:
                now = ns()
                if self.armed and now >= self.armed and self.progress:
                    self.started = self.armed; self.armed = None; self.playing = True
                self.frame_sequence += 1
                self.send({'op': 'status', 'epoch': self.epoch, 'state': self.state,
                    'position_ms': self.current(), 'sample_ns': now + self.offset,
                    'seek_pending': False, 'playing': self.playing, 'speed': self.speed,
                    'remote_clock': {'state': 'locked', 'reads_recent': self.playing, 'renderer_error_ms': 0},
                    'frame': {'epoch': self.epoch, 'sequence': self.frame_sequence, 'position_ms': self.current(),
                              'release_ns': now + self.offset, 'valid': self.playing}})
                time.sleep(.025)
        except (OSError, ValueError): pass

    def close_timing(self):
        if self.timing:
            try: self.timing.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self.timing.close()

    def close(self):
        self.closed = True; self.close_timing()
        try: self.sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.sock.close()


class RobustProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = HostRuntime(runtime_args('unused', 'wasapi/test', self.tmp.name, ephemeral=True), mpv_factory=TimedMpv)
        self.runtime.start(); self.app = self.runtime.app; self.tv = None
        self.movie = Path(self.tmp.name) / 'test.mkv'; self.movie.write_bytes(b'simulated movie')

    def tearDown(self):
        if self.tv: self.tv.close()
        self.runtime.close(); self.tmp.cleanup()

    def wait(self, predicate, seconds=6):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(.025)
        self.fail('Condition timed out: ' + self.app.state + ' ' + self.app.error)

    def connect(self, progress=True):
        self.tv = TimingTV(self.runtime.args.control_port, self.app.pair_token, progress)
        self.wait(lambda: self.app.peer and self.app.peer.clock.best(ns()) is not None)

    def test_start_seek_and_stream_loss_never_change_audio_or_compete_with_clock(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertEqual(self.tv.speed_commands, 0)
        self.assertEqual(self.app.sync_mode, 'audio-clock')
        self.app.action({'action': 'seek', 'seconds': 90})
        self.assertEqual(self.app.state, 'playing')
        self.assertAlmostEqual(self.app.mpv.current(), 90000, delta=1000)
        self.tv.close_timing()
        self.wait(lambda: self.app.state == 'error')
        self.assertTrue(self.app.mpv.paused)
        self.assertFalse(any(c[:2] == ('set_property', 'speed') for c in self.app.mpv.commands))

    def test_arm_ack_without_progress_is_rejected_and_both_pause(self):
        self.connect(progress=False)
        self.app.action({'action': 'load', 'path': str(self.movie)})
        with self.assertRaisesRegex(RuntimeError, 'progress'):
            self.app.action({'action': 'play'})
        self.assertTrue(self.app.mpv.paused)
        self.assertEqual(self.app.state, 'error')

    def test_pair_code_cannot_open_timing_role_and_profiles_are_mode_specific(self):
        self.connect()
        with socket.create_connection(('127.0.0.1', self.runtime.args.control_port), timeout=2) as s:
            s.sendall((json.dumps({'op': 'hello', 'version': 1, 'role': 'timing', 'token': self.app.pair_code}) + '\n').encode())
            self.assertEqual(s.recv(1), b'')
        self.app.action({'action': 'offset', 'milliseconds': 75})
        for mode in ('baseline', 'servo'):
            other = HostRuntime(runtime_args('unused', 'wasapi/test', self.tmp.name, ephemeral=True, sync_mode=mode))
            try: self.assertEqual(other.app.offset_ms, 0)
            finally: other.close()

    def test_servo_mode_uses_source_samples_and_reports_its_algorithm(self):
        # Select the mode before any peer exists; a fresh coordinator is what the UI does.
        self.runtime.close()
        self.runtime = HostRuntime(runtime_args('unused', 'wasapi/test', self.tmp.name,
            ephemeral=True, sync_mode='servo'), mpv_factory=TimedMpv)
        self.runtime.start(); self.app = self.runtime.app
        self.connect(); self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        self.assertEqual(self.app.diagnostic_report()['sync']['mode'], 'servo')
        self.assertEqual(self.app.latest_anchor['source'], 'mpv_source_clock')

    def test_saved_offset_changes_at_the_next_barrier_not_in_live_audio_anchors(self):
        self.connect(); self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.app.action({'action': 'offset', 'milliseconds': -200})
        time.sleep(.2)
        self.assertEqual(self.app.playback_lead_ms, 0)
        self.assertEqual(self.app.state, 'playing')
        self.app.action({'action': 'resync'})
        self.assertEqual(self.app.playback_lead_ms, -200)
        self.assertEqual(self.app.state, 'playing')

    def test_phone_can_measure_without_apply_then_save_only_this_modes_offset(self):
        import test_calibration
        self.connect()
        phone = test_calibration.Phone(self.runtime)
        try:
            reply = phone.request('start'); self.assertTrue(reply['ok'])
            self.wait(lambda: self.app.calibration.snapshot()['state'] == 'playing')
            run = self.app.calibration.snapshot()['run_id']
            self.assertEqual(self.app.offset_ms, 0)
            reply = phone.request('complete', run_id=run,
                pairs=[{'gap_ms': 20, 'uncertainty_ms': 5}] * 6)
            self.assertTrue(reply['ok'], reply)
            self.wait(lambda: self.app.calibration.snapshot()['state'] == 'measured')
            self.assertEqual(self.app.offset_ms, 0)
            self.assertTrue(phone.request('apply', run_id=run)['ok'])
            self.assertEqual(self.app.offset_ms, -20)
            self.assertEqual(self.app.offset_source, 'phone')
            self.assertEqual(self.app.offset_file.name, 'calibration-audio-clock.json')
        finally: phone.close()
