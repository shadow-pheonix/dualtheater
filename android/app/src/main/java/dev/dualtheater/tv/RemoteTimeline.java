package dev.dualtheater.tv;

/** Pure monotonic clock discipline. All positions are media us, times nanoTime ns. */
final class RemoteTimeline {
    // Match the host's source-rate / clock-rate envelope and summed confidence.
    private static final double MIN_ANCHOR_RATE = .999 / 1.001, MAX_ANCHOR_RATE = 1.001 / .999;
    private static final double MAX_UNCERTAINTY_MS = 22, HOLDOVER_ERROR_PER_MS = .004;
    private static final long MAX_HOLDOVER_NS = 2_000_000_000L;
    private long epoch, sequence, lastNs, positionUs, anchorNs, anchorUs, receivedNs;
    private double rate = 1, uncertaintyMs, phaseMs, maxDispatchDelayMs;
    private boolean running, armed, observed;
    private String fault = "";

    synchronized void resetMillis(long newEpoch, long positionMs, long now) {
        reset(newEpoch, Math.multiplyExact(positionMs, 1000L), now);
    }

    synchronized void reset(long newEpoch, long position, long now) {
        epoch = newEpoch; sequence = 0; running = armed = observed = false;
        positionUs = position; lastNs = now; receivedNs = 0; rate = 1; fault = ""; phaseMs = 0;
        maxDispatchDelayMs = 0;
    }

    synchronized void resetPosition(long position, long now) {
        positionUs = position; lastNs = now; running = false;
    }

    synchronized void rendererResetPosition(long position, long now) {
        // A codec rebuffer/re-enable cannot reposition an external audio master.
        if (running) read(now);
        else resetPosition(position, now);
    }

    synchronized void arm(long newEpoch, long position, long audioNs, long videoNs,
                          long leadUs, long now) {
        reset(newEpoch, position, now);
        anchorNs = audioNs; anchorUs = position + leadUs; receivedNs = Math.max(videoNs, audioNs);
        armed = true;
    }

    synchronized void start(long now) {
        if (running) { read(now); return; }
        lastNs = now; running = true;
    }
    synchronized void stop(long now) { read(now); running = false; }

    synchronized boolean accept(long wantedEpoch, long seq, long timeNs, long mediaUs,
                                double newRate, double uncertainty, long now) {
        // Receipt is timestamped on the network thread before parsing and taking
        // this lock. The renderer may have advanced lastNs in the meantime.
        // Compare both positions at the same time; never rewind the clock or
        // treat a delayed thread's old receipt time as a new phase jump.
        long evaluationNs = Math.max(now, lastNs);
        if (wantedEpoch != epoch || seq <= sequence || !armed || !Double.isFinite(newRate)
            || newRate < MIN_ANCHOR_RATE || newRate > MAX_ANCHOR_RATE || !Double.isFinite(uncertainty)
            || uncertainty < 0 || uncertainty > MAX_UNCERTAINTY_MS || evaluationNs - timeNs > 500_000_000L
            || timeNs - now > 20_000_000L) return false;
        maxDispatchDelayMs = Math.max(maxDispatchDelayMs, (evaluationNs - now) / 1_000_000.0);
        read(evaluationNs);
        long target = mediaUs + Math.round((evaluationNs - timeNs) / 1000.0 * newRate);
        phaseMs = (target - positionUs) / 1000.0;
        if (running && Math.abs(target - positionUs) > 150_000) {
            fault = "audio_phase_jump"; return false;
        }
        sequence = seq; anchorNs = timeNs; anchorUs = mediaUs;
        rate = newRate; uncertaintyMs = uncertainty; receivedNs = now; observed = true;
        return true;
    }

    synchronized long read(long now) {
        if (!running || now <= lastNs) return positionUs;
        long dt = now - lastNs;
        // Holding an expired clock cannot let video continue indefinitely.
        if (!fault.isEmpty() || !armed || expired(now)) {
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
        if (expired(now)) return "audio_anchor_expired";
        if (now - receivedNs > 250_000_000L) return "holdover";
        return Math.abs(phaseMs) <= Math.max(8, uncertaintyMs) ? "locked" : "slewing";
    }
    synchronized double phaseMs() { return phaseMs; }
    synchronized double maxDispatchDelayMs() { return maxDispatchDelayMs; }
    synchronized double uncertaintyMs(long now) {
        return observed ? uncertaintyMs + Math.max(0, now - receivedNs) / 1e6 * HOLDOVER_ERROR_PER_MS : 1000;
    }
    synchronized double anchorAgeMs(long now) { return receivedNs == 0 ? 0 : Math.max(0, now - receivedNs) / 1e6; }
    private boolean expired(long now) {
        return now - receivedNs > MAX_HOLDOVER_NS || observed && uncertaintyMs(now) > MAX_UNCERTAINTY_MS;
    }
}
