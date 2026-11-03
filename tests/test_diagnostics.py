import http.client
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from host.diagnostics import SessionDiagnostics, save_report, receiver_report
from host.desktop_support import runtime_args
from host.server import HostRuntime
import test_core


class DiagnosticReportTests(unittest.TestCase):
    def test_native_buffer_observations_are_allowlisted_and_stale_values_are_not_current(self):
        values = dict(epoch=4, native_loading=True, allocated_buffer_bytes=48 * 1024 * 1024,
                      total_buffered_ms=514, java_heap_used_mb=72)
        report = self.report(status=values)['telemetry']
        self.assertTrue(report['native_loading'])
        self.assertEqual(report['allocated_buffer_bytes'], 48 * 1024 * 1024)
        self.assertEqual(report['total_buffered_ms'], 514)
        stale = self.report(status=values, status_age_ms=3000)['telemetry']
        self.assertIsNone(stale['allocated_buffer_bytes'])
        self.assertIsNone(stale['native_loading'])
        values.update(native_loading='PRIVATE_NATIVE_SENTINEL', allocated_buffer_bytes=float('nan'))
        report = self.report(status=values)['telemetry']
        self.assertIsNone(report['native_loading'])
        self.assertIsNone(report['allocated_buffer_bytes'])
        self.assertNotIn('PRIVATE_NATIVE_SENTINEL', json.dumps(report))

    def test_fault_observations_survive_pause_reset_without_copying_raw_status(self):
        from types import SimpleNamespace
        from host.server import ns
        from host.timing import ClockEstimate
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused', 'wasapi/test', directory, ephemeral=True))
            app = runtime.app
            now = ns()
            app.state = 'playing'
            app.peer = SimpleNamespace(closed=False, status_seen=now,
                clock=SimpleNamespace(best=lambda _: ClockEstimate(0, 1_000_000, now)),
                status={'epoch': app.epoch, 'private': 'PRIVATE_FAULT_SENTINEL',
                        'remote_clock': {'state': 'audio_phase_jump', 'phase_error_ms': 172}})
            def reset(reason):
                app.state = reason
                app.peer.status = {'epoch': app.epoch, 'remote_clock': {'state': 'paused'}}
            try:
                with patch.object(app, 'pause_both', side_effect=reset):
                    app.fail('PRIVATE_FAULT_SENTINEL')
                report = app.diagnostic_report()
                self.assertEqual(report['sync']['remote_clock_state'], 'paused')
                self.assertEqual(report['last_failure']['sync']['remote_clock_state'], 'audio_phase_jump')
                self.assertEqual(report['last_failure']['sync']['remote_clock_phase_ms'], 172)
                self.assertNotIn('PRIVATE_FAULT_SENTINEL', json.dumps(report))
                self.assertNotIn('last_failure', report['last_failure'])
            finally:
                app.peer = None
                runtime.close()

    def test_source_sampler_diagnostics_are_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused', 'wasapi/test', directory, ephemeral=True))
            try:
                runtime.app.source_timing = {'state': 'fit_uncertain', 'input_uncertainty_ms': .3,
                    'fit_uncertainty_ms': 11.8, 'consecutive_rejections': 4,
                    'private_path': 'PRIVATE_SOURCE_SENTINEL'}
                result = runtime.app.diagnostic_report()['sync']['source_sampler']
                self.assertEqual(result['state'], 'fit_uncertain')
                self.assertEqual(result['fit_uncertainty_ms'], 11.8)
                self.assertNotIn('PRIVATE_SOURCE_SENTINEL', json.dumps(result))
                runtime.app.source_timing.update(state='PRIVATE_SOURCE_SENTINEL',
                    input_uncertainty_ms=float('nan'), fit_uncertainty_ms='11.8')
                result = runtime.app.diagnostic_report()['sync']['source_sampler']
                self.assertEqual(result['state'], 'unknown')
                self.assertIsNone(result['input_uncertainty_ms'])
                self.assertIsNone(result['fit_uncertainty_ms'])
                runtime.app.anchor_delivery = {'state': 'stale', 'last_send_duration_ms': 850,
                    'private_path': 'PRIVATE_DELIVERY_SENTINEL'}
                result = runtime.app.diagnostic_report()['sync']['anchor_delivery']
                self.assertEqual(result['state'], 'stale')
                self.assertEqual(result['last_send_duration_ms'], 850)
                self.assertNotIn('PRIVATE_DELIVERY_SENTINEL', json.dumps(result))
                runtime.app.anchor_delivery.update(state='PRIVATE_DELIVERY_SENTINEL',
                    last_send_duration_ms=float('nan'))
                result = runtime.app.diagnostic_report()['sync']['anchor_delivery']
                self.assertEqual(result['state'], 'unknown')
                self.assertIsNone(result['last_send_duration_ms'])
            finally:
                runtime.close()

    def test_extended_timing_export_rejects_stale_or_malformed_feedback(self):
        from types import SimpleNamespace
        from host.server import ns
        from host.timing import ClockEstimate
        with tempfile.TemporaryDirectory() as directory:
            runtime = HostRuntime(runtime_args('unused', 'wasapi/test', directory, ephemeral=True))
            app = runtime.app
            now, offset = ns(), 8_000_000_000
            clock = SimpleNamespace(best=lambda _: ClockEstimate(offset, 1_000_000, now))
            app.peer = SimpleNamespace(closed=False, status_seen=now, clock=clock,
                status={'epoch': app.epoch, 'remote_clock': {'state': 'locked', 'phase_error_ms': 2},
                        'rendered_frame': {'epoch': app.epoch, 'release_ns': now + offset - 10_000_000,
                                           'rendered_ns': now + offset}})
            self.assertTrue(app.diagnostic_report()['sync']['rendered_callback_present'])
            app.peer.status['read_ahead'] = {'state': 'running', 'ahead_bytes': 128000,
                'cache_bytes': 256000, 'private_uri': 'PRIVATE_CACHE_SENTINEL',
                'downloaded_bytes': float('nan'), 'failures': '2',
                'foreground_wait_ms': 125.5, 'max_foreground_wait_ms': 'PRIVATE_CACHE_SENTINEL'}
            cache_report = app.diagnostic_report()['telemetry']['read_ahead']
            self.assertEqual(cache_report['state'], 'running')
            self.assertEqual(cache_report['ahead_bytes'], 128000)
            self.assertIsNone(cache_report['downloaded_bytes'])
            self.assertIsNone(cache_report['failures'])
            self.assertEqual(cache_report['foreground_wait_ms'], 125.5)
            self.assertIsNone(cache_report['max_foreground_wait_ms'])
            self.assertNotIn('PRIVATE_CACHE_SENTINEL', json.dumps(cache_report))
            app.peer.status_seen -= 3_000_000_000
            report = app.diagnostic_report()['sync']
            self.assertFalse(report['rendered_callback_present'])
            self.assertEqual(report['remote_clock_state'], 'unknown')
            self.assertEqual(app.diagnostic_report()['telemetry']['read_ahead']['state'], 'unknown')
            app.peer.status_seen = ns()
            app.peer.status.update(remote_clock='malformed', rendered_frame=['malformed'])
            json.dumps(app.diagnostic_report(), allow_nan=False)
            app.peer = None
            runtime.close()

    def test_receiver_export_never_copies_raw_identifiers_or_unknown_latency(self):
        secret = 'PRIVATE_RECEIVER_SENTINEL'
        report = receiver_report({'inspect_s95tr': {'model': secret, 'address': secret,
            'added_av_delay_ms': 50, 'total_processing_delay_ms': 0, 'serial': secret},
            'inspect_hdmi': [{'audio_latency_ms': None, 'edid': secret, 'instance': secret}]})
        self.assertNotIn(secret, json.dumps(report))
        self.assertIsNone(report['lg_s95tr']['total_processing_delay_ms'])
        self.assertIsNone(report['hdmi_declarations'][0]['audio_latency_ms'])

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
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True, sync_mode='baseline'),
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
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True, sync_mode='baseline'))
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
            runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', directory, ephemeral=True, sync_mode='baseline'),
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
