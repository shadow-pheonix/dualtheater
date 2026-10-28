package dev.dualtheater.tv;

/** Pure monotonic clock discipline. All positions are media us, times nanoTime ns. */
final class RemoteTimeline {
    private long epoch, sequence, lastNs, positionUs, anchorNs, anchorUs, receivedNs;
    private double rate = 1, uncertaintyMs, phaseMs;
    private boolean running, armed, observed;
    private String fault = "";

    synchronized void reset(long newEpoch, long position, long now) {
        epoch = newEpoch; sequence = 0; running = armed = observed = false;
        positionUs = position; lastNs = now; receivedNs = 0; rate = 1; fault = ""; phaseMs = 0;
    }

    synchronized void resetPosition(long position, long now) {
        positionUs = position; lastNs = now; running = false;
    }

    synchronized void arm(long newEpoch, long position, long audioNs, long videoNs,
                          long leadUs, long now) {
        reset(newEpoch, position, now);
        anchorNs = audioNs; anchorUs = position + leadUs; receivedNs = Math.max(videoNs, audioNs);
        armed = true;
    }

    synchronized void start(long now) { lastNs = now; running = true; }
    synchronized void stop(long now) { read(now); running = false; }

    synchronized boolean accept(long wantedEpoch, long seq, long timeNs, long mediaUs,
                                double newRate, double uncertainty, long now) {
        if (wantedEpoch != epoch || seq <= sequence || !armed || !Double.isFinite(newRate)
            || newRate < .998 || newRate > 1.002 || !Double.isFinite(uncertainty)
            || uncertainty < 0 || uncertainty > 20 || now - timeNs > 500_000_000L
            || timeNs - now > 20_000_000L) return false;
        read(now);
        long target = mediaUs + Math.round((now - timeNs) / 1000.0 * newRate);
        if (running && Math.abs(target - positionUs) > 150_000) {
            fault = "audio_phase_jump"; return false;
        }
        sequence = seq; anchorNs = timeNs; anchorUs = mediaUs;
        rate = newRate; uncertaintyMs = uncertainty; receivedNs = now; observed = true;
        phaseMs = (target - positionUs) / 1000.0;
        return true;
    }

    synchronized long read(long now) {
        if (!running || now <= lastNs) return positionUs;
        long dt = now - lastNs;
        // Holding an expired clock cannot let video continue indefinitely.
        if (!fault.isEmpty() || !armed || now - receivedNs > 750_000_000L) {
            fault = fault.isEmpty() ? "audio_anchor_expired" : fault;
            lastNs = now; return positionUs;
        }
        double desired = anchorUs + (now - anchorNs) / 1000.0 * rate;
        double atOldTime = anchorUs + (lastNs - anchorNs) / 1000.0 * rate;
        double correction = Math.max(-.004, Math.min(.004, (atOldTime - positionUs) / 2_000_000));
        double speed = Math.max(.995, Math.min(1.005, rate + correction));
        positionUs += Math.max(0, Math.round(dt / 1000.0 * speed));
        lastNs = now; phaseMs = (desired - positionUs) / 1000.0;
        return positionUs;
    }

    synchronized double rate(long now) {
        if (!running) return 1;
        double target = anchorUs + (now - anchorNs) / 1000.0 * rate;
        return Math.max(.995, Math.min(1.005, rate + Math.max(-.004, Math.min(.004,
            (target - positionUs) / 2_000_000))));
    }
    synchronized String state(long now) {
        if (!fault.isEmpty()) return fault;
        if (!running) return "paused";
        if (!observed) return "acquiring";
        if (now - receivedNs > 750_000_000L) return "audio_anchor_expired";
        if (now - receivedNs > 250_000_000L) return "holdover";
        return Math.abs(phaseMs) <= Math.max(8, uncertaintyMs) ? "locked" : "slewing";
    }
    synchronized double phaseMs() { return phaseMs; }
    synchronized double uncertaintyMs(long now) {
        return observed ? uncertaintyMs + Math.max(0, now - receivedNs) / 1e6 * .001 : 1000;
    }
}
