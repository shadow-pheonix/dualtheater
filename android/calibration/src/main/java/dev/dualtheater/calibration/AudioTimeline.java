package dev.dualtheater.calibration;

import java.util.ArrayDeque;

/** Capture sample positions -> BOOTTIME. Callback arrival times never enter the fit. */
final class AudioTimeline {
    private final ArrayDeque<long[]> anchors = new ArrayDeque<>();
    private double slope = 1e9 / 48000, originNs, originFrame, errorNs;

    synchronized void add(long frame, long ns) {
        if (frame < 0 || ns <= 0) throw new IllegalStateException("Invalid microphone timestamp");
        long[] last = anchors.peekLast();
        if (last != null) {
            if (frame == last[0] && ns == last[1]) return;
            if (frame <= last[0] || ns <= last[1]) throw new IllegalStateException("Microphone timestamp discontinuity");
            double expected = (frame - last[0]) * (1e9 / 48000);
            if (Math.abs(ns - last[1] - expected) > 5_000_000)
                throw new IllegalStateException("Microphone timestamps are unstable");
        }
        anchors.addLast(new long[]{frame, ns});
        if (anchors.size() > 24) anchors.removeFirst();
        long[] first = anchors.peekFirst();
        double sx = 0, sy = 0;
        for (long[] a : anchors) { sx += a[0] - first[0]; sy += a[1] - first[1]; }
        double mx = sx / anchors.size(), my = sy / anchors.size(), xx = 0, xy = 0;
        for (long[] a : anchors) {
            double x = a[0] - first[0] - mx, y = a[1] - first[1] - my;
            xx += x * x; xy += x * y;
        }
        if (xx > 0) slope = xy / xx;
        if (Math.abs(slope / (1e9 / 48000) - 1) > .002)
            throw new IllegalStateException("Microphone capture clock rate is inconsistent");
        originFrame = first[0] + mx; originNs = first[1] + my;
        errorNs = 0;
        for (long[] a : anchors) errorNs = Math.max(errorNs, Math.abs(a[1] - (originNs + (a[0] - originFrame) * slope)));
    }

    synchronized boolean ready() { return anchors.size() >= 4; }
    synchronized long time(long frame) {
        if (!ready()) throw new IllegalStateException("Microphone clock is warming up");
        if (Math.abs(frame - anchors.peekLast()[0]) > 48000)
            throw new IllegalStateException("Microphone timestamp is too far from captured samples");
        return Math.round(originNs + (frame - originFrame) * slope);
    }
    synchronized long errorNs() { return Math.round(errorNs); }
}
