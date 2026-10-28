"""Read-only LG status and HDMI latency inspection. No inferred DSP latency.

The LG wire format/constants are documented by google/python-temescal (Apache-2.0)
and diogolccsilva/ha-lg-soundbar. See THIRD_PARTY_NOTICES.md. Windows uses CNG AES,
so the portable host needs no new cryptography package.
"""
import ctypes
import ipaddress
import json
import os
import socket
import struct
import subprocess
import time

GETS = ('PRODUCT_INFO', 'SETTING_VIEW_INFO', 'EQ_VIEW_INFO', 'FUNC_VIEW_INFO')
_KEY = b'T^&*J%^7tr~4^%^&I(o%^!jIJ__+a0 k'
_IV = b"'%^Ur7gy$~t+f)%@"


class WindowsAes:
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('S95TR inspection uses Windows cryptography; run it on the playback PC')
        from ctypes import wintypes as w
        self.api = ctypes.WinDLL('bcrypt')
        ptr, uint = ctypes.c_void_p, w.ULONG
        signatures = {
            'BCryptOpenAlgorithmProvider': ([ctypes.POINTER(ptr), w.LPCWSTR, w.LPCWSTR, uint]),
            'BCryptSetProperty': ([ptr, w.LPCWSTR, ptr, uint, uint]),
            'BCryptGenerateSymmetricKey': ([ptr, ctypes.POINTER(ptr), ptr, uint, ptr, uint, uint]),
            'BCryptEncrypt': ([ptr, ptr, uint, ptr, ptr, uint, ptr, uint, ctypes.POINTER(uint), uint]),
            'BCryptDecrypt': ([ptr, ptr, uint, ptr, ptr, uint, ptr, uint, ctypes.POINTER(uint), uint]),
            'BCryptDestroyKey': ([ptr]), 'BCryptCloseAlgorithmProvider': ([ptr, uint]),
        }
        for name, args in signatures.items():
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = w.LONG
        self.algorithm, self.key = ptr(), ptr()
        self.check(self.api.BCryptOpenAlgorithmProvider(ctypes.byref(self.algorithm), 'AES', None, 0))
        try:
            mode = ctypes.create_string_buffer('ChainingModeCBC\0'.encode('utf-16le'))
            self.check(self.api.BCryptSetProperty(self.algorithm, 'ChainingMode', mode, len(mode) - 1, 0))
            secret = ctypes.create_string_buffer(_KEY)
            self.check(self.api.BCryptGenerateSymmetricKey(self.algorithm, ctypes.byref(self.key),
                None, 0, secret, len(_KEY), 0))
        except Exception:
            self.close(); raise

    @staticmethod
    def check(status):
        if status != 0:
            raise RuntimeError('Windows AES operation failed')

    def transform(self, data, decrypt=False):
        if not data or len(data) % 16 or len(data) > 65536:
            raise ValueError('Invalid encrypted LG frame length')
        source, iv = ctypes.create_string_buffer(data), ctypes.create_string_buffer(_IV)
        result, length = ctypes.create_string_buffer(len(data)), ctypes.c_ulong()
        fn = self.api.BCryptDecrypt if decrypt else self.api.BCryptEncrypt
        self.check(fn(self.key, source, len(data), None, iv, len(_IV), result, len(data),
                      ctypes.byref(length), 0))
        return result.raw[:length.value]

    def close(self):
        if self.key:
            self.api.BCryptDestroyKey(self.key); self.key = None
        if self.algorithm:
            self.api.BCryptCloseAlgorithmProvider(self.algorithm, 0); self.algorithm = None


def packet(message, cipher):
    if message not in GETS:
        raise ValueError('Only allowlisted read-only LG requests are supported')
    raw = json.dumps({'cmd': 'get', 'msg': message}, separators=(',', ':')).encode()
    padding = 16 - len(raw) % 16
    raw = cipher.transform(raw + bytes([padding]) * padding)
    return b'\x10' + struct.pack('>I', len(raw)) + raw


def receive(sock, count, deadline):
    result = bytearray()
    while len(result) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('S95TR inspection timed out')
        sock.settimeout(remaining)
        part = sock.recv(count - len(result))
        if not part:
            raise ConnectionError('S95TR closed the inspection connection')
        result.extend(part)
    return bytes(result)


def read_frame(sock, cipher, deadline):
    header = receive(sock, 5, deadline)
    size = struct.unpack('>I', header[1:])[0]
    if header[0] != 0x10 or size == 0 or size > 65536 or size % 16:
        raise ValueError('Invalid LG frame')
    data = cipher.transform(receive(sock, size, deadline), decrypt=True)
    padding = data[-1]
    if not 1 <= padding <= 16 or data[-padding:] != bytes([padding]) * padding:
        raise ValueError('Invalid LG frame padding')
    value = json.loads(data[:-padding])
    if not isinstance(value, dict) or not isinstance(value.get('data'), dict):
        raise ValueError('Invalid LG response')
    return value


def summarize_lg(responses):
    data = {}
    for message in GETS:
        data.update(responses.get(message, {}))
    raw = data.get('i_av_sync')
    valid = type(raw) is int and 0 <= raw <= 30
    models = [data.get(k) for k in ('s_model_name', 's_model', 'model_name', 'model')]
    model_confirmed = any(isinstance(v, str) and 'S95TR' in v.upper() for v in models)
    def index(key):
        value = data.get(key)
        return value if type(value) is int and 0 <= value <= 255 else None
    return {'protocol': 'lg_local_9741', 'model': 'S95TR' if model_confirmed else 'unconfirmed',
            'added_av_delay_raw': raw if valid else None,
            'added_av_delay_ms': raw * 10 if valid else None,
            'delay_interpretation': 'community_10ms_scale_unverified_on_this_unit',
            'input_id': index('i_curr_func'), 'mode_id': index('i_curr_eq'),
            'total_processing_delay_ms': None, 'automatic_correction_applied': False}


def inspect_s95tr(address, cipher_factory=WindowsAes):
    # Explicit local address only. No scans, cloud credentials, writes or auto-wake.
    addr = ipaddress.ip_address(address)
    if not addr.is_private or addr.is_multicast or addr.is_unspecified:
        raise ValueError('Enter the soundbar address on your private home network')
    cipher = cipher_factory()
    try:
        with socket.create_connection((str(addr), 9741), timeout=3) as sock:
            results, deadline = {}, time.monotonic() + 5
            for message in GETS:
                sock.sendall(packet(message, cipher))
            for _ in range(32):
                value = read_frame(sock, cipher, deadline)
                if value.get('msg') in GETS:
                    results[value['msg']] = value['data']
                if len(results) == len(GETS):
                    break
            return summarize_lg(results)
    finally:
        cipher.close()


def parse_edid(data):
    """Parse declared HDMI latency; no identifiers, no unknown-to-zero conversion."""
    if (len(data) < 128 or len(data) > 4096 or len(data) % 128
        or data[:8] != b'\x00\xff\xff\xff\xff\xff\xff\x00'
        or len(data) != (data[126] + 1) * 128
        or any(sum(data[i:i+128]) % 256 for i in range(0, len(data), 128))):
        raise ValueError('Invalid or incomplete EDID')
    result = {'audio_latency_ms': None, 'video_latency_ms': None,
              'interlaced_audio_latency_ms': None, 'interlaced_video_latency_ms': None,
              'source': 'hdmi_edid_declaration', 'route_verified': False,
              'automatic_correction_applied': False}
    def latency(raw):
        return 2 * (raw - 1) if 1 <= raw <= 251 else None
    for start in range(128, len(data), 128):
        block = data[start:start+128]
        if block[0] != 2:
            continue
        end = block[2]
        if end == 0:
            continue
        if not 4 <= end <= 127:
            raise ValueError('Invalid CTA data block boundary')
        pos = 4
        while pos < end:
            kind, size = block[pos] >> 5, block[pos] & 31
            if pos + 1 + size > end:
                raise ValueError('Truncated CTA data block')
            payload = block[pos+1:pos+1+size]; pos += 1 + size
            if kind != 3 or payload[:3] != b'\x03\x0c\x00':
                continue
            if len(payload) >= 10 and payload[7] & 128:
                result.update(video_latency_ms=latency(payload[8]), audio_latency_ms=latency(payload[9]))
                if payload[7] & 64 and len(payload) >= 12:
                    result.update(interlaced_video_latency_ms=latency(payload[10]),
                                  interlaced_audio_latency_ms=latency(payload[11]))
    return result


def inspect_hdmi():
    if os.name != 'nt':
        raise RuntimeError('HDMI descriptor inspection must run on the Windows playback PC')
    # Raw descriptors/instance IDs stay in this process. Only parsed latency
    # declarations leave it. The descriptor cannot certify the active audio route.
    script = r'''
$ErrorActionPreference = 'Stop'
$result = @()
foreach ($monitor in @(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorDescriptorMethods | Where-Object Active | Select-Object -First 8)) {
    try {
        $first = Invoke-CimMethod -InputObject $monitor -MethodName WmiGetMonitorRawEEdidV1Block -Arguments @{BlockId=[byte]0}
        if ($first.ReturnValue -ne 0) { continue }
        $bytes = [System.Collections.Generic.List[byte]]::new()
        $bytes.AddRange([byte[]]$first.BlockContent)
        $extensions = [int]$bytes[126]
        if ($extensions -gt 31) { continue }
        for ($i=1; $i -le $extensions; $i++) {
            $block = Invoke-CimMethod -InputObject $monitor -MethodName WmiGetMonitorRawEEdidV1Block -Arguments @{BlockId=[byte]$i}
            if ($block.ReturnValue -ne 0) { throw 'EDID read failed' }
            $bytes.AddRange([byte[]]$block.BlockContent)
        }
        $result += [Convert]::ToBase64String($bytes.ToArray())
    } catch { }
}
ConvertTo-Json -InputObject @($result) -Compress
'''
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise RuntimeError('Windows could not read HDMI descriptors')
    import base64
    rows = json.loads(run.stdout.decode('utf-8-sig'))
    if not isinstance(rows, list) or len(rows) > 8:
        raise ValueError('Invalid descriptor result')
    results = []
    for row in rows:
        try:
            results.append(parse_edid(base64.b64decode(row, validate=True)))
        except (ValueError, TypeError):
            continue
    return results
