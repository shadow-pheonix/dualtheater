import json
import os
import struct
import time
import unittest
from unittest.mock import patch
from host.receiver import (GETS, WindowsAes, inspect_s95tr, packet, parse_edid,
                           read_frame, summarize_lg)


class IdentityCipher:
    def transform(self, data, decrypt=False): return data
    def close(self): pass


class FragmentedSocket:
    def __init__(self, data): self.data = bytearray(data); self.sent = []
    def recv(self, count):
        result = self.data[:min(count, 3)]; del self.data[:len(result)]; return bytes(result)
    def settimeout(self, timeout): pass
    def sendall(self, data): self.sent.append(data)
    def __enter__(self): return self
    def __exit__(self, *args): pass


def response(msg, data):
    raw = json.dumps({'msg': msg, 'data': data}).encode()
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    return b'\x10' + struct.pack('>I', len(raw)) + raw


def edid(audio=51, video=16):
    base = bytearray(128); base[:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'; base[126] = 1
    base[127] = -sum(base) % 256
    cta = bytearray(128); cta[0:3] = bytes([2, 3, 17])
    cta[4:17] = bytes([108, 3, 12, 0, 16, 0, 0, 0, 192, video, audio, 21, 61])
    cta[127] = -sum(cta) % 256
    return bytes(base + cta)


class ReceiverTests(unittest.TestCase):
    def test_readonly_probe_handles_fragmentation_and_exports_no_identifiers(self):
        replies = b''.join(response(m, {'i_av_sync': 7, 'i_curr_func': 6,
            's_model_name': 'S95TR', 'serial': 'PRIVATE_SENTINEL'}) for m in GETS)
        sock = FragmentedSocket(replies)
        with patch('host.receiver.socket.create_connection', return_value=sock):
            result = inspect_s95tr('192.168.20.2', IdentityCipher)
        self.assertEqual(result['added_av_delay_ms'], 70)
        self.assertIsNone(result['total_processing_delay_ms'])
        self.assertEqual(result['model'], 'S95TR')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(len(sock.sent), 4)
        for data in sock.sent:
            raw = data[5:]; msg = json.loads(raw[:-raw[-1]])
            self.assertEqual(msg['cmd'], 'get')
            self.assertIn(msg['msg'], GETS)
        with self.assertRaises(ValueError): packet('POWER', IdentityCipher())

    def test_bad_frames_padding_addresses_and_setting_types_are_rejected(self):
        for raw in (b'\x10' + struct.pack('>I', 65552),
                    b'\x10' + struct.pack('>I', 16) + b'\0' * 16):
            with self.assertRaises(ValueError):
                read_frame(FragmentedSocket(raw), IdentityCipher(), time.monotonic() + 1)
        with self.assertRaises(ValueError): inspect_s95tr('8.8.8.8', IdentityCipher)
        for value in (True, -1, 31, '7', None):
            result = summarize_lg({'SETTING_VIEW_INFO': {'i_av_sync': value}})
            self.assertIsNone(result['added_av_delay_ms'])
            self.assertIsNone(result['total_processing_delay_ms'])

    def test_hdmi_declarations_are_not_a_correction_and_unknown_is_not_zero(self):
        result = parse_edid(edid())
        self.assertEqual(result['audio_latency_ms'], 100)
        self.assertEqual(result['video_latency_ms'], 30)
        self.assertEqual(result['interlaced_audio_latency_ms'], 120)
        self.assertFalse(result['automatic_correction_applied'])
        self.assertFalse(result['route_verified'])
        for unknown in (0, 252, 255): self.assertIsNone(parse_edid(edid(audio=unknown))['audio_latency_ms'])
        self.assertEqual(parse_edid(edid(audio=1))['audio_latency_ms'], 0)
        for bad in (edid()[:-1], edid()[:128], edid()[:10] + b'\x01' + edid()[11:]):
            with self.assertRaises(ValueError): parse_edid(bad)

    @unittest.skipUnless(os.name == 'nt', 'Windows CNG AES backend')
    def test_windows_aes_matches_public_protocol_vector(self):
        # Expected ciphertext independently generated with OpenSSL AES-256-CBC,
        # no padding, using the published LG protocol key and IV.
        expected = bytes.fromhex('03dc86ea34efb4bcedb7b522e071816f')
        cipher = WindowsAes()
        try:
            self.assertEqual(cipher.transform(bytes(range(16))), expected)
            self.assertEqual(cipher.transform(expected, decrypt=True), bytes(range(16)))
        finally: cipher.close()
