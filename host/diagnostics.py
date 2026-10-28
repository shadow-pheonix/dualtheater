"""Bounded session metrics and an explicit allowlist for shareable reports.

Never redact a raw snapshot: it contains paths, credentials and arbitrary strings.
Only numbers, booleans and known vocabulary cross the export boundary.
"""
from collections import deque
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from . import __version__

OPERATIONS = ('load', 'play', 'pause', 'seek', 'track', 'resync', 'offset', 'recovery')
STATES = ('idle', 'loading', 'seeking', 'paused', 'armed', 'playing', 'ended', 'error')


def number(value, low=-1e12, high=1e12):
    # Numeric-looking strings and bools are intentionally not accepted.
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        return None
    return round(value, 3)


def vocabulary(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unknown'


def save_report(path, report):
    """Atomically save a report already built by SessionDiagnostics.report."""
    payload = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + '\n'
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.dualtheater-report-', delete=False) as file:
            temporary = Path(file.name)
            file.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class SessionDiagnostics:
    """One host lifetime; drift statistics use the latest 600 accepted samples."""
    def __init__(self):
        self.lock = threading.Lock()
        self.started_ns = time.perf_counter_ns()
        self.samples = deque(maxlen=600)
        self.sample_count = 0
        self.last_sample_ns = None
        self.operations = {op: {'count': 0, 'failures': 0, 'last_ms': None, 'max_ms': None}
                           for op in OPERATIONS}
        self.recoveries = {'buffering': 0, 'drift': 0}
        self.errors = 0
        self.disconnects = 0

    def timing(self, drift_ms, rtt_ms, uncertainty_ms):
        values = (number(drift_ms), number(rtt_ms, 0), number(uncertainty_ms, 0))
        if None in values:
            return
        with self.lock:
            self.samples.append(values)
            self.sample_count += 1
            self.last_sample_ns = time.perf_counter_ns()

    def operation(self, op, elapsed_ms, failed=False):
        if not isinstance(op, str) or op not in OPERATIONS:
            return
        elapsed_ms = number(elapsed_ms, 0)
        if elapsed_ms is None:
            return
        with self.lock:
            row = self.operations[op]
            row['count'] += 1
            row['failures'] += bool(failed)
            row['last_ms'] = elapsed_ms
            row['max_ms'] = max(row['max_ms'] or 0, elapsed_ms)

    def recovery(self, kind):
        if kind in ('buffering', 'drift'):
            with self.lock:
                self.recoveries[kind] += 1

    def error(self):
        with self.lock:
            self.errors += 1

    def disconnected(self):
        with self.lock:
            self.disconnects += 1

    def report(self, *, state, connected, status, status_age_ms, epoch, audio, video_lead_ms):
        now = time.perf_counter_ns()
        with self.lock:
            samples = list(self.samples)
            sample_count, last_sample = self.sample_count, self.last_sample_ns
            operations = {op: dict(row) for op, row in self.operations.items()}
            recoveries = dict(self.recoveries)
            errors, disconnects = self.errors, self.disconnects
        drift = sorted(abs(row[0]) for row in samples)
        signed = sorted(row[0] for row in samples)
        age = number(status_age_ms, 0)
        fresh = connected and age is not None and age <= 2000 and status.get('epoch') == epoch
        telemetry = 'fresh' if fresh else 'stale' if connected and age is not None else 'waiting' if connected else 'disconnected'
        current = status if fresh else {}
        position, buffered = number(current.get('position_ms'), 0), number(current.get('buffered_ms'), 0)
        buffer_ahead = max(0, buffered - position) if position is not None and buffered is not None else None
        frame = current.get('frame')
        frame = frame if isinstance(frame, dict) else {}
        return {
            'schema_version': 1,
            'app_version': __version__,
            'scope': 'current_host_session',
            'measurement': 'API estimates; physical lip-sync, HDR and Atmos reception are unverified',
            'elapsed_seconds': round(max(0, now - self.started_ns) / 1e9, 1),
            'state': vocabulary(state, STATES),
            'connected': connected is True,
            'telemetry': {
                'status': telemetry, 'age_ms': age,
                'buffer_ahead_ms': number(buffer_ahead, 0),
                'dropped_video_frames': number(current.get('dropped_video_frames'), 0),
                'transfer_mbps': number(current.get('transfer_mbps'), 0),
                'transfer_age_ms': number(current.get('transfer_age_ms'), 0),
                'heap_limit_mb': number(current.get('heap_limit_mb'), 0),
                'buffer_budget_mb': number(current.get('buffer_budget_mb'), 0),
                'video_mime': vocabulary(frame.get('mime'), ('video/hevc', 'video/avc', 'video/dolby-vision', 'video/av01', 'video/x-vnd.on2.vp9')),
                'video_width': number(frame.get('width'), 1, 32768),
                'video_height': number(frame.get('height'), 1, 32768),
            },
            'audio': {
                'truehd_last_verified': audio.get('valid') is True,
                'diagnostic_mode': audio.get('diagnostic') is True,
                'output': vocabulary(audio.get('ao'), ('wasapi', 'null')),
                'format': vocabulary(audio.get('format'), ('spdif-truehd',)),
            },
            'timing': {
                'video_lead_ms': number(video_lead_ms, -2000, 2000),
                'accepted_samples': sample_count,
                'last_sample_age_ms': round(max(0, now - last_sample) / 1e6, 1) if last_sample is not None else None,
                'window_capacity': 600, 'window_samples': len(samples),
                'median_drift_ms': signed[len(signed) // 2] if signed else None,
                'p95_absolute_drift_ms': drift[math.ceil(len(drift) * .95) - 1] if drift else None,
                'max_absolute_drift_ms': drift[-1] if drift else None,
                'max_clock_rtt_ms': max(row[1] for row in samples) if samples else None,
                'max_ipc_uncertainty_ms': max(row[2] for row in samples) if samples else None,
            },
            'operations': operations,
            'recoveries': recoveries,
            'errors': errors,
            'disconnects': disconnects,
        }
