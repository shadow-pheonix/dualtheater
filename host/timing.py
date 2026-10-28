"""Bounded clock/timeline models. Units are monotonic ns and media milliseconds.

Uncertainty describes the software observations, never panel or receiver latency.
"""
from collections import deque
from dataclasses import dataclass
import math
from statistics import median
import threading


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class ClockEstimate:
    offset_ns: int  # remote minus host at host_ns
    rtt_ns: int
    host_ns: int
    rate: float = 1.0  # remote clock / host clock
    uncertainty_ns: int = 0

    def remote(self, host_ns):
        return self.host_ns + self.offset_ns + round((host_ns - self.host_ns) * self.rate)

    def host(self, remote_ns):
        return self.host_ns + round((remote_ns - self.host_ns - self.offset_ns) / self.rate)


class AffineClock:
    """Four timestamps, low-delay selection and robust offset/rate regression.

    Assumes each oscillator is within 500 ppm of nominal. RTT/2 remains in the
    budget: regression residuals cannot establish network path symmetry.
    """
    def __init__(self):
        self.samples = deque(maxlen=128)
        self.lock = threading.Lock()

    def add(self, t0, t1, t2, t3):
        if any(type(t) is not int or abs(t) > 2**63 - 1 for t in (t0, t1, t2, t3)):
            return False
        rtt = (t3 - t0) - (t2 - t1)
        if t3 <= t0 or t2 < t1 or not 0 <= rtt <= 100_000_000:
            return False
        with self.lock:
            # Duplicate/replayed exchanges must not manufacture readiness.
            if self.samples and t0 <= self.samples[-1][3]:
                return False
            self.samples.append(((t0 + t3) // 2, ((t1 - t0) + (t2 - t3)) / 2, rtt, t0))
        return True

    def best(self, now):
        with self.lock:
            rows = [s for s in self.samples if 0 <= now - s[0] <= 15_000_000_000]
        if len(rows) < 3:
            return None
        lowest = min(s[2] for s in rows)
        threshold = max(lowest + 2_000_000, sorted(s[2] for s in rows)[2])
        rows = [s for s in rows if s[2] <= threshold]
        if len(rows) < 3:
            return None
        origin = rows[-1][0]
        center = median(s[1] for s in rows)
        # Reject gross phase outliers before rate fitting, allowing clock drift.
        rows = [s for s in rows if abs(s[1] - center) <= 2_000_000 + abs(s[0] - origin) * .001]
        if len(rows) < 3:
            return None
        weights = [1 / max(200_000, s[2])**2 for s in rows]
        total = sum(weights)
        xmean = sum((s[0] - origin) * w for s, w in zip(rows, weights)) / total
        ymean = sum(s[1] * w for s, w in zip(rows, weights)) / total
        span = rows[-1][0] - rows[0][0]
        denom = sum(w * ((s[0] - origin) - xmean)**2 for s, w in zip(rows, weights))
        slope = (sum(w * ((s[0] - origin) - xmean) * (s[1] - ymean)
                     for s, w in zip(rows, weights)) / denom if span >= 2_000_000_000 and denom else 0)
        # Short-span queue noise is not evidence of an impossible oscillator.
        # Revert to offset-only and retain the larger residual in its budget.
        if abs(slope) > .001:
            slope = 0
        offset = ymean - slope * xmean
        residual = max(abs(s[1] - (offset + slope * (s[0] - origin))) for s in rows)
        age = now - origin
        uncertainty = lowest / 2 + residual + 100_000 + age * .001
        return ClockEstimate(round(offset + slope * age), lowest, now,
                             1 + slope, math.ceil(uncertainty))


class AudioTimeline:
    def __init__(self):
        self.samples = deque(maxlen=50)
        self.sequence = 0

    def reset(self):
        self.samples.clear()

    def add(self, sample):
        t, position, uncertainty = (sample.get(k) for k in ('host_ns', 'position_ms', 'uncertainty_ms'))
        if type(t) is not int or not numeric(position) or not numeric(uncertainty) or not 0 <= uncertainty <= 10:
            return None
        if self.samples:
            old = self.samples[-1]
            dt = (t - old[0]) / 1e6
            if dt <= 0:
                return None
            if dt > 1000 or position < old[1] - 2 or abs((position - old[1]) - dt) > 50:
                raise ValueError('Audio timeline discontinuity; coordinated resynchronization required')
        self.samples.append((t, position, uncertainty))
        rows = list(self.samples)
        rate = 1.0
        if len(rows) >= 5 and t - rows[0][0] >= 500_000_000:
            xs = [(r[0] - t) / 1e6 for r in rows]
            ys = [r[1] for r in rows]
            xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
            rate = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / sum((x - xm)**2 for x in xs)
            rate = max(.999, min(1.001, rate))
        intercept = median(r[1] - rate * ((r[0] - t) / 1e6) for r in rows)
        residual = max(abs(r[1] - (intercept + rate * ((r[0] - t) / 1e6))) for r in rows)
        self.sequence += 1
        return {'sequence': self.sequence, 'host_ns': t, 'position_ms': intercept, 'rate': rate,
                'uncertainty_ms': max(r[2] for r in rows) + residual,
                'source': sample.get('source', 'ipc_midpoint')}


class AdaptiveServo:
    """Time-based phase/frequency control; duplicate frames are rejected upstream."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.rows = deque(maxlen=7)
        self.last_ns = self.large_since = None
        self.integral = 0.0

    def update(self, error_ms, now_ns, uncertainty_ms=0):
        if not numeric(error_ms) or not numeric(uncertainty_ms) or uncertainty_ms < 0:
            raise ValueError('Invalid timing observation')
        if self.last_ns is not None and now_ns <= self.last_ns:
            return None, False
        dt = min(.5, (now_ns - self.last_ns) / 1e9) if self.last_ns is not None else 0
        self.last_ns = now_ns
        self.rows.append(error_ms)
        if len(self.rows) < 5:
            return 1.0, False
        error = median(self.rows)
        deadband = max(8, uncertainty_ms + 2)
        phase = 0 if abs(error) <= deadband else error
        self.integral = max(-.001, min(.001, self.integral - phase * dt * .0000002))
        speed = max(.995, min(1.005, 1 + self.integral - phase / 8000))
        if abs(error) > max(180, uncertainty_ms * 3):
            if self.large_since is None:
                self.large_since = now_ns
        else:
            self.large_since = None
        return speed, self.large_since is not None and now_ns - self.large_since >= 1_200_000_000
