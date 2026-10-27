"""Dependency-free LAN discovery: small UDP probe and unicast response."""
import json
import re
import socket

DISCOVERY_PORT = 8767


def response(data, host_id, name, control_port):
    if len(data) > 1024:
        return None
    try:
        query = json.loads(data)
        nonce = query.get('nonce', '')
        if (query.get('op') != 'dualtheater.discover' or query.get('version') != 1
                or not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
            return None
    except (ValueError, AttributeError, UnicodeError):
        return None
    # No pairing code, legacy token or remembered credential is ever broadcast.
    return json.dumps({'op': 'dualtheater.host', 'version': 1, 'nonce': nonce,
                       'host_id': host_id, 'name': name, 'control_port': control_port},
                      separators=(',', ':')).encode()


class DiscoveryServer:
    def __init__(self, app, address='0.0.0.0', port=DISCOVERY_PORT):
        self.app = app
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind((address, port))
            self.socket.settimeout(.5)
        except OSError:
            self.socket.close()
            raise

    def serve(self):
        while not self.app.stop.is_set():
            try:
                data, address = self.socket.recvfrom(2048)
                answer = response(data, self.app.pairings.host_id, self.app.host_name,
                                  self.app.args.control_port)
                if answer:
                    self.socket.sendto(answer, address)
            except socket.timeout:
                continue
            except OSError:
                return

    def close(self):
        self.socket.close()
