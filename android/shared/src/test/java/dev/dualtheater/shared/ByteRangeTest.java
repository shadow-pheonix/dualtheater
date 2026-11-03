package dev.dualtheater.shared;

import org.junit.Test;
import static org.junit.Assert.*;

public class ByteRangeTest {
    @Test public void largeFilesAndOpenSuffixRanges() {
        long size = 100_000_000_000L;
        ByteRange full = ByteRange.parse(null, size);
        assertFalse(full.partial); assertEquals(size - 1, full.end);
        ByteRange tail = ByteRange.parse("bytes=99999999900-", size);
        assertEquals(size - 100, tail.start); assertEquals(size - 1, tail.end);
        ByteRange suffix = ByteRange.parse("bytes=-512", size);
        assertEquals(size - 512, suffix.start);
        assertEquals(99, ByteRange.parse("bytes=90-99999999999", 100).end);
    }
    @Test public void rejectsOverflowsEmptyMultiAndUnsatisfiableRanges() {
        for (String input : new String[]{"bytes=100-", "bytes=9-2", "bytes=-0", "bytes=-", "bytes=0-1,4-5",
                "bytes=999999999999999999999-", "Bytes=0-1", "bytes=+1-2"}) {
            try { ByteRange.parse(input, 100); fail(input); } catch (IllegalArgumentException expected) {}
        }
        try { ByteRange.parse(null, 0); fail(); } catch (IllegalArgumentException expected) {}
    }
}
