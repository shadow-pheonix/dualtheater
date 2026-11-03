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
from host.timing import TimingUnavailable
from unittest.mock import patch
import test_core


class TimedMpv(test_core.FakeMpv):
    cache_paused = False
    def get(self, name, default=None):
        if name == 'paused-for-cache': return self.cache_paused
        return super().get(name, default)

    def seek(self, seconds):
        self.cache_paused = False
        return super().seek(seconds)

    def timed_audio_sample(self):
        return self.audio_sample() | {'source': 'mpv_source_clock'}


class TimingTV:
    def __init__(self, port, token, progress=True, datagrams=False):
        self.port, self.progress = port, progress
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.reader = self.sock.makefile('rb')
        self.lock = threading.Lock()
        self.closed = False; self.timing = None; self.speed_commands = 0
        self.reply_delay = 0
        self.reply_started = threading.Event()
        self.reply_finished = threading.Event()
        self.offset = 8_000_000_000; self.epoch = 0; self.position = 0
        self.started = ns(); self.playing = False; self.state = 'idle'; self.armed = None
        self.anchor = None; self.frame_sequence = 0; self.mode = ''; self.speed = 1
        self.reported_error = ''; self.timing_error_only = False
        self.status_enabled = True; self.freeze_frames = False
        self.send({'op': 'hello', 'version': 1, 'token': token, 'timing_protocol': 2,
                   'timing_datagrams': datagrams})
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
                    reply = (json.dumps({'op': 'pong', 't0': m['t0'], 't1': now, 't2': now}) + '\n').encode()
                    delay, self.reply_delay = self.reply_delay, 0
                    if delay:
                        # Exercise a partial line across the former 500ms read
                        # deadline, not just a delayed complete packet.
                        self.timing.sendall(reply[:8])
                        self.reply_started.set()
                        time.sleep(delay)
                        self.timing.sendall(reply[8:])
                        self.reply_finished.set()
                    else:
                        self.timing.sendall(reply)
                elif m['op'] == 'anchor' and m['epoch'] == self.epoch:
                    self.anchor = m
        except (OSError, ValueError): pass

    def read(self):
        try:
            for raw in self.reader:
                m = json.loads(raw); op = m['op']
                if op == 'welcome':
                    self.mode = m['sync_mode']
                    self.timing_token = m['timing_token']
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
                if not self.freeze_frames: self.frame_sequence += 1
                if not self.status_enabled:
                    time.sleep(.025)
                    continue
                self.send({'op': 'status', 'epoch': self.epoch, 'state': self.state,
                    'position_ms': self.current(), 'sample_ns': now + self.offset,
                    'error': self.reported_error, 'timing_error_only': self.timing_error_only,
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


class DatagramTV(TimingTV):
    def __init__(self, port, token):
        self.reply_enabled = True
        self.last_pong = None
        super().__init__(port, token, datagrams=True)

    def timing_read(self, token):
        try:
            self.timing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.timing.connect(('127.0.0.1', self.port))
            self.timing.settimeout(.2)
            ready = False
            while not self.closed:
                if not ready:
                    self.timing.send(json.dumps({'op': 'hello', 'version': 3, 'token': token}).encode())
                try: m = json.loads(self.timing.recv(2049))
                except socket.timeout: continue
                if m.get('token') != token: continue
                if m['op'] == 'timing_ready': ready = True
                elif m['op'] == 'ping' and self.reply_enabled:
                    now = ns() + self.offset
                    self.last_pong = {'op': 'pong', 'token': token, 't0': m['t0'], 't1': now, 't2': now}
                    self.timing.send(json.dumps(self.last_pong).encode())
                elif m['op'] == 'anchor' and m['epoch'] == self.epoch:
                    if not self.anchor or m['sequence'] > self.anchor['sequence']:
                        self.anchor = m
        except (OSError, ValueError): pass


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

    def connect_datagrams(self):
        self.tv = DatagramTV(self.runtime.args.control_port, self.app.pair_token)
        self.wait(lambda: self.app.peer and self.app.peer.clock.best(ns()) is not None)
        self.assertEqual(self.app.peer.timing.transport, 'udp')
        self.assertEqual(self.app.diagnostic_report()['sync']['timing_transport'], 'udp')

    def test_datagram_start_pause_seek_and_transient_packet_loss(self):
        self.connect_datagrams()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        epoch = self.app.epoch
        original = self.app.peer.timing.send
        def selective_loss(message):
            if message.get('op') != 'anchor': return original(message)
            return False
        with patch.object(self.app.peer.timing, 'send', side_effect=selective_loss):
            time.sleep(.05)
            sequence = self.app.delivered_anchor['sequence']
            time.sleep(.35)
            self.assertEqual(self.app.delivered_anchor['sequence'], sequence)
            self.assertGreater(self.app.latest_anchor['sequence'], sequence)
        self.wait(lambda: self.tv.anchor and self.tv.anchor['sequence'] == self.app.delivered_anchor['sequence'])
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertEqual(self.app.epoch, epoch)
        self.app.action({'action': 'pause'})
        self.app.action({'action': 'seek', 'seconds': 90})
        self.assertEqual(self.app.state, 'paused')
        self.app.action({'action': 'play'})
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertEqual(self.tv.speed_commands, 0)
        self.assertFalse(any(c[:2] == ('set_property', 'speed') for c in self.app.mpv.commands))

    def test_datagram_authentication_endpoint_and_replay_are_bounded(self):
        self.connect_datagrams()
        peer, service = self.app.peer, self.runtime.datagram_timing
        link, clock = peer.timing, peer.clock
        self.tv.reply_enabled = False
        time.sleep(.05)
        count = len(clock.samples)
        # A consumed ping cannot be replayed; unknown nonces, wrong session
        # tokens/endpoints and malformed/oversized packets cannot move clocks.
        service.receive(json.dumps(self.tv.last_pong).encode(), link.address, ns())
        for packet, address in (({'op':'hello','version':3,'token':'wrong'},link.address),
                ({'op':'hello','version':3,'token':peer.timing_token},('127.0.0.1',1)),
                ({'op':'pong','token':peer.timing_token,'t0':1,'t1':2,'t2':3},link.address)):
            service.receive(json.dumps(packet).encode(), address, ns())
        for payload in (b'[]', b'broken', b'x'*2049, b'['*1000+b']'*1000):
            service.receive(payload, link.address, ns())
        self.assertIs(peer.timing, link)
        self.assertIs(peer.clock, clock)
        self.assertEqual(len(clock.samples), count)
        for _ in range(30): link.send({'op':'ping'})
        self.assertLessEqual(len(link.pending), 16)

    def test_silent_datagram_peer_stops_playback_without_losing_control(self):
        self.connect_datagrams()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.tv.reply_enabled = False
        self.wait(lambda: self.app.state == 'error', seconds=4)
        self.assertTrue(self.app.mpv.paused)
        self.assertFalse(self.app.peer.closed)

    def test_brief_native_refill_does_not_trigger_a_coordinated_seek(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        epoch = self.app.epoch
        self.tv.state = 'buffering'
        self.wait(lambda: self.app.peer.status.get('state') == 'buffering')
        time.sleep(.05)
        self.tv.state = 'ready'
        self.wait(lambda: self.app.peer.status.get('state') == 'ready')
        time.sleep(.25)
        self.assertEqual(self.app.epoch, epoch)
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertIsNone(self.app.last_recovery)

    def test_persistent_native_refill_still_recovers_and_records_the_correct_source(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        epoch = self.app.epoch
        self.tv.state = 'buffering'
        self.wait(lambda: self.app.last_recovery is not None and self.app.state == 'playing' and self.app.epoch > epoch)
        self.assertEqual(self.app.last_recovery['source'], 'video')
        self.assertEqual(self.app.diagnostics.recoveries['buffering'], 1)

    def test_audio_cache_pause_does_not_get_the_video_only_refill_grace(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        epoch = self.app.epoch
        self.app.mpv.cache_paused = True
        self.wait(lambda: self.app.last_recovery is not None and self.app.state == 'playing' and self.app.epoch > epoch)
        self.assertEqual(self.app.last_recovery['source'], 'audio')
        self.assertFalse(self.app.mpv.cache_paused)

    def test_delayed_status_does_not_masquerade_as_a_frozen_video_frame(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        before = self.app.peer.status_seen
        self.tv.status_enabled = False
        time.sleep(1.3)  # Timing/audio stay fresh; control telemetry is delayed.
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.tv.status_enabled = True
        self.wait(lambda: self.app.peer.status_seen > before + 1_000_000_000)
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertFalse(self.app.mpv.paused)

    def test_fresh_status_with_a_truly_frozen_frame_still_pauses(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        self.tv.freeze_frames = True
        self.wait(lambda: self.app.state == 'error', seconds=2)
        self.assertIn('Unique video frame telemetry stalled', self.app.error)
        self.assertTrue(self.app.mpv.paused)
        self.assertLess(ns() - self.app.peer.status_seen, 500_000_000)

    def test_transient_rejected_clock_fit_does_not_latch_a_playback_error(self):
        from dataclasses import replace
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        clock = self.app.peer.clock
        for missing in (False, True):
            with self.subTest(missing=missing):
                first = self.app.latest_anchor['sequence']
                actual = clock.best
                def unusable(now):
                    model = actual(now)
                    return None if missing else replace(model, uncertainty_ns=12_200_000)
                with patch.object(clock, 'best', side_effect=unusable):
                    time.sleep(.05)
                    delivered = self.app.delivered_anchor['sequence']
                    time.sleep(.2)
                    self.assertEqual(self.app.state, 'playing', self.app.error)
                    self.assertEqual(self.app.timing_error, '')
                    self.assertGreater(self.app.latest_anchor['sequence'], first)
                    self.assertEqual(self.app.delivered_anchor['sequence'], delivered)
                self.wait(lambda: self.app.delivered_anchor['sequence'] > delivered)
                self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertEqual(self.tv.speed_commands, 0)
        self.assertFalse(any(c[:2] == ('set_property', 'speed') for c in self.app.mpv.commands))

    def test_valid_affine_confidence_keeps_playing_despite_high_path_rtt(self):
        from dataclasses import replace
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        clock = self.app.peer.clock; actual = clock.best
        epoch, corrections = self.app.epoch, self.app.diagnostics.sample_count
        # Path delay alone is not affine-clock uncertainty. A valid current
        # interval may be narrower than half of one delayed exchange's RTT.
        with patch.object(clock, 'best', side_effect=lambda now: replace(actual(now),
                rtt_ns=46_000_000, uncertainty_ns=10_900_000)):
            time.sleep(3.4)  # Exceeds the old monitor's independent RTT deadline.
            self.assertEqual(self.app.state, 'playing', self.app.error)
            self.assertEqual(self.app.epoch, epoch)
            self.assertGreater(self.app.diagnostics.sample_count, corrections)
            self.assertLess(ns() - self.app.delivered_anchor['host_ns'], 250_000_000)
        self.assertFalse(self.app.mpv.paused)

    def test_affine_start_uses_phase_confidence_instead_of_baseline_rtt_limit(self):
        from dataclasses import replace
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        clock = self.app.peer.clock; actual = clock.best
        with patch.object(clock, 'best', side_effect=lambda now: replace(actual(now),
                rtt_ns=46_000_000, uncertainty_ns=10_900_000)):
            self.app.action({'action': 'play'})
            self.assertEqual(self.app.state, 'playing')
            self.assertFalse(self.app.mpv.paused)

    def test_baseline_retains_its_round_trip_limit_at_start_and_monitoring(self):
        from dataclasses import replace
        from host.sync import VideoServo
        self.app.sync_mode = 'baseline'
        self.app.servo = VideoServo()
        self.tv = test_core.SimulatedTV(self.runtime.args.control_port, self.app.pair_token)
        self.wait(lambda: self.app.peer and self.app.peer.clock.best(ns()) is not None)
        self.app.action({'action': 'load', 'path': str(self.movie)})
        clock = self.app.peer.clock; actual = clock.best
        with patch.object(clock, 'best', side_effect=lambda now: replace(actual(now), rtt_ns=46_000_000)):
            with self.assertRaisesRegex(RuntimeError, 'round-trip'):
                self.app.action({'action': 'play'})
        self.app.action({'action': 'play'})
        self.wait(lambda: self.app.drift_ms is not None)
        with patch.object(clock, 'best', side_effect=lambda now: replace(actual(now), rtt_ns=46_000_000)):
            self.wait(lambda: self.app.state == 'error', seconds=4)
            self.assertIn('Clock measurements too uncertain', self.app.error)
            self.assertTrue(self.app.mpv.paused)

    def test_sustained_rejected_clock_fit_expires_delivery_without_stopping_source_sampling(self):
        from dataclasses import replace
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        clock = self.app.peer.clock; actual = clock.best
        with patch.object(clock, 'best', side_effect=lambda now: replace(actual(now), uncertainty_ns=12_200_000)):
            started = time.monotonic()
            self.wait(lambda: self.app.state == 'error', seconds=3)
            self.assertLess(time.monotonic() - started, 2.4)
            self.assertIn('delivery expired', self.app.error)
            self.assertLess(self.app.last_failure['sync']['source_sampler']['observation_age_ms'], 250)
        self.assertTrue(self.app.mpv.paused)
        self.assertFalse(self.app.audio_running.is_set())
        self.assertEqual(self.tv.speed_commands, 0)

    def test_blocked_timing_write_cannot_stall_local_audio_observations(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        link = self.app.peer.timing; original = link.send
        entered, release = threading.Event(), threading.Event()
        def blocked(message):
            if message.get('op') == 'anchor' and not entered.is_set():
                entered.set(); release.wait(1.5)
            return original(message)
        link.send = blocked
        try:
            self.assertTrue(entered.wait(1))
            first = self.app.latest_anchor['host_ns']
            time.sleep(.85)
            self.assertEqual(self.app.state, 'playing', self.app.error)
            self.assertGreater(self.app.latest_anchor['host_ns'] - first, 600_000_000)
            self.assertLess(ns() - self.app.latest_anchor['host_ns'], 250_000_000)
            newest = self.app.latest_anchor['sequence']
            release.set()
            self.wait(lambda: self.app.delivered_anchor['sequence'] >= newest)
            self.assertLess(ns() - self.app.delivered_anchor['host_ns'], 250_000_000)
            self.assertEqual(self.app.state, 'playing', self.app.error)
        finally:
            release.set()

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

    def test_reconnected_timing_reacquires_clock_and_calibration_can_start(self):
        import test_calibration
        self.connect()
        self.app.action({'action': 'offset', 'milliseconds': 75})
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        old_clock, old_link = self.app.peer.clock, self.app.peer.timing
        self.tv.close_timing()
        self.wait(lambda: self.app.state == 'error' and old_link.closed)
        threading.Thread(target=self.tv.timing_read, args=(self.tv.timing_token,), daemon=True).start()
        self.wait(lambda: self.app.peer.clock is not old_clock and self.app.peer.clock.best(ns()) is not None)
        self.assertEqual(self.app.state, 'error')
        self.assertTrue(self.app.mpv.paused)  # Reconnection never resumes by itself.
        phone = test_calibration.Phone(self.runtime)
        try:
            self.assertTrue(phone.request('start')['ok'])
            self.wait(lambda: self.app.calibration.snapshot()['state'] == 'playing')
            run = self.app.calibration.snapshot()['run_id']
            self.assertTrue(phone.request('complete', run_id=run,
                pairs=[{'gap_ms': 10, 'uncertainty_ms': 5}] * 6)['ok'])
            self.wait(lambda: self.app.calibration.snapshot()['state'] == 'measured')
            self.assertEqual(self.app.offset_ms, 75)
        finally:
            phone.close()

    def test_missing_timing_fails_before_replacing_loaded_media(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        old_media, old_mpv = self.app.media, self.app.mpv
        self.tv.close_timing()
        self.wait(lambda: self.app.peer.timing.closed)
        other = Path(self.tmp.name) / 'other.mkv'; other.write_bytes(b'another movie')
        ensure = self.app.ensure_timing
        with patch.object(self.app, 'ensure_timing', side_effect=lambda: ensure(seconds=.15)):
            with self.assertRaises(TimingUnavailable):
                self.app.action({'action': 'load', 'path': str(other)})
        self.assertEqual(self.app.media, old_media)
        self.assertIs(self.app.mpv, old_mpv)
        self.assertTrue(old_mpv.paused)

    def test_timing_preflight_does_not_ignore_unrelated_tv_errors(self):
        self.connect()
        self.tv.close_timing()
        self.wait(lambda: self.app.peer.timing.closed)
        self.tv.reported_error = 'decoder failed'
        self.wait(lambda: self.app.peer.status.get('error') == 'decoder failed')
        with self.assertRaisesRegex(RuntimeError, 'decoder failed'):
            self.app.ensure_timing(seconds=.15)
        self.tv.reported_error = 'timing recovery in progress'; self.tv.timing_error_only = True
        self.wait(lambda: self.app.peer.status.get('timing_error_only'))
        with self.assertRaises(TimingUnavailable):
            self.app.ensure_timing(seconds=.15)

    def test_fragmented_delayed_pong_preserves_live_playback_and_calibration(self):
        self.connect()
        self.app.action({'action': 'offset', 'milliseconds': 229})
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        link = self.app.peer.timing
        self.tv.reply_delay = .65
        self.assertTrue(self.tv.reply_finished.wait(3))
        self.wait(lambda: self.app.peer.clock.best(ns()) is not None)
        self.assertIs(self.app.peer.timing, link)
        self.assertFalse(link.closed)
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertEqual(self.app.playback_lead_ms, 229)
        self.assertFalse(any(c[:2] == ('set_property', 'speed') for c in self.app.mpv.commands))

    def test_stale_pong_is_discarded_without_tearing_down_timing(self):
        self.connect()
        link = self.app.peer.timing
        self.tv.reply_delay = 1.1
        self.assertTrue(self.tv.reply_finished.wait(3))
        # A newly accepted exchange proves parsing continued after the old one.
        after = ns()
        self.wait(lambda: any(row[3] > after for row in self.app.peer.clock.samples))
        self.assertFalse(link.closed)
        self.assertFalse(self.app.peer.closed)

    def test_silent_timing_peer_expires_but_control_remains_connected(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        self.tv.reply_delay = 3.5
        self.assertTrue(self.tv.reply_started.wait(1))
        self.wait(lambda: self.app.peer.timing.closed, seconds=4)
        self.wait(lambda: self.app.state == 'error')
        self.assertTrue(self.app.mpv.paused)
        self.assertFalse(self.app.peer.closed)

    def test_timing_write_failure_does_not_close_control_channel(self):
        self.connect()
        self.app.action({'action': 'load', 'path': str(self.movie)})
        self.app.action({'action': 'play'})
        link = self.app.peer.timing
        original_send = link.send
        def fail_ping(message):
            if message.get('op') == 'ping':
                raise TimeoutError('simulated blocked timing writer')
            return original_send(message)
        link.send = fail_ping
        self.wait(lambda: self.app.state == 'error')
        self.assertTrue(link.closed)
        self.assertTrue(self.app.mpv.paused)
        self.assertFalse(self.app.peer.closed)

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
