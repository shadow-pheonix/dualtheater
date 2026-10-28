package dev.dualtheater.calibration;

/** Detect the reference 1 kHz bursts in 5 ms PCM windows; retain source sample indices. */
final class ToneDetector {
    private static final double[] COS = new double[240], SIN = new double[240];
    static {
        for (int i = 0; i < COS.length; i++) {
            COS[i] = Math.cos(2 * Math.PI * 1000 * i / 48000);
            SIN[i] = Math.sin(2 * Math.PI * 1000 * i / 48000);
        }
    }
    interface Listener { void onTone(long firstFrame, long lastFrame); }
    private final Listener listener;
    private final short[] window = new short[240];
    private int used, positive, negative;
    private long frame, candidate;
    private boolean emitted;

    ToneDetector(Listener listener) { this.listener = listener; }

    void accept(short[] data, int count) {
        for (int i = 0; i < count; i++) {
            window[used++] = data[i]; frame++;
            if (used != window.length) continue;
            double re = 0, im = 0, power = 0;
            for (int j = 0; j < window.length; j++) {
                double v = window[j] / 32768.0;
                power += v * v; re += v * COS[j]; im += v * SIN[j];
            }
            double fraction = power > 0 ? 2 * (re * re + im * im) / (window.length * power) : 0;
            boolean tone = power / window.length > .0000001 && fraction > .65;
            if (tone) {
                negative = 0;
                if (positive++ == 0) candidate = frame - window.length;
                if (positive >= 3 && !emitted) {
                    // The first partial window may precede the first accepted one.
                    listener.onTone(Math.max(0, candidate - 240), candidate + 240);
                    emitted = true;
                }
            } else {
                positive = 0;
                if (++negative >= 3) emitted = false;
            }
            used = 0;
        }
    }
}
