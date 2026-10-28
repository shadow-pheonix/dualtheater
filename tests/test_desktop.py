import http.client
import json
from pathlib import Path
import queue
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from host.desktop_support import (DesktopService, Settings, default_data_dir, find_mpv, format_time,
                                  list_devices, parse_devices, runtime_args)
from host.server import HostRuntime
from test_core import FakeMpv, SimulatedTV


class DesktopSettingsTests(unittest.TestCase):
    def test_preview_settings_do_not_read_or_overwrite_the_base_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)/'DualTheater'
            base.mkdir()
            settings_path = base/'settings.local.json'
            settings_path.write_text('{"mpv":"base-player.exe","device":"wasapi/base"}')
            original = settings_path.read_bytes()
            with patch.dict('os.environ', {'LOCALAPPDATA': directory}):
                preview = default_data_dir()
                self.assertEqual(preview, Path(directory)/'DualTheater-Preview')
                settings = Settings(preview)
                self.assertEqual(settings.values, {})
                player = Path(directory)/'preview.exe'
                player.touch()
                settings.save(str(player), 'wasapi/preview')
            self.assertEqual(settings_path.read_bytes(), original)

    def test_private_state_survives_restart_and_ignores_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            player = Path(directory)/'mpv.exe'
            player.touch()
            settings = Settings(Path(directory)/'profile')
            settings.save(str(player), 'wasapi/test-output')
            restored = Settings(settings.directory)
            self.assertEqual(restored.values, settings.values)
            self.assertEqual(find_mpv(restored.values['mpv']), str(player.resolve()))
            self.assertFalse((Path(directory)/'pairings.json').exists())

    def test_corrupt_settings_preserved_before_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.local.json'
            path.write_text('broken', encoding='utf-8')
            settings = Settings(directory)
            self.assertTrue(settings.warning)
            player = Path(directory)/'mpv.exe'
            player.touch()
            settings.save(str(player), 'wasapi/test')
            self.assertEqual((Path(directory)/'settings.local.unreadable.json').read_text(), 'broken')
            self.assertEqual(Settings(directory).values['device'], 'wasapi/test')

    def test_rejects_implicit_default_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            player=Path(directory)/'mpv.exe'
            player.touch()
            with self.assertRaises(ValueError):
                Settings(directory).save(str(player), 'auto')

    def test_devices_use_friendly_labels_and_exact_wasapi_identifiers(self):
        devices=parse_devices(" 'auto' (Default)\n 'wasapi/a' (HDMI Audio)\n 'wasapi/b' (HDMI Audio)\n 'alsa/default' (Other)\n 'wasapi/c' (USB Audio)\n")
        self.assertEqual([d['id'] for d in devices], ['wasapi/a','wasapi/b','wasapi/c'])
        self.assertEqual([d['label'] for d in devices], ['HDMI Audio (1)','HDMI Audio (2)','USB Audio'])
        self.assertEqual(format_time(3661000),'1:01:01')
        self.assertEqual(format_time(-1000),'0:00')

    def test_device_scan_failure_and_missing_executable_are_clear(self):
        with self.assertRaisesRegex(ValueError,'Select mpv'):
            list_devices('missing-mpv.exe')
        with tempfile.NamedTemporaryFile(suffix='.exe') as file:
            with patch('host.desktop_support.subprocess.run') as run:
                run.return_value.returncode=1
                with self.assertRaisesRegex(RuntimeError,'could not list'):
                    list_devices(file.name)


class RuntimeLifecycleTests(unittest.TestCase):
    def test_partial_bind_failure_closes_files_and_all_bound_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=HostRuntime(runtime_args('unused.exe','wasapi/test',directory,ephemeral=True))
            with patch('host.server.ThreadServer', side_effect=OSError('Port already used')):
                with self.assertRaisesRegex(OSError,'Port already used'):
                    runtime.start()
            self.assertTrue(runtime.app.csv_file.closed)
            self.assertTrue(runtime.closed)
            for service in runtime.servers:
                with socket.socket() as sock:
                    sock.bind(service.server_address)
            runtime.close()  # idempotent even after a partial startup failure

    def test_full_start_stop_releases_ports_and_preserves_pairings(self):
        with tempfile.TemporaryDirectory() as directory:
            args=runtime_args('unused.exe','wasapi/test',directory,ephemeral=True)
            runtime=HostRuntime(args)
            try:
                runtime.start()
                conn=http.client.HTTPConnection('127.0.0.1',args.ui_port,timeout=3)
                conn.request('GET','/')
                response=conn.getresponse()
                self.assertEqual(response.status,200)
                self.assertIn(b'DualTheater',response.read())
                conn.close()
                identity=json.loads((Path(directory)/'pairings.json').read_text())['host_id']
            finally:
                runtime.close()
            self.assertEqual(json.loads((Path(directory)/'pairings.json').read_text())['host_id'],identity)
            for service in runtime.servers:
                with socket.socket() as sock:
                    sock.bind(service.server_address)


class DesktopTransportTests(unittest.TestCase):
    def wait_event(self, service, kind, timeout=15):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                name,value=service.events.get(timeout=.2)
            except queue.Empty:
                continue
            if name=='error':
                raise AssertionError(value)
            if name==kind:
                return value
        self.fail('Desktop event timed out: '+kind)

    def test_desktop_operations_use_shared_tv_audio_transport_and_clean_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            def factory(args):
                args.ui_port=args.media_port=args.control_port=args.discovery_port=0
                return HostRuntime(args,mpv_factory=FakeMpv)
            service=DesktopService(directory,runtime_factory=factory)
            tv=None
            try:
                service.submit('start',mpv='unused.exe',device='wasapi/test')
                self.wait_event(service,'started')
                app=service.runtime.app
                tv=SimulatedTV(service.runtime.args.control_port,app.pair_token)
                deadline=time.monotonic()+5
                while (not app.peer or len(app.peer.clock.samples)<3) and time.monotonic()<deadline:
                    time.sleep(.05)
                movie=Path(directory)/'sample.mkv'
                movie.write_bytes(b'fake media: transport uses FakeMpv')
                for values in ({'action':'load','path':str(movie)}, {'action':'play'},
                               {'action':'pause'}, {'action':'seek','seconds':40}):
                    service.submit('action',**values)
                    self.assertEqual(self.wait_event(service,'action_done'),values['action'])
                self.assertEqual(app.state,'paused')
                self.assertAlmostEqual(app.anchor_ms,40000,delta=150)
                self.assertTrue(app.mpv.paused)
                self.assertFalse(tv.playing)
                service.submit('action',action='offset',milliseconds=90)
                self.wait_event(service,'action_done')
                self.assertEqual(json.loads((Path(directory)/'calibration.json').read_text())['video_lead_ms'],90)
                report_path = Path(directory)/'report.json'
                service.submit('export_diagnostics', path=str(report_path))
                self.wait_event(service, 'diagnostics_exported')
                report = json.loads(report_path.read_text())
                self.assertEqual(report['operations']['load']['count'], 1)
                self.assertNotIn(movie.name, report_path.read_text())
                self.assertNotIn(app.pair_code, report_path.read_text())
                service.submit('stop')
                self.wait_event(service,'stopped')
                self.assertIsNone(service.runtime)
                self.assertTrue(app.csv_file.closed)
            finally:
                if tv:
                    tv.close()
                service.submit('close')
                self.assertTrue(service.closed.wait(10))


if __name__=='__main__':
    unittest.main()
