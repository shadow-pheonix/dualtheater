package dev.dualtheater.tv;

import java.util.LinkedHashMap;

/** Bounded correlation of codec submission and rendered events; no callback-time inference. */
final class FrameObservations {
    static final class Sample {
        final long epoch, sequence, mediaUs, releaseNs, renderedNs, receivedNs;
        Sample(long epoch, long sequence, long mediaUs, long releaseNs, long renderedNs, long receivedNs) {
            this.epoch = epoch; this.sequence = sequence; this.mediaUs = mediaUs;
            this.releaseNs = releaseNs; this.renderedNs = renderedNs; this.receivedNs = receivedNs;
        }
    }
    private final LinkedHashMap<Long, Sample> submitted = new LinkedHashMap<>();
    private Sample scheduled, rendered;
    private long codecGeneration;
    synchronized long beginCodec() { clear(); return ++codecGeneration; }
    synchronized void clearCodec(long codec) { if (codec == codecGeneration) clear(); }
    synchronized void retireCodec(long codec) {
        if (codec == codecGeneration) { clear(); ++codecGeneration; }
    }
    synchronized void clear() { submitted.clear(); scheduled = rendered = null; }
    synchronized void schedule(long epoch, long sequence, long mediaUs, long releaseNs) {
        scheduled = new Sample(epoch, sequence, mediaUs, releaseNs, 0, 0);
    }
    synchronized void submit(long codec, long rawPts, long releaseNs) {
        if (codec != codecGeneration || scheduled == null || scheduled.releaseNs != releaseNs) return;
        submitted.put(rawPts, scheduled);
        if (submitted.size() > 64) submitted.remove(submitted.keySet().iterator().next());
    }
    synchronized void rendered(long codec, long rawPts, long eventNs, long receivedNs) {
        if (codec != codecGeneration) return;
        Sample s = submitted.remove(rawPts);
        if (s == null || eventNs < s.releaseNs - 1_000_000 || eventNs - s.releaseNs > 500_000_000
            || eventNs > receivedNs + 1_000_000 || receivedNs - eventNs > 2_000_000_000L
            || rendered != null && s.sequence <= rendered.sequence) return;
        rendered = new Sample(s.epoch, s.sequence, s.mediaUs, s.releaseNs, eventNs, receivedNs);
    }
    synchronized Sample latest() { return rendered; }
}
