"""Session-authorized, bounded latest-value timing; no playback commands."""
from collections import OrderedDict
import hmac
import json
import socket
import threading
import time
from .timing import AffineClock


class DatagramTimingLink:
    transport = 'udp'

    def __init__(self, service, peer, address):
        self.service, self.peer, self.address = service, peer, address
        self.closed = False
        self.pending = OrderedDict()
        self.lock = threading.Lock()
        self.seen_ns = time.perf_counter_ns()

    def send(self, message):
        with self.lock:
            if self.closed:
                raise ConnectionError('Timing connection closed')
            message = dict(message, token=self.peer.timing_token)
            if message.get('op') == 'ping':
                message['t0'] = time.perf_counter_ns()
                self.pending[message['t0']] = None
                while len(self.pending) > 16:
                    self.pending.popitem(last=False)
            payload = json.dumps(message, separators=(',', ':')).encode()
            if len(payload) > 2048:
                raise ValueError('Oversized timing datagram')
            try:
                self.service.socket.sendto(payload, self.address)
            except BlockingIOError:
                return False  # A newer value replaces it next tick.
            return True

    def pong(self, message, received):
        t0 = message.get('t0')
        if type(t0) is not int:
            return
        with self.lock:
            if t0 not in self.pending:
                return
            del self.pending[t0]
        t1, t2 = message.get('t1'), message.get('t2')
        if any(type(t) is not int for t in (t1, t2)) or not 0 <= received - t0 <= 1_000_000_000:
            return
        self.seen_ns = received
        self.peer.clock.add(t0, t1, t2, received)

    def close(self):
        self.closed = True


class DatagramTimingService:
    def __init__(self, app, address):
        self.app = app
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(address)
            self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        self.closed = threading.Event()

    def receive(self, payload, address, received):
        """One bounded packet from the currently authorized control peer."""
        if len(payload) > 2048:
            return
        peer = self.app.peer
        if not peer or peer.closed or not peer.timing_datagrams or address[0] != peer.address:
            return
        try:
            message = json.loads(payload)
            token = message.get('token') if isinstance(message, dict) else None
            if not isinstance(token, str) or not hmac.compare_digest(token, peer.timing_token):
                return
            link = peer.timing
            if message.get('op') == 'hello' and message.get('version') == 3:
                if not link or link.closed:
                    link = DatagramTimingLink(self, peer, address)
                    peer.clock = AffineClock()
                    peer.timing = link
                if isinstance(link, DatagramTimingLink) and link.address == address:
                    link.send({'op': 'timing_ready', 'version': 3})
            elif (message.get('op') == 'pong' and isinstance(link, DatagramTimingLink)
                  and not link.closed and link.address == address):
                link.pong(message, received)
        except (ValueError, TypeError, UnicodeError, RecursionError, OSError):
            return

    def serve(self):
        import select
        while not self.closed.is_set() and not self.app.stop.is_set():
            try:
                readable, _, _ = select.select([self.socket], [], [], .2)
                if readable:
                    payload, address = self.socket.recvfrom(2049)
                    self.receive(payload, address, time.perf_counter_ns())
                peer = self.app.peer
                link = peer.timing if peer else None
                if (isinstance(link, DatagramTimingLink) and not link.closed
                        and time.perf_counter_ns() - link.seen_ns > 3_000_000_000):
                    link.close()
                    if self.app.audio_running.is_set():
                        self.app.timing_error = 'Dedicated timing connection lost; reconnect and reload'
            except (OSError, ValueError):
                if not self.closed.is_set():
                    self.closed.wait(.05)

    def close(self):
        self.closed.set()
        self.socket.close()
