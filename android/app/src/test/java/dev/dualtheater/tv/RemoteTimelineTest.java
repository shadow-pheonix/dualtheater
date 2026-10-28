package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class RemoteTimelineTest {
    @Test public void positiveTwoSecondLeadDoesNotExpireBeforeAudioStarts() {
        RemoteTimeline t = new RemoteTimeline(); long video = 1_000_000_000L, audio = 3_000_000_000L;
        t.arm(1, 0, audio, video, 2_000_000, 0); t.start(video);
        for (int i = 1; i <= 20; i++) t.read(video + i * 100_000_000L);
        assertEquals("acquiring", t.state(audio));
        assertTrue(t.accept(1, 1, audio, 2_000_000, 1, 1, audio));
        assertEquals(2_000_000, t.read(audio), 1);
    }
    @Test public void arbitraryOriginsSignedLeadAndReset() {
        RemoteTimeline t = new RemoteTimeline(); long origin = 8_000_000_000_000L;
        t.arm(2, 50_000_000, origin, origin + 70_000_000, -70_000, origin - 100_000_000);
        t.start(origin + 70_000_000);
        assertEquals(50_100_000, t.read(origin + 170_000_000), 1);
        assertFalse(t.accept(1, 2, origin, 0, 1, 0, origin));
        t.reset(3, 200_000, origin + 200_000_000);
        assertEquals(200_000, t.read(origin + 400_000_000));
        assertEquals("paused", t.state(origin + 400_000_000));
    }
    @Test public void duplicateOutOfOrderExpiredAndJumpAreRejected() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        assertFalse(t.accept(1, 1, start, 0, 1, 1, start));
        assertFalse(t.accept(1, 2, start - 600_000_000, 0, 1, 1, start));
        assertFalse(t.accept(1, 3, start, 900_000, 1, 1, start));
        assertEquals("audio_phase_jump", t.state(start));
    }
    @Test public void monotonicSlewDriftAndHoldover() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        long previous = 0;
        for (int i = 1; i < 3000; i++) {
            long now = start + i * 10_000_000L;
            if (i % 5 == 0) assertTrue(t.accept(1, i, now, Math.round(i * 10_000 * 1.0002), 1.0002, 1, now));
            long p = t.read(now); assertTrue(p >= previous); previous = p;
            assertTrue(t.rate(now) >= .995 && t.rate(now) <= 1.005);
        }
        assertEquals("locked", t.state(start + 29_990_000_000L));
        assertEquals("holdover", t.state(start + 30_300_000_000L));
        long frozen = t.read(start + 31_000_000_000L);
        assertEquals(frozen, t.read(start + 32_000_000_000L));
        assertEquals("audio_anchor_expired", t.state(start + 32_000_000_000L));
    }
}
