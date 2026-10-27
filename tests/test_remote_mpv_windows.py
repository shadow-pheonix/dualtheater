"""Real compressed-audio clock + simulated TV remote/barrier integration.

The output driver is null. This never opens the user's HDMI endpoint.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from host import server
from host.mpv import Mpv
from test_core import SimulatedTV


class NullTrueHd(Mpv):
    def __init__(self, executable, device, log_dir, diagnostic=False):
        super().__init__(executable, None, log_dir, diagnostic=False)

    def launch(self):
        original = subprocess.Popen
        def null(args, **kwargs):
            return original(['--ao=null' if arg == '--ao=wasapi' else arg for arg in args], **kwargs)
        with patch('host.mpv.subprocess.Popen', side_effect=null):
            super().launch()

    def verify(self):
        params = self.get('audio-out-params', {}) or {}
        if self.get('current-ao') != 'null' or params.get('format') != 'spdif-truehd':
            raise RuntimeError('Test must remain on TrueHD null output')
        if self.get('speed') != 1:
            raise RuntimeError('Audio speed changed')
        return {'valid': True, 'ao': 'null', 'format': 'spdif-truehd', 'test_only': True}


@unittest.skipUnless(os.name == 'nt' and os.environ.get('DUALTHEATER_MPV'), 'Set DUALTHEATER_MPV for real audio-clock integration')
class RealRemoteTests(unittest.TestCase):
    def test_real_truehd_remote_seek_pause_and_resume(self):
        clip = Path(__file__).resolve().parents[1] / 'calibration-SDR-TrueHD-no-Atmos.mkv'
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(server, 'ROOT', Path(temp)):
                args = argparse.Namespace(host='127.0.0.1', media_port=8765,
                    mpv=os.environ['DUALTHEATER_MPV'], device='unused-test-endpoint', diagnostic=False)
                app = server.Coordinator(args, mpv_factory=NullTrueHd)
            control = server.ThreadServer(('127.0.0.1', 0), server.ControlHandler)
            control.app = app
            for target in (control.serve_forever, app.heartbeat, app.monitor, app.remote_worker):
                threading.Thread(target=target, daemon=True).start()
            tv = SimulatedTV(control.server_address[1], app.pair_token)
            def wait(predicate, seconds=10):
                until = time.monotonic() + seconds
                while time.monotonic() < until:
                    if predicate(): return
                    time.sleep(.02)
                self.fail('Timed out: ' + app.state + ' ' + app.error)
            def remote(action, seconds=None):
                request = tv.remote(action, seconds)
                wait(lambda: request in tv.remote_results)
                self.assertTrue(tv.remote_results[request]['ok'], tv.remote_results[request])
            try:
                wait(lambda: app.peer and bool(app.peer.status))
                app.action({'action': 'load', 'path': str(clip)})
                remote('toggle')
                wait(lambda: app.drift_ms is not None)
                self.assertLess(abs(app.drift_ms), 80)
                remote('seek', 5)
                wait(lambda: app.drift_ms is not None)
                self.assertLess(abs(app.drift_ms), 80)
                self.assertEqual(app.state, 'playing')
                self.assertGreater(app.mpv.audio_sample()['position_ms'], 4900)
                remote('toggle')
                self.assertTrue(app.mpv.get('pause'))
                remote('seek', 2)
                self.assertEqual(app.state, 'paused')
                self.assertEqual(app.anchor_ms, 2000)
                remote('toggle')
                wait(lambda: app.drift_ms is not None)
                self.assertLess(abs(app.drift_ms), 80)
                self.assertEqual(app.mpv.get('speed'), 1)
            finally:
                tv.close(); app.close(); control.shutdown(); control.server_close()


if __name__ == '__main__': unittest.main()
