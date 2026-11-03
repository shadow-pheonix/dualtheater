"""Bounded clock/timeline models. Units are monotonic ns and media milliseconds.

Uncertainty describes the software observations, never panel or receiver latency.
"""
from collections import deque
from dataclasses import dataclass
import math
from statistics import median
import threading


class TimingUnavailable(RuntimeError):
    """Allowlisted, actionable preparation error safe to send to the phone."""
    def __init__(self):
        super().__init__('TV timing is unavailable. Wait for TV reconnection, then retry calibration or playback.')


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
        self.last_fit = None
        self.last_fit_sample_ns = -1

    def holdover(self, now):
        with self.lock:
            previous = self.last_fit
        if previous is None or not 0 <= now - previous.host_ns <= 750_000_000:
            return None
        age = now - previous.host_ns
        # This only bridges a temporarily unusable fit. It does not renew
        # itself; uncertainty includes both oscillator and fitted-rate error.
        return ClockEstimate(previous.remote(now) - now, previous.rtt_ns, now,
            previous.rate, math.ceil(previous.uncertainty_ns + age * .002))

    def observations(self, now):
        """Bounded relative numbers for fault diagnosis; no device identifiers."""
        with self.lock:
            rows = list(self.samples)
        origin = rows[-1][1] if rows else 0
        return [{'age_ms': round((now - t) / 1e6, 3),
                 'offset_delta_ms': round((offset - origin) / 1e6, 3),
                 'rtt_ms': round(rtt / 1e6, 3)} for t, offset, rtt, _ in rows]

    def supported_phase(self, rows, now):
        """Track an acquired clock with sparse replies, without inventing readiness."""
        with self.lock:
            previous = self.last_fit
        if previous is None or not rows:
            return self.holdover(now)
        predicted = previous.remote(now) - now
        prior_uncertainty = previous.uncertainty_ns + abs(now - previous.host_ns) * .002
        lower = max(predicted - prior_uncertainty,
            max(s[1] - s[2] / 2 - (now - s[0]) * .001 for s in rows))
        upper = min(predicted + prior_uncertainty,
            min(s[1] + s[2] / 2 + (now - s[0]) * .001 for s in rows))
        if lower > upper:
            return self.holdover(now)
        # The midpoint minimizes worst-case phase error over the supported
        # interval. Keeping a prior estimate at one edge can unnecessarily
        # exhaust the confidence budget despite a usable current exchange.
        phase = (lower + upper) / 2
        estimate = ClockEstimate(round(phase), min(s[2] for s in rows), now, previous.rate,
            math.ceil(max(phase - lower, upper - phase) + 100_000))
        newest = max(s[3] for s in rows)
        with self.lock:
            # Re-polling the same exchanges must not renew the fallback model.
            if newest > self.last_fit_sample_ns and self.last_fit.host_ns <= now:
                self.last_fit, self.last_fit_sample_ns = estimate, newest
        return estimate

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
            # Use live observations for v1.0's unchanged regression. An old
            # minimum RTT must not exclude all healthy replies for 15 seconds.
            rows = [s for s in self.samples if 0 <= now - s[0] <= 3_000_000_000]
        if len(rows) < 3:
            return self.supported_phase(rows, now)
        lowest = min(s[2] for s in rows)
        threshold = max(lowest + 2_000_000, sorted(s[2] for s in rows)[2])
        rows = [s for s in rows if s[2] <= threshold]
        if len(rows) < 3:
            return self.holdover(now)
        origin = rows[-1][0]
        center = median(s[1] for s in rows)
        # Network asymmetry can move an exchange's midpoint by up to RTT/2.
        # A fixed 2 ms phase filter discarded mutually compatible live replies
        # (e.g. 6/11/13 ms RTT), manufacturing expiry during healthy playback.
        # Keep the regression/rate bounds; include the measured delay envelope
        # in outlier selection and retain its residual in the confidence budget.
        rows = [s for s in rows if abs(s[1] - center) <=
                max(2_000_000, (s[2] + lowest) / 2) + abs(s[0] - origin) * .001]
        if len(rows) < 3:
            return self.holdover(now)
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
        # Each exchange bounds the offset by its own RTT/2, expanded to now
        # using the oscillator bound. Residual + minimum RTT double-counted
        # compatible path asymmetry and could exceed 12 ms with a narrow valid
        # interval. Intersect the actual bounds, without assuming symmetry.
        lower = max(s[1] - s[2] / 2 - (now - s[0]) * .001 for s in rows)
        upper = min(s[1] + s[2] / 2 + (now - s[0]) * .001 for s in rows)
        if lower > upper:
            return self.holdover(now)
        phase = (lower + upper) / 2
        uncertainty = max(phase - lower, upper - phase) + 100_000
        estimate = ClockEstimate(round(phase), lowest, now,
                                 1 + slope, math.ceil(uncertainty))
        with self.lock:
            newest = max(s[3] for s in rows)
            if self.last_fit is None or self.last_fit.host_ns <= now and newest > self.last_fit_sample_ns:
                self.last_fit, self.last_fit_sample_ns = estimate, newest
        return estimate


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
        # Keep v1.0's rate fit; current phase must not inherit an old settling
        # residual that rejects every otherwise fresh source observation.
        phase_rows = [r for r in rows if t - r[0] <= 250_000_000]
        intercept = median(r[1] - rate * ((r[0] - t) / 1e6) for r in phase_rows)
        residual = max(abs(r[1] - (intercept + rate * ((r[0] - t) / 1e6))) for r in phase_rows)
        self.sequence += 1
        return {'sequence': self.sequence, 'host_ns': t, 'position_ms': intercept, 'rate': rate,
                'uncertainty_ms': max(r[2] for r in phase_rows) + residual,
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
