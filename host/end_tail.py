"""Bound the final unmatched track tail; never modify compressed audio timing."""
import math


class EndTail:
    MAX_MS = 10_000

    def __init__(self, epoch, peer, now, duration, audio_ms, video_ms, lead_ms):
        values = (duration, audio_ms, video_ms, lead_ms)
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise RuntimeError('Invalid end-of-media position')
        if duration <= 0 or min(audio_ms, video_ms) < max(0, duration - self.MAX_MS):
            raise RuntimeError('An endpoint ended before the final media tail')
        self.epoch, self.peer = epoch, peer
        remaining = max(0, duration - min(audio_ms, video_ms), abs(lead_ms))
        # Allow the normal two-second status-liveness budget to report final
        # video completion; this is only the validated terminal-track phase.
        self.deadline_ns = now + round(min(self.MAX_MS, max(3000, remaining + 2500)) * 1e6)
        self.audio_done = False
        self.final_anchor = None

    def audio_ended(self, anchor, now):
        if (not anchor or not 0 <= now - anchor['host_ns'] <= 750_000_000
                or anchor.get('epoch') != self.epoch):
            raise RuntimeError('Final audio clock is unavailable')
        self.final_anchor = dict(anchor)
        self.audio_done = True

    def project(self, now, sequence):
        if not self.audio_done or self.final_anchor is None or now > self.deadline_ns:
            raise RuntimeError('Final media tail deadline exceeded')
        original = self.final_anchor
        age_ms = max(0, now - original['host_ns']) / 1e6
        uncertainty = original['uncertainty_ms'] + age_ms * .001
        if uncertainty > 10:
            raise RuntimeError('Final media tail clock is too uncertain')
        # Audio is already finished. This explicitly labelled bounded projection
        # lets the remaining VIDEO reach EOF without restarting or retiming audio.
        return dict(epoch=self.epoch, sequence=sequence, host_ns=now,
                    position_ms=original['position_ms'] + age_ms * original.get('rate', 1),
                    rate=original.get('rate', 1), uncertainty_ms=uncertainty,
                    source='end_of_audio_tail')
