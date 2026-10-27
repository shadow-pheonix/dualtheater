"""Pure clock and video-servo math. All cross-device times are monotonic ns."""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ClockSample:
    offset_ns: int  # Android nanoTime - host perf_counter_ns
    rtt_ns: int
    host_ns: int


class ClockFilter:
    def __init__(self):
        self.samples = deque(maxlen=32)

    def add(self, t0, t1, t2, t3):
        rtt = (t3 - t0) - (t2 - t1)
        if t3 < t0 or t2 < t1 or not 0 <= rtt <= 100_000_000:
            return False
        self.samples.append(ClockSample(((t1 - t0) + (t2 - t3)) // 2, rtt, t3))
        return True

    def best(self, now):
        recent = [s for s in tuple(self.samples) if 0 <= now - s.host_ns < 15_000_000_000]
        return min(recent, key=lambda s: s.rtt_ns) if len(recent) >= 3 else None


class VideoServo:
    """Never changes the audio clock. Positive error means video is ahead.

    A 15 ms deadband prevents frame quantization chasing. Sustained large error
    requests a paused barrier rather than repeatedly seeking during playback.
    """
    def __init__(self):
        self.errors = deque(maxlen=7)
        self.large_count = 0

    def reset(self):
        self.errors.clear()
        self.large_count = 0

    def update(self, error_ms):
        if not math.isfinite(error_ms):
            raise ValueError('Non-finite drift')
        self.errors.append(error_ms)
        if len(self.errors) < 5:
            return 1.0, False
        error = sorted(self.errors)[len(self.errors) // 2]
        self.large_count = self.large_count + 1 if abs(error) > 180 else 0
        speed = 1.0 if abs(error) <= 15 else max(.995, min(1.005, 1 - error / 10_000))
        return speed, self.large_count >= 12


def parse_range(value, size):
    """Single RFC 9110 byte range; None means whole representation.

    Deliberately reject multipart rather than misreporting a partial response.
    """
    if not value:
        return None
    if size <= 0 or not value.startswith('bytes=') or ',' in value:
        raise ValueError('Unsatisfiable range')
    left, sep, right = value[6:].partition('-')
    if not sep or not (left or right):
        raise ValueError('Invalid range')
    if (left and not left.isdecimal()) or (right and not right.isdecimal()):
        raise ValueError('Invalid range')
    if not left:
        count = int(right)
        if count <= 0:
            raise ValueError('Invalid suffix')
        return max(0, size - count), size - 1
    start = int(left)
    end = min(int(right), size - 1) if right else size - 1
    if start >= size or end < start:
        raise ValueError('Unsatisfiable range')
    return start, end
