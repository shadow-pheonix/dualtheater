import json
import queue
import socket
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from host.desktop_support import runtime_args
from host.server import HostRuntime
import test_core


class ProtocolTV(test_core.SimulatedTV):
    """A simulated TV that negotiates client protocol 1 and exposes text tracks."""

    def __init__(self, port, token):
        self.client_states = []
        self.client_replies = {}
        self.client_condition = threading.Condition()
        self.client_sequence = 0
        self.welcome = {}
        self.subtitle_tracks = [{
            'id': '0:0', 'label': 'English', 'language': 'eng', 'codec': 'application/pgs',
            'selected': False, 'supported': True, 'format_label': 'PGS bitmap subtitles',
        }]
        self.selected_subtitle = 'off'
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.file = self.sock.makefile('rb')
        self.lock = threading.Lock(); self.closed = False
        self.epoch = 0; self.position = 0; self.start_ns = test_core.server.ns(); self.playing = False
        self.speed = 1; self.state = 'idle'; self.offset_ns = 8_000_000_000
        self.armed = None; self.timing_valid = True
        self.remote_results = {}; self.remote_sequence = 0; self.coordinator = {}
        self.send({'op': 'hello', 'version': 1, 'client_protocol': 1, 'timing_protocol': 2,
                   'remote_controls': True, 'token': token, 'device': 'Protocol test TV'})
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.telemetry, daemon=True).start()

    def read(self):
        try:
            for raw in self.file:
                msg = json.loads(raw); op = msg.get('op')
                if op == 'welcome':
                    self.welcome = msg
                    continue
                if op == 'client_state':
                    with self.client_condition:
                        self.client_states.append(msg['state'])
                        self.client_condition.notify_all()
                    continue
                if op == 'client_response':
                    with self.client_condition:
                        self.client_replies[msg.get('reply')] = msg
                        self.client_condition.notify_all()
                    continue
                if op == 'coordinator': self.coordinator = msg; continue
                if op == 'remote_result': self.remote_results[msg['request']] = msg; continue
                if op == 'ping':
                    now = test_core.server.ns() + self.offset_ns
                    self.send({'op': 'pong', 't0': msg['t0'], 't1': now, 't2': now})
                    continue
                if op == 'subtitle':
                    incoming = msg.get('epoch', -1)
                    sid = msg.get('sid', 'off')
                    error = ''
                    if incoming != self.epoch:
                        error = 'Playback epoch changed'
                    elif sid != 'off' and sid != '0:0':
                        error = 'Subtitle track unavailable'
                    else:
                        self.selected_subtitle = sid
                    self.send({'reply': msg['id'], 'epoch': self.epoch, 'error': error})
                    continue
                if msg.get('epoch', 0) < self.epoch: continue
                self.epoch = msg.get('epoch', self.epoch)
                if op == 'pause':
                    self.position = self.current(); self.playing = False; self.armed = None
                elif op in ('load', 'seek'):
                    self.playing = False; self.position = msg['position_ms']; self.state = 'ready'; self.armed = None
                    if op == 'load': self.selected_subtitle = 'off'
                elif op == 'arm': self.armed = msg['host_ns']
                elif op == 'speed':
                    self.position = self.current(); self.start_ns = test_core.server.ns(); self.speed = msg['value']
                self.send({'reply': msg['id'], 'epoch': self.epoch})
        except (OSError, ValueError, KeyError):
            pass

    def telemetry(self):
        try:
            while not self.closed:
                now = test_core.server.ns()
                if self.armed and now >= self.armed:
                    self.start_ns = self.armed; self.armed = None; self.playing = True
                tracks = [dict(row, selected=row['id'] == self.selected_subtitle) for row in self.subtitle_tracks]
                self.send({'op': 'status', 'epoch': self.epoch, 'state': self.state,
                    'position_ms': self.current(), 'seek_pending': False, 'playing': self.playing,
                    'speed': self.speed, 'subtitle_tracks': tracks,
                    'selected_subtitle': self.selected_subtitle,
                    'frame': {'epoch': self.epoch, 'position_ms': self.current(),
                        'release_ns': now + self.offset_ns, 'valid': self.playing and self.timing_valid}})
                time.sleep(.025)
        except OSError:
            pass

    def latest_state(self):
        with self.client_condition:
            return self.client_states[-1] if self.client_states else {}

    def wait_state(self, predicate, timeout=8):
        until = time.monotonic() + timeout
        with self.client_condition:
            while time.monotonic() < until:
                for state in reversed(self.client_states):
                    if predicate(state): return state
                self.client_condition.wait(max(0.01, until - time.monotonic()))
        raise AssertionError('Timed out waiting for TV client state')

    def client_request(self, action, timeout=15, **fields):
        self.client_sequence += 1
        ident = self.client_sequence
        if action in ('track', 'subtitle', 'play', 'pause', 'seek', 'resync'):
            state = self.latest_state()
            fields.setdefault('epoch', state.get('epoch', self.epoch))
            fields.setdefault('media_generation', state.get('media_generation', -1))
        self.send({'op': 'client_request', 'id': ident, 'action': action, **fields})
        until = time.monotonic() + timeout
        with self.client_condition:
            while time.monotonic() < until:
                if ident in self.client_replies: return self.client_replies.pop(ident)
                self.client_condition.wait(max(0.01, until - time.monotonic()))
        raise AssertionError('Timed out waiting for TV client response: ' + action)


class PhoneClient:
    """Real authenticated calibration-role socket using one shared request ID sequence."""

    def __init__(self, runtime):
        self.socket = socket.create_connection(('127.0.0.1', runtime.args.control_port), timeout=5)
        self.reader = self.socket.makefile('rb')
        self.condition = threading.Condition()
        self.states = []
        self.responses = {}
        self.next_id = 0
        hello = {'op': 'hello', 'version': 1, 'role': 'calibration', 'client_protocol': 1,
                 'client_id': str(uuid.uuid4()), 'device': 'Protocol test phone',
                 'token': runtime.app.pair_token}
        self.socket.sendall((json.dumps(hello) + '\n').encode())
        self.welcome = json.loads(self.reader.readline())
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for raw in self.reader:
                message = json.loads(raw)
                with self.condition:
                    if message.get('op') == 'client_state': self.states.append(message['state'])
                    elif message.get('op') == 'client_response': self.responses[message.get('reply')] = message
                    self.condition.notify_all()
        except (OSError, ValueError):
            pass

    def latest_state(self):
        with self.condition:
            return self.states[-1] if self.states else {}

    def wait_state(self, predicate, timeout=8):
        until = time.monotonic() + timeout
        with self.condition:
            while time.monotonic() < until:
                for state in reversed(self.states):
                    if predicate(state): return state
                self.condition.wait(max(0.01, until - time.monotonic()))
        raise AssertionError('Timed out waiting for phone client state')

    def request(self, action, timeout=15, **fields):
        self.next_id += 1
        ident = self.next_id
        if action in ('track', 'subtitle', 'play', 'pause', 'seek', 'resync'):
            state = self.latest_state()
            fields.setdefault('epoch', state.get('epoch', -1))
            fields.setdefault('media_generation', state.get('media_generation', -1))
        self.socket.sendall((json.dumps({'op': 'client_request', 'id': ident, 'action': action, **fields}) + '\n').encode())
        until = time.monotonic() + timeout
        with self.condition:
            while time.monotonic() < until:
                if ident in self.responses: return self.responses.pop(ident)
                self.condition.wait(max(0.01, until - time.monotonic()))
        raise AssertionError('Timed out waiting for phone client response: ' + action)

    def close(self):
        try: self.socket.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        self.reader.close(); self.socket.close()


class ClientProtocolSocketTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/test', self.directory.name,
            ephemeral=True, sync_mode='baseline'), mpv_factory=test_core.FakeMpv)
        self.runtime.start()
        self.app = self.runtime.app
        self.media_root = Path(self.directory.name) / 'chosen-library'
        self.media_root.mkdir()
        (self.media_root / 'movie.mkv').write_bytes(b'protocol fixture')
        for index in range(104): (self.media_root / f'zz-extra-{index:03}.mkv').write_bytes(b'x')
        self.root_id = self.app.library.add(str(self.media_root))
        self.tv = ProtocolTV(self.runtime.args.control_port, self.app.pair_token)
        self.wait(lambda: self.app.peer and bool(self.app.peer.status))
        self.phone = PhoneClient(self.runtime)

    def tearDown(self):
        if getattr(self, 'phone', None): self.phone.close()
        if getattr(self, 'tv', None): self.tv.close()
        self.runtime.close(); self.directory.cleanup()

    def wait(self, predicate, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate(): return
            time.sleep(.02)
        self.fail('Timed out waiting for host state: ' + str(self.app.state))

    def fresh_phone_state(self):
        return self.phone.wait_state(lambda s: s.get('media_generation') == self.app.media_generation
            and s.get('epoch') == self.app.epoch and bool(s.get('providers')), timeout=8)

    def test_tv_browse_load_phone_tracks_and_disconnect_preserve_host_control(self):
        self.assertEqual(self.tv.welcome.get('client_protocol'), 1)
        self.assertEqual(self.phone.welcome.get('client_protocol'), 1)
        self.assertEqual(self.phone.welcome.get('role'), 'calibration')
        state = self.phone.wait_state(lambda s: bool(s.get('providers')))
        self.assertIn({'id': 'windows', 'label': 'Windows folders', 'available': True}, state['providers'])

        providers = self.tv.client_request('providers')
        self.assertTrue(providers['ok'], providers)
        self.assertIn('tv', [row['id'] for row in providers['result']['providers']])
        first_page = self.tv.client_request('browse', provider='windows', entry='', cursor=0)
        self.assertTrue(first_page['ok'], first_page)
        roots = first_page['result']['entries']
        selected_root = next(row for row in roots if row['id'] == self.root_id)
        self.assertNotIn(str(self.media_root), selected_root['id'])
        listing = self.tv.client_request('browse', provider='windows', entry=selected_root['id'], cursor=0)
        self.assertTrue(listing['ok'], listing)
        self.assertLessEqual(len(listing['result']['entries']), 100)
        self.assertEqual(listing['result']['next_cursor'], 100)
        movie = next(row for row in listing['result']['entries'] if row['name'] == 'movie.mkv')
        self.assertNotIn(str(self.media_root), movie['id'])

        self.app.action({'action': 'offset', 'milliseconds': 125})
        loaded = self.tv.client_request('load_entry', provider='windows', entry=movie['id'], autoplay=True, timeout=20)
        self.assertTrue(loaded['ok'], loaded)
        self.wait(lambda: self.app.state == 'playing')
        generation = self.app.media_generation
        offset = self.app.offset_ms
        state = self.phone.wait_state(lambda s: s.get('media_generation') == generation
            and s.get('state') == 'playing' and bool(s.get('audio_tracks')) and bool(s.get('subtitle_tracks')))
        tv_state = self.tv.wait_state(lambda s: s.get('media_generation') == generation
            and bool(s.get('audio_tracks')) and bool(s.get('subtitle_tracks')))
        self.assertTrue(any(track['id'] == '1' and track['supported'] for track in state['audio_tracks']))
        self.assertTrue(any(track['id'] == '0:0' and track['supported'] for track in tv_state['subtitle_tracks']))

        selected_audio = self.phone.request('track', aid='1', epoch=state['epoch'], media_generation=generation)
        self.assertTrue(selected_audio['ok'], selected_audio)
        self.wait(lambda: self.app.state == 'playing' and self.app.epoch != state['epoch'])
        self.assertEqual(self.app.media_generation, generation)
        self.assertEqual(self.app.offset_ms, offset)

        state = self.fresh_phone_state()
        selected_subtitle = self.phone.request('subtitle', sid='0:0', epoch=state['epoch'], media_generation=generation)
        self.assertTrue(selected_subtitle['ok'], selected_subtitle)
        self.wait(lambda: self.app.selected_subtitle == '0:0'
            and self.app.peer.status.get('selected_subtitle') == '0:0')
        self.assertEqual(self.app.media_generation, generation)

        stale = self.phone.request('subtitle', sid='off', epoch=self.app.epoch,
            media_generation=generation - 1)
        self.assertFalse(stale['ok'])
        self.assertIn('Movie changed', stale['error'])
        with self.app.op_lock:
            self.app.track_catalog.append({'id': '99', 'label': 'Unsupported test codec', 'supported': False})
        state = self.fresh_phone_state()
        unsupported = self.phone.request('track', aid='99', epoch=state['epoch'], media_generation=generation)
        self.assertFalse(unsupported['ok'])
        self.assertIn('unavailable', unsupported['error'].lower())
        self.assertEqual(str(self.app.mpv.aid), '1')
        self.assertEqual(self.app.state, 'playing')
        self.assertEqual(self.app.error, '')

        forbidden = self.phone.request('library_add', path=str(self.media_root))
        self.assertFalse(forbidden['ok'])
        self.assertIn('Unsupported client action', forbidden['error'])
        playback_before_rejected_path = (self.app.state, self.app.epoch, self.app.media_generation,
            self.app.offset_ms, self.app.mpv.current())
        escaped = self.phone.request('load_entry', provider='windows', entry=str(self.media_root / 'movie.mkv'), autoplay=False)
        self.assertFalse(escaped['ok'])
        self.assertEqual(self.app.media, self.media_root / 'movie.mkv')
        self.assertEqual(self.app.media_generation, generation)
        self.assertEqual(self.app.state, playback_before_rejected_path[0])
        self.assertEqual(self.app.epoch, playback_before_rejected_path[1])
        self.assertEqual(self.app.offset_ms, playback_before_rejected_path[3])
        self.assertAlmostEqual(self.app.mpv.current(), playback_before_rejected_path[4], delta=1500)

        state = self.fresh_phone_state()
        seek = self.phone.request('seek', seconds=45.0, play_after=True,
            epoch=state['epoch'], media_generation=generation)
        self.assertTrue(seek['ok'], seek)
        self.wait(lambda: self.app.state == 'playing' and self.app.epoch != state['epoch'])
        self.assertAlmostEqual(self.app.mpv.current(), 45000, delta=1500)
        self.assertEqual(self.app.media_generation, generation)
        self.assertEqual(self.app.offset_ms, offset)
        state = self.fresh_phone_state()
        paused = self.phone.request('pause', epoch=state['epoch'], media_generation=generation)
        self.assertTrue(paused['ok'], paused)
        self.wait(lambda: self.app.state == 'paused')
        self.assertEqual(self.app.media_generation, generation)
        self.assertEqual(self.app.offset_ms, offset)

        self.phone.close(); self.phone = None
        self.wait(lambda: not self.app.calibration.snapshot()['phone_connected'])
        self.app.action({'action': 'play'})
        self.assertEqual(self.app.state, 'playing')
        self.app.action({'action': 'pause'})
        self.assertEqual(self.app.state, 'paused')
        tv_state = self.tv.wait_state(lambda s: s.get('media_generation') == generation
            and s.get('epoch') == self.app.epoch)
        tv_paused = self.tv.client_request('pause', epoch=tv_state['epoch'], media_generation=generation)
        self.assertTrue(tv_paused['ok'], tv_paused)
        self.assertEqual(self.app.state, 'paused')

    def test_state_and_library_providers_exist_without_any_clients(self):
        self.phone.close(); self.phone = None
        self.tv.close(); self.tv = None
        self.wait(lambda: self.app.peer is None or self.app.peer.closed)
        state = self.app.client_state()
        self.assertFalse(state['can_control'])
        providers = {row['id']: row for row in state['providers']}
        self.assertTrue(providers['windows']['available'])
        self.assertFalse(providers['tv']['available'])
        self.assertFalse(providers['phone']['available'])


if __name__ == '__main__':
    unittest.main()
