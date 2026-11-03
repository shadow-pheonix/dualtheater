package dev.dualtheater.tv;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.Random;
import org.junit.Test;
import static org.junit.Assert.*;

public class BufferedByteReaderTest {
    @Test public void tinyContainerReadsKeepEveryByteAndAmortizePhysicalReads() throws Exception {
        byte[] original = new byte[256 * 1024 + 37]; new Random(42).nextBytes(original);
        ByteArrayInputStream input = new ByteArrayInputStream(original);
        int[] physical = {0};
        BufferedByteReader.Source source = (b, o, n) -> { physical[0]++; return input.read(b, o, n); };
        BufferedByteReader reader = new BufferedByteReader(64 * 1024); reader.reset(original.length);
        ByteArrayOutputStream result = new ByteArrayOutputStream(); byte[] scratch = new byte[32];
        int logical = 0;
        while (true) {
            int count = reader.read(source, scratch, 3, 1 + logical % 10);
            if (count < 0) break;
            result.write(scratch, 3, count); logical++;
        }
        assertArrayEquals(original, result.toByteArray());
        assertEquals(5, physical[0]);
        assertTrue(logical > physical[0] * 1000);
    }

    @Test public void reopenAfterSeekDropsUnreadPrefetchAndHonorsTheNewRange() throws Exception {
        BufferedByteReader reader = new BufferedByteReader(16);
        byte[] scratch = new byte[32];
        ByteArrayInputStream first = new ByteArrayInputStream(new byte[]{1, 2, 3, 4, 5, 6});
        reader.reset(6);
        assertEquals(2, reader.read(first::read, scratch, 0, 2));
        reader.reset(0); // close
        ByteArrayInputStream second = new ByteArrayInputStream(new byte[]{90, 91, 92, 93});
        reader.reset(3);
        assertEquals(3, reader.read(second::read, scratch, 1, 12));
        assertArrayEquals(new byte[]{90, 91, 92}, java.util.Arrays.copyOfRange(scratch, 1, 4));
        assertEquals(-1, reader.read(second::read, scratch, 0, 1));
        assertEquals(1, second.available());
    }

    @Test public void shortReadsAndUnknownLengthDoNotBecomePrematureEof() throws Exception {
        byte[] original = new byte[71]; new Random(4).nextBytes(original);
        ByteArrayInputStream input = new ByteArrayInputStream(original);
        BufferedByteReader.Source source = (b, o, n) -> input.read(b, o, Math.min(n, 3));
        BufferedByteReader reader = new BufferedByteReader(16); reader.reset(-1);
        ByteArrayOutputStream result = new ByteArrayOutputStream(); byte[] scratch = new byte[41];
        int count;
        while ((count = reader.read(source, scratch, 0, scratch.length)) >= 0) result.write(scratch, 0, count);
        assertArrayEquals(original, result.toByteArray());
        assertEquals(0, reader.read(source, scratch, scratch.length, 0));
        assertEquals(-1, reader.read(source, scratch, 0, 1));
    }

    @Test public void largeReadsBypassTheCopyButCannotCrossTheDeclaredRange() throws Exception {
        byte[] original = new byte[100]; new Random(8).nextBytes(original);
        ByteArrayInputStream input = new ByteArrayInputStream(original);
        BufferedByteReader reader = new BufferedByteReader(16); reader.reset(37);
        byte[] result = new byte[50];
        assertEquals(37, reader.read(input::read, result, 0, result.length));
        assertArrayEquals(java.util.Arrays.copyOf(original, 37), java.util.Arrays.copyOf(result, 37));
        assertEquals(-1, reader.read(input::read, result, 0, result.length));
        assertEquals(63, input.available());
    }
}
