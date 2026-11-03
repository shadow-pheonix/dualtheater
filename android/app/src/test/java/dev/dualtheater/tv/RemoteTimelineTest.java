package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class RemoteTimelineTest {
    @Test public void deliveryCanRecoverWithinTransportDeadlineWhileConfidenceRemainsBounded() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        long lead = 137_000; // Generic calibration fixture, not a device profile.
        long video = start - lead * 1000;
        t.arm(1, 0, start, video, lead, 0); t.start(video); t.read(start);
        assertTrue(t.accept(1, 1, start, lead, 1, 7.5, start));
        for (int i = 1; i <= 260; i++) t.read(start + i * 10_000_000L);
        assertEquals("holdover", t.state(start + 2_600_000_000L));
        assertTrue(t.uncertaintyMs(start + 2_600_000_000L) < 22);
        assertEquals(lead + 2_600_000, t.read(start + 2_600_000_000L), 1);
        assertTrue(t.accept(1, 2, start + 2_600_000_000L, lead + 2_600_000,
            1, 7.5, start + 2_600_000_000L));
        assertEquals("locked", t.state(start + 2_600_000_000L));
        assertEquals(lead + 2_600_000, t.read(start + 2_600_000_000L), 1);
    }

    @Test public void absentTimingStillExpiresAtTheTransportDeadline() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        assertEquals("holdover", t.state(start + 2_900_000_000L));
        t.read(start + 3_010_000_000L);
        assertEquals("audio_anchor_expired", t.state(start + 3_010_000_000L));
    }

    @Test public void nativeRendererRebufferCannotFreezeOrRepositionTheExternalMaster() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        assertEquals(100_000, t.read(start + 100_000_000L), 1);
        // Video renderer stopped/re-enabled while independent HDMI audio plays.
        t.rendererResetPosition(50_000, start + 250_000_000L);
        t.start(start + 350_000_000L);
        assertEquals(350_000, t.read(start + 350_000_000L), 1);
        assertEquals("holdover", t.state(start + 350_000_000L));
        t.reset(2, 900_000, start + 400_000_000L);
        assertEquals(900_000, t.read(start + 700_000_000L));
        assertEquals("paused", t.state(start + 700_000_000L));
    }
    @Test public void briefDeliveryGapUsesBoundedConfidenceWithoutAJumpOrFresheningOldPackets() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        for (int i = 1; i <= 100; i++) t.read(start + i * 10_000_000L);
        assertEquals("holdover", t.state(start + 1_000_000_000L));
        assertFalse(t.accept(1, 2, start + 100_000_000L, 100_000, 1, 1, start + 1_000_000_000L));
        assertEquals(1000, t.anchorAgeMs(start + 1_000_000_000L), .001);
        assertTrue(t.accept(1, 3, start + 1_300_000_000L, 1_300_000, 1, 1, start + 1_300_000_000L));
        assertEquals(1_300_000, t.read(start + 1_300_000_000L), 1);
        assertEquals("locked", t.state(start + 1_300_000_000L));
        long frozen = t.read(start + 4_400_000_000L);
        assertEquals("audio_anchor_expired", t.state(start + 4_400_000_000L));
        assertEquals(frozen, t.read(start + 5_000_000_000L));
    }

    @Test public void holdoverExpiresEarlierWhenConfidenceIsExhausted() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 21.5, start));
        assertEquals(100_000, t.read(start + 100_000_000L), 1);
        assertEquals(100_000, t.read(start + 200_000_000L), 1);
        assertEquals("audio_anchor_expired", t.state(start + 200_000_000L));
    }

    @Test public void validatorMatchesTheHostRateAndConfidenceContract() {
        long start = 1_000_000_000L;
        for (double source : new double[]{.999, 1.001}) {
            for (double clock : new double[]{.999, 1.001}) {
                RemoteTimeline t = new RemoteTimeline(); t.arm(1, 0, start, start, 0, 0);
                assertTrue(t.accept(1, 1, start, 0, source / clock, 22, start));
            }
        }
        RemoteTimeline t = new RemoteTimeline(); t.arm(1, 0, start, start, 0, 0);
        assertFalse(t.accept(1, 1, start, 0, 1.001 / .999 + .000001, 1, start));
        assertFalse(t.accept(1, 1, start, 0, 1, 22.001, start));
    }
    @Test public void epochResetPreservesPositionsPastThirtyFiveMinutes() {
        RemoteTimeline t = new RemoteTimeline(); long now = 1_000_000_000L;
        for (long millis : new long[]{2_147_483L, 2_147_484L, 3_300_000L, 14_400_000L}) {
            t.resetMillis(1, millis, now);
            assertEquals(millis * 1000L, t.read(now + 100_000_000L));
            assertEquals("paused", t.state(now));
        }
    }

    @Test public void delayedTimingThreadCannotCreateFalsePhaseJump() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        // Receipt was timestamped before parsing/lock acquisition. Meanwhile
        // the renderer has already advanced the same clock on another thread.
        t.read(start + 400_000_000L);
        assertTrue(t.accept(1, 2, start + 40_000_000L, 40_000, 1, 1, start + 50_000_000L));
        assertEquals("holdover", t.state(start + 400_000_000L));
        assertEquals(400_000, t.read(start + 400_000_000L), 1);
        assertEquals(0, t.phaseMs(), .001);
    }

    @Test public void delayedProcessingDoesNotMakeOldAnchorFresh() {
        RemoteTimeline t = new RemoteTimeline(); long start = 1_000_000_000L;
        t.arm(1, 0, start, start, 0, 0); t.start(start);
        assertTrue(t.accept(1, 1, start, 0, 1, 1, start));
        t.read(start + 600_000_000L);
        assertFalse(t.accept(1, 2, start + 40_000_000L, 40_000, 1, 1, start + 50_000_000L));
        assertEquals("holdover", t.state(start + 600_000_000L));
    }

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
        long frozen = t.read(start + 33_100_000_000L);
        assertEquals(frozen, t.read(start + 34_000_000_000L));
        assertEquals("audio_anchor_expired", t.state(start + 34_000_000_000L));
    }
}
