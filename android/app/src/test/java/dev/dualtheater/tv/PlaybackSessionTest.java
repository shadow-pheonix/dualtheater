package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class PlaybackSessionTest {
    @Test public void restartedHostCanLoadWithLowerEpochAfterAuthenticatedReset() {
        PlaybackSession session = new PlaybackSession();
        session.accept(40);
        session.reset();
        assertEquals(0, session.epoch());
        assertTrue(session.accept(1));
        assertEquals(1, session.epoch());
    }

    @Test public void olderCommandsRemainInvalidWithinTheSameConnection() {
        PlaybackSession session = new PlaybackSession();
        session.accept(12);
        try { session.accept(11); fail("Accepted old transport command"); }
        catch (IllegalStateException expected) {}
        assertEquals(12, session.epoch());
        assertFalse(session.accept(12));
    }

    @Test public void callbackFromOldConnectionCannotMatchReusedEpoch() {
        PlaybackSession session = new PlaybackSession();
        session.accept(2);
        long oldCallback = session.generation();
        session.reset();
        session.accept(2);
        assertFalse(session.matches(oldCallback));
        assertTrue(session.matches(session.generation()));
    }

    @Test public void newEpochInvalidatesScheduledCallbackButSameEpochSpeedDoesNot() {
        PlaybackSession session = new PlaybackSession();
        session.accept(4);
        long callback = session.generation();
        session.accept(4);
        assertTrue(session.matches(callback));
        session.accept(5);
        assertFalse(session.matches(callback));
    }
}
