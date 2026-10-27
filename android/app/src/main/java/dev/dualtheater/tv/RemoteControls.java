package dev.dualtheater.tv;

import java.util.Locale;

/** UI-only scrub preview. This class never seeks or starts a media player. */
final class RemoteControls {
    private long previewMs = -1, sequence = 0, pending = -1;

    long nudge(long currentMs, long durationMs, long deltaMs) {
        long base = previewMs >= 0 ? previewMs : currentMs;
        previewMs = Math.max(0, Math.min(Math.max(0, durationMs - 100), base + deltaMs));
        return previewMs;
    }
    boolean hasPreview() { return previewMs >= 0; }
    long previewMs() { return previewMs; }
    void clearPreview() { previewMs = -1; }
    boolean isPending() { return pending >= 0; }
    long begin() {
        if (isPending()) return -1;
        pending = ++sequence;
        return pending;
    }
    boolean complete(long request) {
        if (pending < 0 || request != pending) return false;
        pending = -1;
        return true;
    }
    void reset() { previewMs = -1; pending = -1; }
    static String time(long ms) {
        long seconds = Math.max(0, ms) / 1000;
        return seconds >= 3600
            ? String.format(Locale.ROOT, "%d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
            : String.format(Locale.ROOT, "%02d:%02d", seconds / 60, seconds % 60);
    }
}
