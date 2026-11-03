package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;

public class ReadAheadWindowTest {
    @Test public void smallReadHeadAdvancesAreBatchedButARealHoleRefillsImmediately() {
        long mib = 1024 * 1024L, window = 128 * mib, ahead = window;
        int requests = 0;
        // 128 MiB of playback in 256 KiB extractor signals: four grouped
        // 32 MiB refills instead of 512 small HTTP/file transactions.
        for (int i = 0; i < 512; i++) {
            ahead -= 256 * 1024;
            if (ReadAheadWindow.needsRefill(ahead, window, false)) {
                while (ahead < window) {
                    assertTrue(ReadAheadWindow.needsRefill(ahead, window, true));
                    long chunk = ReadAheadWindow.nextChunkLength(ahead, window);
                    assertEquals(8 * mib, chunk);
                    ahead += chunk; requests++;
                }
            }
        }
        assertEquals(16, requests);
        assertEquals(window, ahead);
        assertTrue(ReadAheadWindow.needsRefill(0, window, false));
        assertFalse(ReadAheadWindow.needsRefill(0, 0, false));
    }
    @Test public void evictionRepairsTheFirstHoleInsteadOfTrustingAnOldDownloadCursor() {
        // Simulated committed bytes, then an LRU hole behind the writer's old
        // high-water mark. The reader must get a contiguous window, not a sum
        // of cached islands or a stale completed-download position.
        boolean[] cached = new boolean[256];
        java.util.Arrays.fill(cached, true);
        for (int head = 0; head < 200; head++) {
            int end = Math.min(cached.length, head + 32);
            cached[head + 3] = false;
            cached[head + 11] = false;
            int repairs = 0;
            while (true) {
                int prefix = head;
                while (prefix < end && cached[prefix]) prefix++;
                long signedCoverage = prefix == head ? -(end - head) : prefix - head;
                int next = (int)ReadAheadWindow.firstMissingPosition(head, end, signedCoverage);
                if (next == end) break;
                assertFalse(cached[next]);
                for (int i = next; i < Math.min(end, next + 8); i++) cached[i] = true;
                assertTrue(++repairs <= 4);
            }
            for (int i = head; i < end; i++) assertTrue(cached[i]);
        }
    }
    @Test public void diskWindowIsBoundedIndependentlyOfHeapBudget() {
        assertEquals(0, ReadAheadWindow.lookaheadBytes(0));
        assertEquals(512 * 1024, ReadAheadWindow.lookaheadBytes(1024 * 1024));
        assertEquals(128L * 1024 * 1024, ReadAheadWindow.lookaheadBytes(512L * 1024 * 1024));
        assertEquals(ReadAheadWindow.MAX_LOOKAHEAD_BYTES,
            ReadAheadWindow.lookaheadBytes(Long.MAX_VALUE));
    }

    @Test public void signalsAreThrottledAndIgnoreSmallReads() {
        long step = ReadAheadWindow.READ_HEAD_SIGNAL_BYTES;
        assertFalse(ReadAheadWindow.shouldSignalReadHead(step - 1, -1));
        assertTrue(ReadAheadWindow.shouldSignalReadHead(step, -1));
        assertFalse(ReadAheadWindow.shouldSignalReadHead(step * 2 - 1, step));
        assertTrue(ReadAheadWindow.shouldSignalReadHead(step * 2, step));
    }

    @Test public void targetAndChunksStopAtEndAndAvoidOverflow() {
        long chunk = ReadAheadWindow.MAX_CHUNK_BYTES;
        assertEquals(0, ReadAheadWindow.targetEnd(0, 0, 128 * 1024 * 1024));
        assertEquals(22, ReadAheadWindow.targetEnd(0, 22, 128 * 1024 * 1024));
        assertEquals(2, ReadAheadWindow.nextChunkLength(20, 22));
        assertEquals(5_000_000, ReadAheadWindow.targetEnd(4_000_000, 5_000_000, 128 * 1024 * 1024));
        assertEquals(Long.MAX_VALUE,
            ReadAheadWindow.targetEnd(Long.MAX_VALUE - 10, -1, 128));
        assertEquals(chunk, ReadAheadWindow.nextChunkLength(0, chunk + 100));
        assertEquals(100, ReadAheadWindow.nextChunkLength(chunk, chunk + 100));
        assertEquals(0, ReadAheadWindow.nextChunkLength(10, 10));
    }

    @Test public void onlyLargeHeadJumpsCancelTheCurrentWindow() {
        long far = ReadAheadWindow.FAR_SEEK_BYTES;
        assertFalse(ReadAheadWindow.isFarSeek(-1, far * 4));
        assertFalse(ReadAheadWindow.isFarSeek(100, 100 + far - 1));
        assertTrue(ReadAheadWindow.isFarSeek(100, 100 + far));
        assertTrue(ReadAheadWindow.isFarSeek(far * 2, far));
    }
}
