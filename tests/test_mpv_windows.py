"""Optional real-mpv IPC tests. Null output only: never opens the HDMI device."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from host.mpv import Mpv


@unittest.skipUnless(os.name == 'nt' and os.environ.get('DUALTHEATER_MPV'), 'Set DUALTHEATER_MPV to run real Windows mpv IPC tests')
class RealMpvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wav = Path(self.tmp.name) / 'silent.wav'
        with wave.open(str(self.wav), 'wb') as wav:
            wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(48000)
            wav.writeframes(b'\0' * 48000 * 4 * 5)
        self.original_popen = subprocess.Popen
        self.audio = None
    def tearDown(self):
        if self.audio: self.audio.close()
        self.tmp.cleanup()
    def null_output(self, args, **kwargs):
        args = ['--ao=null' if arg == '--ao=wasapi' else arg for arg in args]
        return self.original_popen(args, **kwargs)
    def wait(self, fn):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = fn()
            if result: return result
            time.sleep(.05)
        self.fail('Real mpv did not become ready')
    def test_named_pipe_play_pause_and_seek_with_null_output(self):
        self.audio = Mpv(os.environ['DUALTHEATER_MPV'], None, Path(self.tmp.name), diagnostic=True)
        with patch('host.mpv.subprocess.Popen', side_effect=self.null_output): self.audio.launch()
        self.audio.command('loadfile', str(self.wav), 'replace')
        self.wait(lambda: self.audio.get('audio-out-params'))
        self.assertEqual(self.audio.get('current-ao'), 'null')
        self.audio.pause(False)
        self.wait(lambda: self.audio.audio_sample()['position_ms'] is not None)
        time.sleep(.15)
        self.audio.pause()
        before = self.audio.get('time-pos'); time.sleep(.1)
        self.assertAlmostEqual(self.audio.get('time-pos'), before, delta=.025)
        self.audio.seek(2)
        self.assertFalse(self.audio.get('seeking'))
        self.audio.pause(False)
        self.wait(lambda: 2000 <= (self.audio.audio_sample()['position_ms'] or 0) <= 2400)
    def test_strict_decoder_list_does_not_decode_pcm(self):
        self.audio = Mpv(os.environ['DUALTHEATER_MPV'], None, Path(self.tmp.name), diagnostic=False)
        with patch('host.mpv.subprocess.Popen', side_effect=self.null_output): self.audio.launch()
        # Bypass auto-TrueHD selection to exercise the decoder fallback prohibition.
        self.audio.command('set_property', 'user-data/dualtheater-aid', '1')
        self.audio.command('loadfile', str(self.wav), 'replace')
        time.sleep(.3)
        self.assertIsNone(self.audio.get('audio-out-params'))
        with self.assertRaises(RuntimeError): self.audio.verify()

    def test_source_timestamp_script_reports_fresh_advancing_audio(self):
        self.audio = Mpv(os.environ['DUALTHEATER_MPV'], None, Path(self.tmp.name), diagnostic=True)
        with patch('host.mpv.subprocess.Popen', side_effect=self.null_output): self.audio.launch()
        self.audio.command('loadfile', str(self.wav), 'replace')
        self.wait(lambda: self.audio.get('audio-out-params'))
        self.audio.pause(False)
        samples = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and len(samples) < 6:
            sample = self.audio.timed_audio_sample()
            if sample['position_ms'] is not None:
                samples.append(sample)
            time.sleep(.05)
        self.assertEqual(len(samples), 6)
        self.assertGreater(samples[-1]['position_ms'], samples[0]['position_ms'])
        for sample in samples:
            self.assertEqual(sample['source'], 'mpv_source_clock')
            self.assertLess(abs(time.perf_counter_ns() - sample['host_ns']), 3_000_000_000)
            self.assertGreaterEqual(sample['uncertainty_ms'], 0)

    def test_truehd_packet_path_and_seek_with_null_output(self):
        clip = Path(__file__).resolve().parents[1] / 'calibration-SDR-TrueHD-no-Atmos.mkv'
        if not clip.exists(): self.skipTest('Generate calibration clip first')
        self.audio = Mpv(os.environ['DUALTHEATER_MPV'], None, Path(self.tmp.name), diagnostic=False)
        with patch('host.mpv.subprocess.Popen', side_effect=self.null_output): self.audio.launch()
        self.audio.command('loadfile', str(clip), 'replace')
        params = self.wait(lambda: self.audio.get('audio-out-params'))
        self.assertEqual(params['format'], 'spdif-truehd')
        self.assertEqual(self.audio.get('current-ao'), 'null')
        self.audio.pause(False)
        self.wait(lambda: self.audio.audio_sample()['position_ms'] is not None)
        self.audio.pause(); self.audio.seek(8); self.audio.pause(False)
        self.wait(lambda: 8000 <= (self.audio.audio_sample()['position_ms'] or 0) <= 8500)


if __name__ == '__main__': unittest.main()
