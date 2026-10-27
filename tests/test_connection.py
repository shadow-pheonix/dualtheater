import argparse
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from host.discovery import DiscoveryServer, response
from host.pairing import PairingStore
from host import server


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'pairings.json'
        self.store = PairingStore(self.path)
        self.client = str(uuid.uuid4())
    def tearDown(self): self.temp.cleanup()
    def authenticate(self, token, **values):
        return self.store.authenticate(token, values.get('client', self.client), 'Test TV',
                                       'legacy-secret', '012345', '192.0.2.10')
    def test_first_pair_and_remembered_login_after_host_restart(self):
        token = self.authenticate('012345')
        self.assertGreaterEqual(len(token), 40)
        restarted = PairingStore(self.path)
        self.assertEqual(restarted.host_id, self.store.host_id)
        self.assertEqual(restarted.authenticate(token, self.client, 'Test TV', 'new-session', '999999', '192.0.2.10'), token)
        self.assertNotEqual(token, '012345')
    def test_wrong_code_does_not_create_credentials(self):
        with self.assertRaises(ValueError): self.authenticate('000000')
        self.assertEqual(self.store.devices, {})
        self.assertEqual(json.loads(self.path.read_text())['devices'], {})
    def test_rate_limit_and_valid_remembered_credentials(self):
        token = self.authenticate('012345')
        for _ in range(5):
            with self.assertRaises(ValueError): self.authenticate('000000')
        with self.assertRaisesRegex(ValueError, 'wait one minute'): self.authenticate('012345')
        self.assertEqual(self.authenticate(token), token)
    def test_legacy_clients_and_invalid_ids(self):
        self.assertIsNone(self.authenticate('legacy-secret', client=None))
        with self.assertRaises(ValueError): self.authenticate('012345', client=None)
        with self.assertRaises(ValueError): self.authenticate('012345', client='bad-id')
        with self.assertRaises(ValueError): self.authenticate('１２３４５６')
    def test_corrupt_store_is_preserved(self):
        self.path.write_text('not JSON')
        with self.assertRaises(RuntimeError): PairingStore(self.path)
        self.assertEqual(self.path.read_text(), 'not JSON')


class DiscoveryTests(unittest.TestCase):
    def test_query_nonce_and_no_credentials_in_reply(self):
        query = json.dumps({'op': 'dualtheater.discover', 'version': 1, 'nonce': 'a' * 32}).encode()
        reply = json.loads(response(query, str(uuid.uuid4()), 'Laptop', 8766))
        self.assertEqual(reply['nonce'], 'a' * 32)
        self.assertEqual(reply['control_port'], 8766)
        self.assertEqual(set(reply), {'op', 'version', 'nonce', 'host_id', 'name', 'control_port'})
        for query in (b'{}', b'bad JSON', b'[]', b'x' * 2048,
                      b'{"op":"dualtheater.discover","version":1,"nonce":"short"}'):
            self.assertIsNone(response(query, 'id', 'Laptop', 8766))
    def test_real_udp_discovery_round_trip(self):
        app = argparse.Namespace(stop=threading.Event(), host_name='Test Laptop',
              pairings=argparse.Namespace(host_id=str(uuid.uuid4())), args=argparse.Namespace(control_port=9876))
        discovery = DiscoveryServer(app, address='127.0.0.1', port=0)
        threading.Thread(target=discovery.serve, daemon=True).start()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.sendto(json.dumps({'op': 'dualtheater.discover', 'version': 1, 'nonce': 'b' * 32}).encode(),
                              discovery.socket.getsockname())
                raw, address = client.recvfrom(2048)
                reply = json.loads(raw)
                self.assertEqual(reply['name'], 'Test Laptop')
                self.assertEqual(reply['control_port'], 9876)
                self.assertEqual(reply['nonce'], 'b' * 32)
        finally: app.stop.set(); discovery.close()


class PairingProtocolTests(unittest.TestCase):
    def test_short_code_handshake_issues_trusted_token_then_reuses_it(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(server, 'ROOT', Path(temp)):
                app = server.Coordinator(argparse.Namespace())
            control = server.ThreadServer(('127.0.0.1', 0), server.ControlHandler); control.app = app
            threading.Thread(target=control.serve_forever, daemon=True).start()
            client_id = str(uuid.uuid4())
            def hello(token):
                with socket.create_connection(control.server_address) as sock:
                    sock.sendall((json.dumps({'op': 'hello', 'version': 1, 'token': token,
                        'client_id': client_id, 'device': 'Test TV', 'remote_controls': True}) + '\n').encode())
                    with sock.makefile('rb') as reader: message = json.loads(reader.readline())
                until = time.monotonic() + 2
                while app.peer and not app.peer.closed and time.monotonic() < until: time.sleep(.01)
                return message
            try:
                denied = hello('wrong-code')
                self.assertEqual(denied['op'], 'auth_required')
                paired = hello(app.pair_code)
                self.assertEqual(paired['op'], 'welcome')
                token = paired['trusted_token']
                app.pair_code = '999999'; app.pair_token = 'changed-session-token'
                remembered = hello(token)
                self.assertEqual(remembered['trusted_token'], token)
                self.assertEqual(remembered['host_id'], paired['host_id'])
            finally: app.close(); control.shutdown(); control.server_close()


if __name__ == '__main__': unittest.main()
