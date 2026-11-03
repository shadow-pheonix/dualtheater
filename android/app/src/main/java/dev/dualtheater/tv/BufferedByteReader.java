package dev.dualtheater.tv;

import java.io.IOException;

/** Coalesces extractor header reads without changing bytes or logical positions. */
final class BufferedByteReader {
    interface Source { int read(byte[] target, int offset, int length) throws IOException; }
    private final byte[] buffer;
    private int position, limit;
    private long remaining;

    BufferedByteReader(int capacity) {
        if (capacity <= 0) throw new IllegalArgumentException("Invalid read buffer capacity");
        buffer = new byte[capacity];
    }

    void reset(long length) { position = limit = 0; remaining = length; }

    int read(Source source, byte[] target, int offset, int length) throws IOException {
        if (offset < 0 || length < 0 || offset > target.length - length) throw new IndexOutOfBoundsException();
        if (length == 0) return 0;
        if (remaining == 0) return -1;
        if (position == limit) {
            int requested = length >= buffer.length ? length : buffer.length;
            if (remaining >= 0) requested = (int)Math.min(requested, remaining);
            if (length >= buffer.length) {
                int count = source.read(target, offset, requested);
                if (count > 0 && remaining >= 0) remaining -= count;
                else if (count < 0) remaining = 0;
                return count;
            }
            position = limit = 0;
            int count = source.read(buffer, 0, requested);
            if (count <= 0) { if (count < 0) remaining = 0; return count; }
            limit = count;
        }
        int count = Math.min(length, limit - position);
        System.arraycopy(buffer, position, target, offset, count);
        position += count;
        if (remaining >= 0) remaining -= count;
        return count;
    }
}
