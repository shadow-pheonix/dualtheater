package dev.dualtheater.tv;
import org.junit.Test;
import static org.junit.Assert.*;

public class FrameObservationsTest {
    @Test public void eventTimeIsIndependentOfDelayedCallbackAndOldFramesAreRejected() {
        FrameObservations o = new FrameObservations();
        long codec = o.beginCodec();
        o.schedule(2, 7, 123_000, 1_000_000_000);
        o.submit(codec, 9_000_000, 1_000_000_000);
        o.rendered(codec, 9_000_000, 1_013_000_000, 1_400_000_000);
        assertEquals(1_013_000_000, o.latest().renderedNs);
        assertEquals(123_000, o.latest().mediaUs);
        o.schedule(2, 6, 122_000, 900_000_000);
        o.submit(codec, 8_000_000, 900_000_000);
        o.rendered(codec, 8_000_000, 913_000_000, 1_500_000_000);
        assertEquals(7, o.latest().sequence);
        o.clear();
        o.rendered(codec, 9_000_000, 1_013_000_000, 1_500_000_000);
        assertNull(o.latest());
    }
    @Test public void mismatchedSubmissionsAndExpiredEventsDoNotBecomeMeasurements() {
        FrameObservations o = new FrameObservations();
        long codec = o.beginCodec();
        o.schedule(1, 1, 0, 1_000_000_000);
        o.submit(codec, 1, 900_000_000);
        o.rendered(codec, 1, 1_010_000_000, 1_100_000_000);
        assertNull(o.latest());
        o.submit(codec, 1, 1_000_000_000);
        o.rendered(codec, 1, 1_600_000_000, 1_700_000_000);
        assertNull(o.latest());
    }
    @Test public void retiredCodecCannotConsumeOrClearNewSubmissionWithTheSamePts() {
        FrameObservations o = new FrameObservations();
        long old = o.beginCodec(), current = o.beginCodec();
        o.schedule(3, 8, 123_000, 1_000_000_000);
        o.submit(current, 9_000_000, 1_000_000_000);
        o.rendered(old, 9_000_000, 1_013_000_000, 1_400_000_000);
        o.clearCodec(old); o.retireCodec(old);
        assertNull(o.latest());
        o.rendered(current, 9_000_000, 1_013_000_000, 1_400_000_000);
        assertEquals(8, o.latest().sequence);
    }
}
