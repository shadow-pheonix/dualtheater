"""Experimental setup fallback with actual authorized host sockets, no devices."""
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch
from host.server import ns
import test_robust_protocol as protocol
from test_robust_protocol import TimingTV


class FallbackTV(TimingTV):
    def __init__(self, port, token, send_hello):
        self.send_hello = send_hello
        self.udp_address = None
        super().__init__(port, token, datagrams=True, fallback=True)

    def timing_read(self, token):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.connect(('127.0.0.1', self.port))
            self.udp_address = udp.getsockname()
            if self.send_hello:
                udp.send(json.dumps({'op':'hello','version':3,'token':token}).encode())
            # Model a filtered outbound path OR discarded inbound ready/ping.
            # Actual Android's bounded negotiation is separately JVM tested.
            time.sleep(2.55)
        if not self.closed:
            super().timing_read(token)


class TimingFallbackTests(unittest.TestCase):
    setUp = protocol.RobustProtocolTests.setUp
    tearDown = protocol.RobustProtocolTests.tearDown
    wait = protocol.RobustProtocolTests.wait

    def fallback(self, send_hello):
        self.tv = FallbackTV(self.runtime.args.control_port, self.app.pair_token, send_hello)
        self.wait(lambda: self.app.peer and self.app.peer.timing and self.app.peer.timing.transport == 'tcp'
                  and self.app.peer.clock.best(ns()) is not None)
        self.assertFalse(self.app.peer.timing_datagrams)
        self.app.action({'action':'load','path':str(self.movie)})
        self.app.action({'action':'play'})
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.app.action({'action':'pause'})
        self.app.action({'action':'seek','seconds':30})
        self.app.action({'action':'play'})
        self.assertEqual(self.app.state, 'playing', self.app.error)
        self.assertEqual(self.tv.speed_commands, 0)
        self.assertFalse(any(c[:2] == ('set_property','speed') for c in self.app.mpv.commands))

    def test_outbound_udp_blocked_starts_with_tcp_and_preserves_barriers(self):
        self.fallback(False)

    def test_pending_udp_can_fallback_and_late_hello_cannot_replace_tcp(self):
        self.fallback(True)
        peer = self.app.peer
        link, clock = peer.timing, peer.clock
        self.runtime.datagram_timing.receive(json.dumps({'op':'hello','version':3,
            'token':peer.timing_token}).encode(), self.tv.udp_address, ns())
        self.assertIs(peer.timing, link)
        self.assertIs(peer.clock, clock)
        self.assertFalse(link.closed)
        self.assertEqual(self.app.state, 'playing')

    def test_live_and_armed_migration_rejected_and_start_reserves_before_ack(self):
        self.tv = TimingTV(self.runtime.args.control_port, self.app.pair_token, datagrams=False)
        self.wait(lambda: self.app.peer and self.app.peer.clock.best(ns()) is not None)
        peer = self.app.peer
        with socket.socket() as unused:
            old = peer.timing
            for state in ('armed', 'playing'):
                self.app.state = state
                self.assertIsNone(self.app.claim_timing(peer, unused))
                self.assertIs(peer.timing, old)
            self.app.state = 'idle'
            self.app.action({'action':'load','path':str(self.movie)})
            original = peer.request
            reservations = []
            def request(op, **values):
                if op == 'arm':
                    reservations.append(self.app.state)
                    self.assertIsNone(self.app.claim_timing(peer, unused))
                return original(op, **values)
            with patch.object(peer, 'request', side_effect=request):
                self.app.action({'action':'play'})
            self.assertEqual(reservations, ['armed'])
            self.assertEqual(self.app.state, 'playing', self.app.error)

    def test_udp_adoption_does_not_wait_on_control_writer_lock(self):
        # Hold the real control writer lock as if its socket send were slow.
        self.tv = TimingTV(self.runtime.args.control_port, self.app.pair_token)
        self.wait(lambda: self.app.peer and self.app.peer.timing)
        peer = self.app.peer
        self.tv.close_timing()
        self.wait(lambda: peer.timing.closed)
        peer.timing_datagrams = True
        payload = json.dumps({'op':'hello','version':3,'token':peer.timing_token}).encode()
        done = threading.Event()
        def receive():
            try: self.runtime.datagram_timing.receive(payload, ('127.0.0.1', 9), ns())
            finally: done.set()
        with peer.lock:
            worker = threading.Thread(target=receive, daemon=True)
            worker.start()
            self.assertTrue(done.wait(.5), 'UDP waited on the control lock')
            self.assertEqual(peer.timing.transport, 'udp')
        worker.join(1)

    def test_legacy_udp_peer_cannot_silently_switch_to_tcp(self):
        protocol.RobustProtocolTests.connect_datagrams(self)
        peer = self.app.peer
        old = peer.timing
        with socket.socket() as unused:
            self.assertFalse(peer.timing_fallback)
            self.assertIsNone(self.app.claim_timing(peer, unused))
        self.assertIs(peer.timing, old)

    def test_wrong_token_cannot_claim_pending_fallback(self):
        self.tv = FallbackTV(self.runtime.args.control_port, self.app.pair_token, True)
        self.wait(lambda: self.app.peer and self.app.peer.timing)
        peer = self.app.peer
        old = peer.timing
        with socket.create_connection(('127.0.0.1', self.runtime.args.control_port), timeout=1) as sock:
            sock.sendall(b'{"op":"hello","version":1,"role":"timing","token":"wrong"}\n')
            self.assertEqual(sock.recv(10), b'')
        self.assertIs(peer.timing, old)
        self.assertFalse(old.closed)

