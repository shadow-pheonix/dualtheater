import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import queue
import threading
import tempfile
import time
import unittest

from host.library import Library
from host.server import Coordinator, Peer
from host import server
from host.mpv import Mpv


class LibraryTests(unittest.TestCase):
    def test_persisted_grants_are_opaque_bounded_and_revocable(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'chosen'; root.mkdir()
            (root / 'one.mkv').write_bytes(b'video')
            (root / 'skip.txt').write_text('not media')
            db = base / 'private' / 'library.json'
            library = Library(db)
            root_id = library.add(str(root))
            self.assertEqual(json.loads(db.read_text())['roots'][0]['path'], str(root.resolve()))
            root_page = library.browse()
            self.assertEqual(root_page['entries'][0]['id'], root_id)
            page = library.browse(root_id)
            self.assertEqual(len(page['entries']), 1)
            item_id = page['entries'][0]['id']
            self.assertNotIn(str(root), item_id)
            self.assertEqual(library.resolve_file(item_id).read_bytes(), b'video')
            # Root grants persist, item IDs expire across sessions.
            restored = Library(db)
            self.assertEqual(len(restored.roots_list()), 1)
            with self.assertRaisesRegex(ValueError, 'expired'):
                restored.resolve_file(item_id)
            library.remove(root_id)
            with self.assertRaisesRegex(ValueError, 'expired'):
                library.resolve_file(item_id)
            self.assertEqual(Library(db).roots_list(), [])

    def test_missing_root_grant_is_preserved_for_removable_media(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root = base / 'removable'; root.mkdir()
            db = base / 'library.json'; library = Library(db); root_id = library.add(str(root))
            root.rename(base / 'offline')
            restored = Library(db); entry = restored.browse()['entries'][0]
            self.assertEqual(entry['id'], root_id)
            self.assertFalse(entry['available'])
            self.assertEqual(len(restored.roots), 1)

    def test_corrupt_grants_are_preserved_and_do_not_get_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); db = base / 'library.json'; db.write_text('{broken')
            before = db.read_bytes(); library = Library(db)
            with self.assertRaisesRegex(ValueError, 'preserved'): library.add(str(base))
            self.assertEqual(db.read_bytes(), before)

    def test_retargeted_grant_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root = base / 'root'; root.mkdir(); outside = base / 'outside'; outside.mkdir()
            library = Library(base / 'library.json'); root_id = library.add(str(root))
            root.rename(base / 'original')
            try: root.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError): self.skipTest('Windows symlink privilege unavailable')
            with self.assertRaisesRegex(ValueError, 'identity'): library.browse(root_id)

    def test_escape_symlink_is_not_listed_or_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root = base / 'root'; outside = base / 'outside'
            root.mkdir(); outside.mkdir(); (outside / 'secret.mkv').write_bytes(b'x')
            link = root / 'escape.mkv'
            try: link.symlink_to(outside / 'secret.mkv')
            except (OSError, NotImplementedError): self.skipTest('Windows symlink privilege unavailable')
            library = Library(base / 'library.json'); root_id = library.add(str(root))
            self.assertEqual(library.browse(root_id)['entries'], [])

    def test_browse_pages_are_capped_at_one_hundred(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'root'; root.mkdir()
            for index in range(205): (root / f'{index:03}.mkv').write_bytes(b'x')
            library = Library(Path(temp) / 'library.json'); root_id = library.add(str(root))
            first = library.browse(root_id)
            self.assertEqual(len(first['entries']), 100)
            self.assertEqual(first['next_cursor'], 100)
            second = library.browse(root_id, first['next_cursor'])
            self.assertEqual(len(second['entries']), 100)
            self.assertEqual(second['next_cursor'], 200)


class TrackCatalogTests(unittest.TestCase):
    def test_supported_formats_and_metadata_qualification_do_not_infer_objects(self):
        tracks = Coordinator.make_track_catalog([
            {'type': 'audio', 'id': 1, 'codec': 'truehd', 'channels': 8, 'selected': True,
             'title': 'Stereo calibration - no Atmos', 'lang': 'eng', 'demux-channels': 'stereo'},
            {'type': 'audio', 'id': 2, 'codec': 'eac3', 'title': 'Original Atmos mix', 'lang': 'tel',
             'demux-channel-layout': '5.1'},
            {'type': 'audio', 'id': 3, 'codec': 'aac', 'channels': 8, 'title': 'Surround'}])
        self.assertTrue(tracks[0]['supported'])
        self.assertNotIn('Atmos (track title)', tracks[0]['format_label'])
        self.assertIn('Dolby TrueHD \u00b7 stereo', tracks[0]['format_label'])
        self.assertIn('English', tracks[0]['label'])
        self.assertEqual(Coordinator.badge_for(tracks), 'English \u00b7 Dolby TrueHD \u00b7 stereo')
        self.assertIn('Atmos (track title)', tracks[1]['format_label'])
        self.assertIn('Telugu', tracks[1]['label'])
        self.assertIn('5.1', tracks[1]['format_label'])
        self.assertFalse(tracks[2]['supported'])
        self.assertIn('8 channels', tracks[2]['format_label'])

    def test_unknown_client_errors_do_not_return_private_host_details(self):
        app = object.__new__(Coordinator)
        app.error = 'mpv could not open C:\\Private\\movie.mkv at HDMI endpoint DEADBEEF'
        app.peer = None; app.media = None; app.remote_media = None; app.media_title = ''
        app.state = 'error'; app.epoch = 4; app.media_generation = 1; app.audio_sample = {}
        app.anchor_ms = 0; app.duration_ms = 0; app.offset_ms = 0; app.track_catalog = []
        app.audio_badge = ''; app.selected_subtitle = 'off'; app.storage_providers = {}
        app.library = type('LibraryStub', (), {'providers': lambda self: []})()
        state = app.client_state()
        self.assertNotIn('Private', state['error'])
        self.assertNotIn('DEADBEEF', state['error'])
        self.assertLessEqual(len(state['error']), 240)

    def test_verification_requires_the_selected_codec_passthrough_format(self):
        mpv = Mpv('unused', 'unused', Path('.'))
        values = {'current-ao': 'wasapi', 'audio-decoder': 'no'}
        mpv.get = lambda name, default=None: values.get(name, default)
        for codec, fmt in (('truehd', 'spdif-truehd'), ('ac3', 'spdif-ac3'),
                           ('eac3', 'spdif-eac3'), ('dts', 'spdif-dts'),
                           ('dts-hd', 'spdif-dts-hd')):
            values.update({'audio-codec-name': codec, 'audio-out-params': {'format': fmt},
                           'current-tracks/audio': {'codec-profile': 'DTS' if codec == 'dts' else ''}})
            self.assertTrue(mpv.verify()['valid'], codec)
        values.update({'audio-codec-name': 'dts', 'audio-out-params': {'format': 'spdif-dts-hd'},
                       'current-tracks/audio': {'codec-profile': 'DTS-HD MA'}})
        self.assertTrue(mpv.verify()['valid'])
        values['audio-out-params'] = {'format': 'spdif-dts'}
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'): mpv.verify()
        values['audio-out-params'] = {'format': 'float'}
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'): mpv.verify()


class ClientQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        args = argparse.Namespace(data_dir=self.tmp.name, host='127.0.0.1', control_port=0,
                                  media_port=0, diagnostic=True, device='null', sync_mode='baseline')
        self.app = Coordinator(args, mpv_factory=lambda *args: None)
        self.responses = []
        self.peer = type('PeerStub', (), {'client_protocol': 1, 'last_client_id': 0, 'closed': False,
              'send': lambda peer, body: self.responses.append(body)})()
        self.app.peer = self.peer

    def tearDown(self):
        self.app.csv_file.close(); self.tmp.cleanup()

    def test_client_ids_must_be_monotonic_and_media_generation_is_required(self):
        self.app.enqueue_client(self.peer, {'id': 1, 'action': 'providers'})
        queued = self.app.client_queue.get_nowait()
        self.assertEqual(queued[1]['id'], 1)
        self.app.client_queue.task_done()
        with self.assertRaises(queue.Empty): self.app.client_queue.get_nowait()
        self.app.enqueue_client(self.peer, {'id': 1, 'action': 'providers'})
        self.assertFalse(self.responses[-1]['ok'])
        self.app.enqueue_client(self.peer, {'id': 2, 'action': 'track', 'aid': '1'})
        self.assertFalse(self.responses[-1]['ok'])

    def test_stale_media_generation_is_rejected_by_worker(self):
        self.app.media_generation = 3; self.app.epoch = 7
        worker = threading.Thread(target=self.app.client_worker, daemon=True); worker.start()
        self.app.enqueue_client(self.peer, {'id': 1, 'action': 'subtitle', 'sid': '0:0',
                                            'epoch': 7, 'media_generation': 2})
        deadline = time.monotonic() + 2
        while not self.responses and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(len(self.responses), 1)
        self.assertFalse(self.responses[0]['ok'])
        self.assertIn('Movie changed', self.responses[0]['error'])
        self.app.stop.set(); worker.join(1)

    def test_pause_cancels_only_after_current_session_generation_check(self):
        self.app.media_generation = 3; self.app.epoch = 7
        self.app.cancel.clear()
        self.app.enqueue_client(self.peer, {'id': 1, 'action': 'pause', 'epoch': 6, 'media_generation': 3})
        self.assertFalse(self.responses[-1]['ok'])
        self.assertFalse(self.app.cancel.is_set())
        self.app.enqueue_client(self.peer, {'id': 2, 'action': 'pause', 'epoch': 7, 'media_generation': 3})
        self.assertTrue(self.app.cancel.is_set())
        item = self.app.client_queue.get_nowait(); self.assertEqual(item[1]['id'], 2)
        self.app.client_queue.task_done()

    def test_local_track_and_subtitle_stale_choices_do_not_fail_playback(self):
        self.app.media_generation = 3; self.app.epoch = 7
        self.app.track_catalog = [{'id': '1', 'supported': True}]
        self.peer.status = {'subtitle_tracks': [{'id': '0:0', 'supported': True}]}
        self.peer.status_seen = 1
        for body in ({'action': 'track', 'aid': 1, 'epoch': 6, 'media_generation': 3},
                     {'action': 'subtitle', 'sid': '0:0', 'epoch': 7, 'media_generation': 2},
                     {'action': 'subtitle', 'sid': '0:1'}):
            with self.assertRaises(ValueError): self.app.action(body)
            self.assertEqual(self.app.state, 'idle')
            self.assertEqual(self.app.error, '')

    def test_storage_unregister_only_revokes_the_sending_peer_provider(self):
        owner = type('PeerStub', (), {'role': 'phone', 'storage': None, 'closed': False})()
        other = type('PeerStub', (), {'role': 'tv', 'storage': 'tv', 'closed': False})()
        self.app.storage_providers['tv'] = {'peer': other, 'address': '127.0.0.1', 'port': 1, 'token': 'x'}
        self.assertEqual(self.app.storage_unregister(owner), {'removed': True})
        self.assertIn('tv', self.app.storage_providers)


class AndroidProxyTests(unittest.TestCase):
    def test_proxy_keeps_authenticated_source_identity_and_forwards_ranges(self):
        payload = bytes(range(256)) * 8
        class StorageHandler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                if self.path != '/capability/file/item': self.send_error(404); return
                raw = self.headers.get('Range', '')
                if raw:
                    left, right = map(int, raw.removeprefix('bytes=').split('-', 1))
                    body = payload[left:right + 1]
                    self.send_response(206); self.send_header('Content-Range', f'bytes {left}-{right}/{len(payload)}')
                else:
                    body = payload; self.send_response(200)
                self.send_header('Content-Length', str(len(body))); self.send_header('Accept-Ranges', 'bytes')
                self.end_headers(); self.wfile.write(body)
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), StorageHandler)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(data_dir=temp, host='127.0.0.1', control_port=0, media_port=8765,
                                      diagnostic=True, device='null', sync_mode='baseline')
            app = Coordinator(args, mpv_factory=lambda *args: None)
            try:
                app.media_token = 'host-capability'
                peer = type('StoragePeer', (), {'closed': False})()
                source = {'address': '127.0.0.1', 'port': upstream.server_port,
                          'token': 'capability', 'peer': peer}
                app.storage_providers['phone'] = source
                app.remote_media = {'provider': 'phone', 'entry': 'item', 'size': len(payload),
                    'name': 'movie.mkv', 'suffix': 'mkv', 'detached': False,
                    'source': source.copy()}
                proxy = server.ThreadingHTTPServer(('127.0.0.1', 0), server.HttpHandler)
                proxy.app, proxy.local_ui = app, False
                threading.Thread(target=proxy.serve_forever, daemon=True).start()
                conn = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
                conn.request('GET', '/media/host-capability/mkv', headers={'Range': 'bytes=12-27'})
                response = conn.getresponse(); body = response.read()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.getheader('Content-Range'), f'bytes 12-27/{len(payload)}')
                self.assertEqual(body, payload[12:28]); conn.close()
                app.storage_providers['phone'] = dict(source, token='retired-capability')
                conn = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
                conn.request('GET', '/media/host-capability/mkv')
                self.assertEqual(conn.getresponse().status, 410); conn.close()
                app.storage_providers['phone'] = source
                peer.closed = True
                conn = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
                conn.request('GET', '/media/host-capability/mkv')
                self.assertEqual(conn.getresponse().status, 410); conn.close()
                proxy.shutdown(); proxy.server_close()
            finally:
                app.csv_file.close()
        upstream.shutdown(); upstream.server_close()
