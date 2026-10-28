package dev.dualtheater.calibration;

import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class MeasurementTest {
    @Test public void audioSamplesUseCaptureAnchorsIncludingClockDrift() {
        AudioTimeline timeline = new AudioTimeline();
        long base = 5_000_000_000_000L;
        double slope = 1e9 / 48000 * 1.0001;
        for (int i = 0; i < 10; i++) timeline.add(i * 4800L, base + Math.round(i * 4800 * slope));
        assertTrue(timeline.ready());
        assertEquals(base + Math.round(15000 * slope), timeline.time(15000), 2);
    }

    @Test public void repeatedAudioAnchorDoesNotCreateFalseReadiness() {
        AudioTimeline timeline = new AudioTimeline();
        for (int i = 0; i < 10; i++) timeline.add(0, 5_000_000_000L);
        assertFalse(timeline.ready());
    }

    @Test public void microphoneDiscontinuitiesAndStaleExtrapolationAreRejected() {
        AudioTimeline timeline = new AudioTimeline();
        for (int i = 0; i < 4; i++) timeline.add(i * 4800, 5_000_000_000L + i * 100_000_000L);
        try { timeline.add(1, 5_500_000_000L); fail(); } catch (IllegalStateException expected) {}
        try { timeline.time(100000); fail(); } catch (IllegalStateException expected) {}
    }

    @Test public void microphoneTimestampJumpsAreRejected() {
        AudioTimeline timeline = new AudioTimeline();
        timeline.add(0, 5_000_000_000L);
        try { timeline.add(4800, 5_120_000_000L); fail(); } catch (IllegalStateException expected) {}
    }

    @Test public void toneOnsetsRetainSamplePositionAcrossArbitraryReadBoundaries() {
        List<long[]> events = new ArrayList<>();
        ToneDetector detector = new ToneDetector((lo, hi) -> events.add(new long[]{lo, hi}));
        int[] starts = {96000, 230000, 388000, 504000, 682000, 844000};
        short[] pcm = new short[900000];
        Random random = new Random(42);
        for (int i = 0; i < pcm.length; i++) pcm[i] = (short)(random.nextInt(101) - 50);
        for (int start : starts) for (int i = start; i < start + 1920; i++)
            pcm[i] += (short)(5000 * Math.sin(2 * Math.PI * 1000 * i / 48000));
        int position = 0;
        while (position < pcm.length) {
            int length = Math.min(317, pcm.length - position);
            detector.accept(Arrays.copyOfRange(pcm, position, position + length), length);
            position += length;
        }
        assertEquals(6, events.size());
        for (int i = 0; i < starts.length; i++) {
            assertTrue(events.get(i)[0] <= starts[i]);
            assertTrue(events.get(i)[1] >= starts[i]);
        }
    }

    @Test public void broadbandNoiseDoesNotLookLikeTheReferenceTone() {
        List<Long> events = new ArrayList<>();
        ToneDetector detector = new ToneDetector((lo, hi) -> events.add(lo));
        Random random = new Random(123);
        short[] pcm = new short[48000];
        for (int i = 0; i < pcm.length; i++) pcm[i] = (short)(random.nextInt(10001) - 5000);
        detector.accept(pcm, pcm.length);
        assertTrue(events.isEmpty());
    }

    @Test public void quietCleanBeepIsDetectedWithoutRequiringLoudCaptureLevels() {
        List<Long> events = new ArrayList<>();
        ToneDetector detector = new ToneDetector((lo, hi) -> events.add(lo));
        short[] pcm = new short[12000];
        for (int i = 4800; i < 6720; i++) pcm[i] = (short)(100 * Math.sin(2 * Math.PI * 1000 * i / 48000));
        detector.accept(pcm, pcm.length);
        assertEquals(1, events.size());
    }

    private MeasurementEngine capture(long origin, double gapMs, int missing) {
        MeasurementEngine engine = new MeasurementEngine();
        for (int frame = 0; frame < 1320; frame++) {
            long start = origin + Math.round(frame * 1e9 / 60), end = start + 8_000_000L;
            if (frame == 40) {
                assertTrue(engine.ready()); engine.begin();
                for (double cue : MeasurementEngine.CUES_MS) {
                    long time = origin + Math.round((cue + gapMs) * 1e6);
                    engine.tone(time - 5_000_000, time + 5_000_000);
                }
            }
            double middleMs = (start - origin + 4_000_000) / 1e6;
            boolean flash = false;
            for (int i = 0; i < MeasurementEngine.CUES_MS.length; i++)
                if (i != missing && middleMs >= MeasurementEngine.CUES_MS[i]
                    && middleMs < MeasurementEngine.CUES_MS[i] + 1000.0 / 24) flash = true;
            engine.frame(flash ? 220 : 16, start, end);
        }
        return engine;
    }

    @Test public void knownPhysicalGapFallsInsideEachReportedCaptureInterval() {
        double[][] pairs = capture(9_000_000_000_000L, 45, -1).pairs();
        assertNotNull(pairs); assertEquals(6, pairs.length);
        for (double[] pair : pairs) assertTrue(Math.abs(pair[0] - 45) <= pair[1]);
    }

    @Test public void measurementsDoNotDependOnPhoneUptimeOrHostClock() {
        double[][] first = capture(5_000_000_000L, -65, -1).pairs();
        double[][] later = capture(5_000_000_000_000L, -65, -1).pairs();
        assertNotNull(first); assertNotNull(later);
        for (int i = 0; i < first.length; i++) assertEquals(first[i][0], later[i][0], .001);
    }

    @Test public void missedFlashDoesNotBecomeAWholePeriodOffset() {
        assertNull(capture(5_000_000_000L, 45, 2).pairs());
    }

    @Test public void largeGapsAndBackwardCameraTimestampsInvalidateCapture() {
        MeasurementEngine engine = new MeasurementEngine();
        engine.frame(16, 5_000_000_000L, 5_005_000_000L);
        try { engine.frame(16, 5_200_000_000L, 5_205_000_000L); fail(); }
        catch (IllegalStateException expected) {}
        try { engine.frame(16, 4_900_000_000L, 4_905_000_000L); fail(); }
        catch (IllegalStateException expected) {}
    }
}
