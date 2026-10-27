package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class RemoteControlsTest {
    @Test public void repeatedKeysAccumulateFromPreviewInsteadOfLivePlayback() {
        RemoteControls controls = new RemoteControls();
        assertEquals(110000, controls.nudge(100000, 300000, 10000));
        assertEquals(120000, controls.nudge(103000, 300000, 10000));
        assertEquals(110000, controls.nudge(104000, 300000, -10000));
        controls.clearPreview();
        assertEquals(95000, controls.nudge(105000, 300000, -10000));
    }
    @Test public void seekingClampsAtBothEndsAndUnknownDuration() {
        RemoteControls controls = new RemoteControls();
        assertEquals(0, controls.nudge(2000, 300000, -10000));
        controls.clearPreview();
        assertEquals(299900, controls.nudge(298000, 300000, 10000));
        controls.clearPreview();
        assertEquals(0, controls.nudge(0, 0, 10000));
    }
    @Test public void onlyMatchingAcknowledgementUnlocksPendingInput() {
        RemoteControls controls = new RemoteControls();
        assertFalse(controls.complete(-1));
        long first = controls.begin();
        assertTrue(controls.isPending());
        assertEquals(-1, controls.begin());
        assertFalse(controls.complete(first + 1));
        assertTrue(controls.isPending());
        assertTrue(controls.complete(first));
        assertFalse(controls.isPending());
    }
    @Test public void resetDoesNotReuseRequestNumbers() {
        RemoteControls controls = new RemoteControls();
        long first = controls.begin();
        controls.nudge(0, 100000, 10000);
        controls.reset();
        assertFalse(controls.hasPreview());
        long next = controls.begin();
        assertTrue(next > first);
        assertFalse(controls.complete(first));
        assertTrue(controls.isPending());
    }
    @Test public void timestampsUseMovieHoursWhenNeeded() {
        assertEquals("00:00", RemoteControls.time(-1));
        assertEquals("02:05", RemoteControls.time(125999));
        assertEquals("1:00:00", RemoteControls.time(3600000));
        assertEquals("2:36:31", RemoteControls.time(9391000));
    }
}
