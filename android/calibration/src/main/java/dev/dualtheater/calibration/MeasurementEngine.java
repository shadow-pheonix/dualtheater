package dev.dualtheater.calibration;

import java.util.ArrayList;
import java.util.List;

/** Bounded event matching; no Android dependencies, media encoding or network clock. */
final class MeasurementEngine {
    static final double[] CUES_MS = {2000, 115000.0 / 24, 194000.0 / 24, 10500, 341000.0 / 24, 422000.0 / 24};
    static final class Event {
        final long lo, hi;
        Event(long lo, long hi) { this.lo = lo; this.hi = hi; }
        double middleMs() { return lo / 1e6 + (hi - lo) / 2e6; }
        double uncertaintyMs() { return (hi - lo) / 2e6; }
    }
    private final List<Event> flashes = new ArrayList<>(), tones = new ArrayList<>();
    private int darkFrames;
    private double baseline;
    private boolean bright, collecting;
    private long previousStart;

    synchronized boolean ready() { return darkFrames >= 20; }
    synchronized void begin() { flashes.clear(); tones.clear(); collecting = true; bright = false; }
    synchronized int flashCount() { return flashes.size(); }
    synchronized int toneCount() { return tones.size(); }

    synchronized void frame(double luminance, long exposureStart, long exposureEnd) {
        if (!Double.isFinite(luminance) || exposureStart <= 0 || exposureEnd < exposureStart)
            throw new IllegalStateException("Invalid camera exposure metadata");
        if (previousStart > 0 && (exposureStart <= previousStart || exposureStart - previousStart > 100_000_000L))
            throw new IllegalStateException("Camera frames are missing or discontinuous; retry");
        if (exposureEnd - exposureStart > 45_000_000L)
            throw new IllegalStateException("Camera exposure is too long; brighten the screen and retry");
        if (!ready()) {
            baseline += (luminance - baseline) / ++darkFrames;
        } else {
            boolean nowBright = luminance > baseline + Math.max(25, baseline * .4);
            if (nowBright && !bright && collecting) {
                if (flashes.size() >= 24) throw new IllegalStateException("Too many flashes; keep the camera still");
                // Bracket the transition, including integration time of the ROI.
                flashes.add(new Event(previousStart, exposureEnd));
            }
            if (!nowBright) baseline += (luminance - baseline) * .01;
            bright = nowBright;
        }
        previousStart = exposureStart;
    }

    synchronized void tone(long lo, long hi) {
        if (!collecting) return;
        if (lo <= 0 || hi < lo || hi - lo > 30_000_000L) throw new IllegalStateException("Invalid microphone timing");
        if (tones.size() >= 24) throw new IllegalStateException("Too many tones; reduce background noise");
        tones.add(new Event(lo, hi));
    }

    private static List<Event> match(List<Event> events) {
        List<Event> found = null;
        for (int first = 0; first < events.size(); first++) {
            List<Event> trial = new ArrayList<>(); trial.add(events.get(first));
            int index = first + 1;
            for (int cue = 1; cue < CUES_MS.length; cue++) {
                double expected = events.get(first).middleMs() + CUES_MS[cue] - CUES_MS[0];
                while (index < events.size() && events.get(index).middleMs() < expected - 100) index++;
                if (index >= events.size() || Math.abs(events.get(index).middleMs() - expected) > 100) break;
                trial.add(events.get(index++));
            }
            if (trial.size() == CUES_MS.length) {
                if (found != null) throw new IllegalStateException("Ambiguous cue sequence; retry");
                found = trial;
            }
        }
        return found;
    }

    synchronized double[][] pairs() {
        List<Event> video = match(flashes), audio = match(tones);
        if (video == null || audio == null) return null;
        double[][] pairs = new double[CUES_MS.length][2];
        for (int i = 0; i < pairs.length; i++) {
            pairs[i][0] = audio.get(i).middleMs() - video.get(i).middleMs();
            pairs[i][1] = audio.get(i).uncertaintyMs() + video.get(i).uncertaintyMs();
        }
        return pairs;
    }
}
