package dev.dualtheater.tv;

/** Playback epochs belong to one authenticated connection, not the Activity lifetime. */
final class PlaybackSession {
    private volatile long epoch;
    private volatile long generation;

    long epoch() { return epoch; }
    long generation() { return generation; }

    void reset() {
        generation++;
        epoch = 0;
    }

    boolean accept(long incoming) {
        if (incoming < epoch || incoming < 0) throw new IllegalStateException("Stale command epoch");
        if (incoming == epoch) return false;
        generation++;
        epoch = incoming;
        return true;
    }

    boolean matches(long expectedGeneration) { return generation == expectedGeneration; }
}
