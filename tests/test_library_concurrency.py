import argparse
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from host.server import Coordinator, ns
from host.diagnostics import SessionDiagnostics
from host.desktop_support import DesktopService
from test_core import FakeMpv


class LibraryConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        args = argparse.Namespace(data_dir=self.tmp.name, host='127.0.0.1', control_port=0,
                                  media_port=0, diagnostic=True, device='null', sync_mode='baseline')
        self.app = Coordinator(args)
        self.responses = []
        self.peer = type('Client', (), {'closed': False, 'client_protocol': 1, 'last_client_id': 0,
            'status': {'epoch': 0}, 'status_seen': ns(), 'role': 'tv', 'storage': None,
            'address': '127.0.0.1', 'send': lambda p, body: self.responses.append(body),
            'request': lambda p, operation, **fields: p.status.update(epoch=fields.get('epoch', 0)),
            'close': lambda p: setattr(p, 'closed', True)})()
        self.app.peer = self.peer
        self.threads = []
        self.release = threading.Event()

    def tearDown(self):
        self.release.set(); self.app.stop.set()
        for thread in self.threads: thread.join(1)
        self.app.close(); self.tmp.cleanup()

    def start(self, target):
        thread = threading.Thread(target=target, daemon=True); thread.start(); self.threads.append(thread)

    def test_slow_library_read_does_not_delay_coordinated_pause(self):
        entered = threading.Event()
        def slow_browse(*args):
            entered.set(); self.release.wait(2); return {'entries': []}
        self.app.browse_provider = slow_browse
        self.app.mpv = FakeMpv(); self.app.mpv.loaded = True
        self.app.media = Path(self.tmp.name)/'movie.mkv'; self.app.media.write_bytes(b'fixture')
        self.app.state = 'playing'; self.app.media_generation = 1
        self.start(self.app.client_worker); self.start(self.app.browse_worker)
        self.app.enqueue_client(self.peer, {'id': 1, 'action': 'browse', 'provider': 'phone'})
        self.assertTrue(entered.wait(1))
        self.app.enqueue_client(self.peer, {'id': 2, 'action': 'pause', 'epoch': 0, 'media_generation': 1})
        until = time.monotonic() + .75
        while self.app.state != 'paused' and time.monotonic() < until: time.sleep(.01)
        self.assertEqual(self.app.state, 'paused')
        self.assertFalse(self.release.is_set(), 'Browse should still be pending')
        self.assertTrue(self.app.mpv.paused)

    def test_repeated_identical_storage_registration_does_not_revoke_a_playing_source(self):
        registration = {'port': 30001, 'token': 'a' * 32, 'label': 'TV storage'}
        self.app.storage_register(self.peer, registration)
        source = self.app.storage_providers['tv']
        self.app.remote_media = {'provider': 'tv', 'source': source.copy(), 'detached': False}
        self.app.storage_register(self.peer, dict(registration))
        self.assertIs(self.app.storage_providers['tv'], source)
        self.assertFalse(self.app.remote_media['detached'])
        self.app.storage_register(self.peer, dict(registration, token='b' * 32))
        self.assertTrue(self.app.remote_media['detached'])

    def test_unicode_catalog_is_bounded_and_keeps_selected_track(self):
        self.app.track_catalog = [{'id': str(i), 'label': '字幕' * 100, 'format_label': '字幕' * 60,
                                   'selected': i == 127} for i in range(128)]
        self.peer.status['subtitle_tracks'] = [{'id': f'0:{i}', 'label': '字幕' * 100,
                                                'selected': i == 127} for i in range(128)]
        state = self.app.client_state()
        self.assertLess(len(json.dumps({'op': 'client_state', 'state': state}, ensure_ascii=False).encode()), 65536)
        self.assertTrue(state['catalog_truncated'])
        self.assertTrue(any(row['id'] == '127' and row['selected'] for row in state['audio_tracks']))
        self.assertTrue(any(row['id'] == '0:127' and row['selected'] for row in state['subtitle_tracks']))

    def test_other_bitstream_diagnostics_do_not_claim_truehd(self):
        report = SessionDiagnostics().report(state='paused', connected=False, status={}, status_age_ms=None,
            epoch=0, audio={'valid': True, 'ao': 'wasapi', 'format': 'spdif-eac3'}, video_lead_ms=0)
        self.assertFalse(report['audio']['truehd_last_verified'])
        self.assertTrue(report['audio']['passthrough_last_verified'])
        self.assertEqual(report['audio']['format'], 'spdif-eac3')

    def test_windows_pause_is_not_queued_behind_a_slow_library_read(self):
        entered, paused = threading.Event(), threading.Event()
        app = self.app
        def action(body):
            if body['action'] == 'browse': entered.set(); self.release.wait(2)
            if body['action'] == 'pause': paused.set()
            return {}
        app.action = action
        service = DesktopService(self.tmp.name)
        service.runtime = type('Runtime', (), {'app': app, 'closed': False,
            'close': lambda runtime: None})()
        try:
            service.submit('library', action='browse', provider='phone')
            self.assertTrue(entered.wait(1))
            service.submit('priority_pause')
            self.assertTrue(paused.wait(.75))
            self.assertFalse(self.release.is_set())
        finally:
            self.release.set(); service.submit('close'); self.assertTrue(service.closed.wait(2))
