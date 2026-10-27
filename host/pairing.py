"""Remember paired TVs without advertising credentials on the LAN."""
from collections import defaultdict, deque
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid


class PairingStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.failures = defaultdict(deque)
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                self.host_id = str(uuid.UUID(data['host_id']))
                self.devices = data['devices']
                if not isinstance(self.devices, dict):
                    raise ValueError('Invalid devices')
                for key, record in self.devices.items():
                    uuid.UUID(key)
                    if not isinstance(record.get('token'), str) or len(record['token']) < 40:
                        raise ValueError('Invalid credential')
            except (ValueError, KeyError, TypeError) as e:
                raise RuntimeError('Cannot read pairings.json; preserve it and repair or rename it before starting') from e
        else:
            self.host_id = str(uuid.uuid4())
            self.devices = {}
            self._save()

    def _save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'host_id': self.host_id,
                                         'devices': self.devices}, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def authenticate(self, token, client_id, name, legacy_token, pair_code, address):
        """Returns a remembered token, or None for a legacy/manual connection."""
        if not isinstance(token, str) or not token.isascii():
            raise ValueError('Enter the six-digit pairing code')
        with self.lock:
            # Existing clients keep their original session-token route.
            legacy = hmac.compare_digest(token, legacy_token)
            if not client_id:
                if legacy:
                    return None
                raise ValueError('Enter the current pairing code using the updated TV app')
            try:
                client_id = str(uuid.UUID(client_id))
            except (ValueError, TypeError, AttributeError) as e:
                raise ValueError('Invalid TV identity') from e
            record = self.devices.get(client_id)
            if record and hmac.compare_digest(token, record['token']):
                return record['token']
            now = time.monotonic()
            failures = self.failures[address]
            while failures and now - failures[0] >= 60:
                failures.popleft()
            if len(failures) >= 5:
                raise ValueError('Too many incorrect codes; wait one minute and try again')
            if not legacy and not hmac.compare_digest(token, pair_code):
                failures.append(now)
                raise ValueError('Enter the six-digit code shown on the laptop')
            if client_id not in self.devices and len(self.devices) >= 32:
                raise ValueError('This laptop already remembers 32 TVs')
            trusted = secrets.token_urlsafe(32)
            previous = self.devices.get(client_id)
            self.devices[client_id] = {'name': str(name)[:80], 'token': trusted}
            try:
                self._save()
            except OSError:
                if previous is None:
                    del self.devices[client_id]
                else:
                    self.devices[client_id] = previous
                raise
            failures.clear()
            return trusted
