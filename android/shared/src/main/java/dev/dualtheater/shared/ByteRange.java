package dev.dualtheater.shared;

/** Single byte ranges only. End is inclusive; invalid and unsatisfiable ranges throw. */
public final class ByteRange {
    public final long start, end;
    public final boolean partial;
    private ByteRange(long start, long end, boolean partial) {
        this.start = start; this.end = end; this.partial = partial;
    }
    public static ByteRange parse(String header, long size) {
        if (size <= 0) throw new IllegalArgumentException("Empty file");
        if (header == null) return new ByteRange(0, size - 1, false);
        if (!header.matches("bytes=[0-9]*-[0-9]*")) throw new IllegalArgumentException("Single byte range required");
        String[] parts = header.substring(6).split("-", -1);
        try {
            if (parts[0].isEmpty()) {
                long count = Long.parseLong(parts[1]);
                if (count <= 0) throw new IllegalArgumentException("Invalid suffix range");
                return new ByteRange(Math.max(0, size - count), size - 1, true);
            }
            long first = Long.parseLong(parts[0]);
            long last = parts[1].isEmpty() ? size - 1 : Long.parseLong(parts[1]);
            if (first >= size || last < first) throw new IllegalArgumentException("Unsatisfiable range");
            return new ByteRange(first, Math.min(last, size - 1), true);
        } catch (NumberFormatException error) { throw new IllegalArgumentException("Invalid range"); }
    }
}
