package dev.dualtheater.tv;

/** Pure bounds for the disk read-ahead window. */
final class ReadAheadWindow {
    static final long READ_HEAD_SIGNAL_BYTES = 256L * 1024;
    static final long MAX_CHUNK_BYTES = 8L * 1024 * 1024;
    static final long MAX_LOOKAHEAD_BYTES = 128L * 1024 * 1024;
    static final long FAR_SEEK_BYTES = 4L * 1024 * 1024;

    private ReadAheadWindow() {}

    static long lookaheadBytes(long diskBudgetBytes) {
        if (diskBudgetBytes <= 0) return 0;
        return Math.min(MAX_LOOKAHEAD_BYTES, diskBudgetBytes / 2);
    }

    static boolean shouldSignalReadHead(long bytesRead, long lastSignalBytes) {
        return bytesRead >= READ_HEAD_SIGNAL_BYTES
            && (lastSignalBytes < 0 || bytesRead - lastSignalBytes >= READ_HEAD_SIGNAL_BYTES);
    }

    static boolean isFarSeek(long oldReadHead, long newReadHead) {
        return oldReadHead >= 0 && Math.abs(newReadHead - oldReadHead) >= FAR_SEEK_BYTES;
    }

    static long targetEnd(long readHead, long totalLength, long lookaheadBytes) {
        if (readHead < 0 || lookaheadBytes <= 0) return Math.max(0, readHead);
        long sum = readHead > Long.MAX_VALUE - lookaheadBytes ? Long.MAX_VALUE : readHead + lookaheadBytes;
        return totalLength >= 0 ? Math.min(sum, totalLength) : sum;
    }

    static long nextChunkLength(long position, long end) {
        if (position < 0 || end <= position) return 0;
        return Math.min(MAX_CHUNK_BYTES, end - position);
    }

    static long firstMissingPosition(long head, long end, long cachedLength) {
        if (head < 0 || end <= head) return head;
        return head + Math.max(0, Math.min(end - head, cachedLength));
    }

    static boolean needsRefill(long ahead, long window, boolean filling) {
        return window > 0 && (filling || ahead <= window - window / 4);
    }
}
