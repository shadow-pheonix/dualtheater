import http.client
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from host.diagnostics import SessionDiagnostics, save_report
from host.desktop_support import runtime_args
from host.server import HostRuntime
import test_core


class DiagnosticReportTests(unittest.TestCase):
    def setUp(self):
        self.metrics = SessionDiagnostics()
        self.values = dict(state='playing', connected=True, status={'epoch': 4},
                           status_age_ms=100, epoch=4, audio={}, video_lead_ms=10)

    def report(self, **values):
        return self.metrics.report(**(self.values | values))

    def test_drift_window_is_bounded_and_keeps_lifetime_counts(self):
        for _ in range(100):
            self.metrics.timing(900, 5, 2)
        for value in range(600):
            self.metrics.timing(value, 4, 1)
        result = self.report()['timing']
        self.assertEqual(result['accepted_samples'], 700)
        self.assertEqual(result['window_samples'], 600)
        self.assertEqual(result['median_drift_ms'], 300)
        self.assertEqual(result['p95_absolute_drift_ms'], 569)
        self.assertEqual(result['max_absolute_drift_ms'], 599)
        self.assertEqual(result['max_clock_rtt_ms'], 4)
        self.assertIsNotNone(result['last_sample_age_ms'])

    def test_no_measurements_and_invalid_numbers_remain_unknown(self):
        for value in (float('nan'), float('inf'), 'private-value', True, 10**1000):
            self.metrics.timing(value, 1, 1)
        result = self.report()
        self.assertEqual(result['timing']['accepted_samples'], 0)
        self.assertIsNone(result['timing']['p95_absolute_drift_ms'])
        self.assertIsNone(result['telemetry']['buffer_ahead_ms'])
        json.dumps(result, allow_nan=False)

    def test_allowlist_does_not_export_private_or_attacker_controlled_strings(self):
        secret = 'PRIVATE_SENTINEL_movie_address_endpoint_token'
        status = {'epoch': 4, 'file': secret, 'error': secret, 'decoder': secret,
                  'token': secret, 'url': secret, 'logs': [secret], 'decoders': [secret],
                  'position_ms': 1000, 'buffered_ms': 6500, 'dropped_video_frames': 2,
                  'transfer_mbps': secret, 'heap_limit_mb': float('nan'),
                  'buffer_budget_mb': True, 'frame': {'mime': secret, 'width': 3840, 'height': 2160,
                                                    'codecs': secret, 'color': secret}}
        result = self.report(state=secret, status=status,
                             audio={'valid': True, 'ao': secret, 'format': secret, 'params': {'device': secret}})
        payload = json.dumps(result, allow_nan=False)
        self.assertNotIn(secret, payload)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['telemetry']['buffer_ahead_ms'], 5500)
        self.assertEqual(result['telemetry']['dropped_video_frames'], 2)
        self.assertIsNone(result['telemetry']['transfer_mbps'])
        self.assertIsNone(result['telemetry']['heap_limit_mb'])
        self.assertIsNone(result['telemetry']['buffer_budget_mb'])
        self.assertEqual(result['telemetry']['video_width'], 3840)
        self.assertEqual(result['audio']['output'], 'unknown')

    def test_stale_disconnected_and_wrong_epoch_telemetry_is_not_current(self):
        status = {'epoch': 4, 'position_ms': 1000, 'buffered_ms': 8000, 'transfer_mbps': 90}
        for values, label in (({'status_age_ms': 2100}, 'stale'),
                              ({'connected': False}, 'disconnected'),
                              ({'epoch': 5}, 'stale'),
                              ({'status_age_ms': None}, 'waiting')):
            result = self.report(status=status, **values)['telemetry']
            self.assertEqual(result['status'], label)
            self.assertIsNone(result['buffer_ahead_ms'])
            self.assertIsNone(result['transfer_mbps'])

    def test_operation_failures_and_recovery_reasons_are_fixed_counters(self):
        self.metrics.operation('load', 1234)
        self.metrics.operation('load', 2000, failed=True)
        self.metrics.operation('private-path', 3)
        self.metrics.recovery('buffering')
        self.metrics.recovery('drift')
        self.metrics.error()
        self.metrics.disconnected()
        result = self.report()
        self.assertEqual(result['operations']['load'],
                         {'count': 2, 'failures': 1, 'last_ms': 2000, 'max_ms': 2000})
        self.assertNotIn('private-path', json.dumps(result))
        self.assertEqual(result['recoveries'], {'buffering': 1, 'drift': 1})
        self.assertEqual((result['errors'], result['disconnects']), (1, 1))

    def test_failed_export_preserves_previous_report_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            path.write_text('previous report')
            with patch('host.diagnostics.os.replace', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):
                    save_report(path, self.report())
            self.assertEqual(path.read_text(), 'previous report')
            self.assertEqual(list(Path(directory).iterdir()), [path])
            save_report(path, self.report())
            self.assertEqual(json.loads(path.read_text())['schema_version'], 1)


class DiagnosticProtocolTests(unittest.TestCase):
    def test_fast_reconnect_cannot_leave_old_audio_running_with_a_new_tv_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True),
                                  mpv_factory=test_core.FakeMpv)
            tv = None
            def wait(predicate):
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(.025)
                self.fail('Reconnect condition timed out')
            try:
                runtime.start()
                app = runtime.app
                tv = test_core.SimulatedTV(runtime.args.control_port, app.pair_token)
                wait(lambda: app.peer and bool(app.peer.status))
                movie = Path(directory) / 'fixture.mkv'
                movie.write_bytes(b'FakeMpv reconnect fixture')
                app.action({'action': 'load', 'path': str(movie)})
                app.action({'action': 'play'})
                old_peer = app.peer
                # Reconnect entirely between monitor iterations: the new socket
                # is healthy but its epoch no longer describes the old playback.
                with app.op_lock:
                    tv.close()
                    wait(lambda: old_peer.closed)
                    tv = test_core.SimulatedTV(runtime.args.control_port, app.pair_token)
                    wait(lambda: app.peer is not old_peer and bool(app.peer.status))
                wait(lambda: app.state == 'error')
                self.assertTrue(app.mpv.paused)
                self.assertIn('generation changed', app.error)
            finally:
                if tv:
                    tv.close()
                runtime.close()

    def test_report_endpoint_is_local_authenticated_and_does_not_query_mpv(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True))
            try:
                runtime.start()
                app = runtime.app
                def get(port, headers=None):
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                    try:
                        conn.request('GET', '/api/diagnostics', headers=headers or {})
                        response = conn.getresponse()
                        return response.status, response.read()
                    finally:
                        conn.close()
                headers = {'X-Control-Token': app.ui_token}
                self.assertEqual(get(runtime.args.ui_port)[0], 404)
                self.assertEqual(get(runtime.args.ui_port, headers | {'Origin': 'http://untrusted.example'})[0], 403)
                self.assertEqual(get(runtime.args.media_port, headers)[0], 404)
                app.mpv = unittest.mock.Mock()
                app.mpv.get.side_effect = AssertionError('Export must not perform IPC')
                status, payload = get(runtime.args.ui_port, headers)
                self.assertEqual(status, 200)
                report = json.loads(payload)
                self.assertEqual(report['telemetry']['status'], 'disconnected')
                self.assertNotIn(app.pair_token, payload.decode())
                self.assertNotIn(app.ui_token, payload.decode())
                self.assertNotIn(app.pairings.host_id, payload.decode())
            finally:
                runtime.close()

    def test_real_coordinator_collects_timing_actions_failures_and_disconnects(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True),
                                  mpv_factory=test_core.FakeMpv)
            tv = None
            def wait(predicate):
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    time.sleep(.025)
                self.fail('Coordinator diagnostic condition timed out')
            try:
                runtime.start()
                app = runtime.app
                tv = test_core.SimulatedTV(runtime.args.control_port, app.pair_token)
                wait(lambda: app.peer and bool(app.peer.status))
                movie = Path(directory) / 'PRIVATE_FILM_NAME.mkv'
                movie.write_bytes(b'FakeMpv transport fixture')
                app.action({'action': 'load', 'path': str(movie)})
                app.action({'action': 'play'})
                wait(lambda: app.diagnostic_report()['timing']['accepted_samples'] > 0)
                report = app.diagnostic_report()
                self.assertEqual(report['operations']['load']['count'], 1)
                self.assertEqual(report['operations']['play']['failures'], 0)
                self.assertNotIn(movie.name, json.dumps(report))
                self.assertNotIn(directory, json.dumps(report))
                self.assertEqual(report['telemetry']['status'], 'fresh')
                app.action({'action': 'pause'})
                with self.assertRaises(ValueError):
                    app.action({'action': 'seek', 'seconds': -1})
                report = app.diagnostic_report()
                self.assertEqual(report['operations']['seek']['failures'], 1)
                self.assertEqual(report['errors'], 1)
                tv.close()
                wait(lambda: app.diagnostic_report()['disconnects'] == 1)
                self.assertEqual(app.diagnostic_report()['telemetry']['status'], 'disconnected')
            finally:
                if tv:
                    tv.close()
                runtime.close()
