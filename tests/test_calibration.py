import hashlib
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from host.calibration import CUE_TIMES_MS, FIXTURE_SHA256, summarize
from host.desktop_support import runtime_args
from host.server import HostRuntime, ROOT
import test_core


class SummaryTests(unittest.TestCase):
    def test_late_sound_decreases_video_lead_and_early_sound_increases_it(self):
        for gap in (45, -45):
            result = summarize([{'gap_ms': gap, 'uncertainty_ms': 15}] * 6, 100)
            self.assertEqual(result['proposed_video_lead_ms'], 100 - gap)
            self.assertEqual(result['absolute_accuracy'], 'unvalidated')

    def test_incomplete_nonfinite_noisy_or_out_of_range_capture_is_rejected(self):
        valid = [{'gap_ms': 0, 'uncertainty_ms': 15}] * 6
        for rows in (valid[:5], valid + valid[:1],
                     [{'gap_ms': float('nan'), 'uncertainty_ms': 1}] * 6,
                     [{'gap_ms': '45', 'uncertainty_ms': 1}] * 6,
                     [{'gap_ms': 0, 'uncertainty_ms': 41}] * 6,
                     valid[:5] + [{'gap_ms': 100, 'uncertainty_ms': 15}]):
            with self.assertRaises(ValueError): summarize(rows, 0)
        with self.assertRaises(ValueError):
            summarize([{'gap_ms': -500, 'uncertainty_ms': 15}] * 6, 1800)

    def test_original_fixture_and_irregular_cadence_are_pinned(self):
        self.assertEqual(hashlib.sha256((ROOT/'calibration-phone-SDR-TrueHD.mkv').read_bytes()).hexdigest(), FIXTURE_SHA256)
        intervals = [round(b - a, 2) for a, b in zip(CUE_TIMES_MS, CUE_TIMES_MS[1:])]
        self.assertGreater(len(set(intervals)), 3)


class Phone:
    def __init__(self, runtime, token=None):
        self.socket = socket.create_connection(('127.0.0.1', runtime.args.control_port), timeout=5)
        self.reader = self.socket.makefile('rb')
        self.counter = 0
        self.socket.sendall((json.dumps({'op': 'hello', 'version': 1, 'role': 'calibration',
            'client_id': str(uuid.uuid4()), 'device': 'Test phone',
            'token': token or runtime.app.pair_code}) + '\n').encode())
        self.welcome = json.loads(self.reader.readline())
    def request(self, action, **values):
        self.counter += 1
        self.socket.sendall((json.dumps(dict(op='calibration', id=self.counter, action=action, **values)) + '\n').encode())
        return json.loads(self.reader.readline())
    def close(self):
        try: self.socket.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.reader.close(); self.socket.close()


class CalibrationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', self.directory.name, ephemeral=True, sync_mode='baseline'),
                                   mpv_factory=test_core.FakeMpv)
        self.runtime.start()
        self.app = self.runtime.app
        self.tv = test_core.SimulatedTV(self.runtime.args.control_port, self.app.pair_token)
        self.wait(lambda: self.app.peer and bool(self.app.peer.status))
        self.phone = Phone(self.runtime)
    def tearDown(self):
        self.phone.close(); self.tv.close(); self.runtime.close(); self.directory.cleanup()
    def wait(self, predicate, seconds=8):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(.025)
        self.fail('Calibration timed out: ' + str(self.app.calibration.snapshot()))
    def start(self):
        response = self.phone.request('start')
        self.assertTrue(response['ok'], response)
        self.wait(lambda: self.app.calibration.snapshot()['state'] == 'playing')
        return self.app.calibration.snapshot()['run_id']
    def measured(self):
        run_id = self.start()
        result = self.phone.request('complete', run_id=run_id,
            pairs=[{'gap_ms': 45, 'uncertainty_ms': 15}] * 6)
        self.assertTrue(result['ok'], result)
        self.wait(lambda: self.app.calibration.snapshot()['state'] == 'measured')
        return run_id

    def test_phone_authenticates_alongside_tv_without_replacing_its_socket(self):
        self.assertEqual(self.phone.welcome['role'], 'calibration')
        self.assertEqual(self.phone.welcome['calibration_protocol'], 1)
        self.assertGreater(len(self.phone.welcome['trusted_token']), 40)
        peer = self.app.peer
        self.assertTrue(self.phone.request('status')['ok'])
        self.assertIs(self.app.peer, peer)
        self.assertFalse(peer.closed)
        denied = Phone(self.runtime, token='wrong')
        try: self.assertEqual(denied.welcome['op'], 'auth_required')
        finally: denied.close()

    def test_measure_then_explicit_apply_uses_existing_coordinator_and_saved_offset(self):
        run_id = self.measured()
        self.assertTrue(self.app.mpv.paused)
        self.assertEqual(self.app.offset_ms, 0)
        result = self.phone.request('apply', run_id=run_id)
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.app.offset_ms, -45)
        self.assertEqual(json.loads(self.app.offset_file.read_text())['video_lead_ms'], -45)
        self.assertFalse(self.phone.request('apply', run_id=run_id)['ok'])
        self.assertFalse(any(c[:2] == ('set_property', 'speed') for c in self.app.mpv.commands))

    def test_stale_run_or_changed_playback_cannot_apply(self):
        run_id = self.measured()
        self.assertFalse(self.phone.request('apply', run_id='old-run')['ok'])
        self.app.action({'action': 'seek', 'seconds': 4})
        self.assertFalse(self.phone.request('apply', run_id=run_id)['ok'])
        self.assertEqual(self.app.offset_ms, 0)

    def test_disconnect_cancels_test_and_pauses_audio_without_disconnecting_tv(self):
        self.start()
        tv_peer = self.app.peer
        self.phone.close()
        self.wait(lambda: not self.app.calibration.snapshot()['phone_connected'])
        self.wait(lambda: self.app.mpv.paused)
        self.assertIs(self.app.peer, tv_peer)
        self.assertFalse(tv_peer.closed)

    def test_cancel_while_waiting_for_operation_lock_does_not_cancel_other_work(self):
        with self.app.op_lock:
            self.assertTrue(self.phone.request('start')['ok'])
            self.assertTrue(self.phone.request('cancel')['ok'])
            self.assertFalse(self.app.cancel.is_set())
        self.wait(lambda: not self.app.calibration.run.worker.is_alive())
        self.assertEqual(self.app.calibration.snapshot()['state'], 'cancelled')

    def test_no_tv_no_arbitrary_media_paths_or_unsupported_operations(self):
        self.assertFalse(self.phone.request('load', path='arbitrary.mkv')['ok'])
        self.tv.close(); self.wait(lambda: self.app.peer.closed)
        self.assertFalse(self.phone.request('start')['ok'])

    def test_failed_offset_save_keeps_previous_value_and_file(self):
        self.app.action({'action': 'offset', 'milliseconds': 90})
        original = self.app.offset_file.read_bytes()
        with patch('host.server.os.replace', side_effect=OSError('Storage unavailable')):
            with self.assertRaises(OSError):
                self.app.action({'action': 'offset', 'milliseconds': 45})
        self.assertEqual(self.app.offset_ms, 90)
        self.assertEqual(self.app.offset_file.read_bytes(), original)
        self.assertFalse(self.app.offset_file.with_suffix('.tmp').exists())
