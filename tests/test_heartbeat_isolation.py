"""Slow optional writes must not starve a real TV control connection."""
import json
import socket
import tempfile
import threading
import time
import unittest

from host.desktop_support import runtime_args
from host.server import HostRuntime
from test_core import FakeMpv


class BlockedDestination:
    closed = False
    client_protocol = 1

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def send(self, message):
        self.entered.set()
        self.release.wait(6)

    def close(self):
        self.closed = True
        self.release.set()


class HeartbeatIsolationTests(unittest.TestCase):
    def check_blocked_destination(self, role):
        with tempfile.TemporaryDirectory() as directory:
            args = runtime_args('fake', 'wasapi/test', directory, ephemeral=True)
            runtime = HostRuntime(args, mpv_factory=FakeMpv).start()
            destination = BlockedDestination()
            sock = socket.create_connection(('127.0.0.1', args.control_port), timeout=.9)
            reader = sock.makefile('rb')
            try:
                sock.sendall((json.dumps({'op': 'hello', 'version': 1,
                    'token': runtime.app.pair_token, 'remote_controls': True}) + '\n').encode())
                self.assertEqual(json.loads(reader.readline())['op'], 'welcome')
                if role == 'phone':
                    runtime.app.calibration.owner = destination
                else:
                    runtime.app.peer.timing = destination
                self.assertTrue(destination.entered.wait(1.5))
                # Two *new* coordinator records after the blocked write began.
                # This is shorter than either transport timeout, but several
                # normal 200ms heartbeats. No HDMI or real media is opened.
                deadline = time.monotonic() + .9
                count = 0
                while count < 2 and time.monotonic() < deadline:
                    message = json.loads(reader.readline())
                    if message.get('op') == 'coordinator':
                        count += 1
                self.assertEqual(count, 2)
                self.assertFalse(runtime.app.peer.closed)
                self.assertFalse(destination.release.is_set())
            finally:
                destination.close()
                runtime.app.calibration.owner = None
                if runtime.app.peer:
                    runtime.app.peer.timing = None
                sock.shutdown(socket.SHUT_RDWR)
                reader.close()
                sock.close()
                runtime.close()

    def test_slow_phone_does_not_starve_tv_control(self):
        self.check_blocked_destination('phone')

    def test_slow_timing_does_not_starve_tv_control(self):
        self.check_blocked_destination('timing')
