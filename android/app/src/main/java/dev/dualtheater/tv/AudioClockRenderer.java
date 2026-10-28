package dev.dualtheater.tv;

import androidx.media3.common.Format;
import androidx.media3.common.PlaybackParameters;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.*;
import androidx.media3.exoplayer.source.MediaSource;
import androidx.media3.exoplayer.source.SampleStream;

/** Retains the stock hardware renderer; contributes its one remote media clock. */
@UnstableApi
final class AudioClockRenderer extends ForwardingRenderer implements MediaClock {
    private final RemoteTimeline timeline;
    private long streamOffsetUs;
    private volatile boolean enabled;
    private volatile long lastReadNs;
    private volatile double rendererErrorMs;

    AudioClockRenderer(Renderer delegate, RemoteTimeline timeline) {
        super(delegate); this.timeline = timeline;
    }
    // Select only while stopped, before enabling a media item. No live handoff.
    void select(boolean value) {
        if (getState() == STATE_STARTED) throw new IllegalStateException("Stop before changing sync mode");
        enabled = value;
    }
    @Override public void handleMessage(int type, Object message) throws ExoPlaybackException {
        if (type == 10001) select((Boolean) message);
        else super.handleMessage(type, message);
    }
    @Override public MediaClock getMediaClock() { return enabled ? this : null; }
    @Override public long getPositionUs() {
        long now = System.nanoTime(); lastReadNs = now;
        return streamOffsetUs + timeline.read(now);
    }
    @Override public PlaybackParameters getPlaybackParameters() {
        return new PlaybackParameters((float) timeline.rate(System.nanoTime()));
    }
    @Override public void setPlaybackParameters(PlaybackParameters parameters) {
        // The remote audio rate is authoritative; this never controls Windows audio.
    }
    @Override public boolean hasSkippedSilenceSinceLastCall() { return false; }

    @Override public void enable(RendererConfiguration config, Format[] formats, SampleStream stream,
        long positionUs, boolean joining, boolean mayRenderStart, long startPositionUs,
        long offsetUs, MediaSource.MediaPeriodId periodId) throws ExoPlaybackException {
        streamOffsetUs = offsetUs;
        timeline.resetPosition(positionUs - offsetUs, System.nanoTime());
        super.enable(config, formats, stream, positionUs, joining, mayRenderStart,
                     startPositionUs, offsetUs, periodId);
    }
    @Override public void replaceStream(Format[] formats, SampleStream stream, long startPositionUs,
        long offsetUs, MediaSource.MediaPeriodId periodId) throws ExoPlaybackException {
        streamOffsetUs = offsetUs;
        super.replaceStream(formats, stream, startPositionUs, offsetUs, periodId);
    }
    @Override public void resetPosition(long positionUs, boolean keyframe) throws ExoPlaybackException {
        timeline.resetPosition(positionUs - streamOffsetUs, System.nanoTime());
        super.resetPosition(positionUs, keyframe);
    }
    @Override public void start() throws ExoPlaybackException {
        if (enabled) timeline.start(System.nanoTime());
        super.start();
    }
    @Override public void stop() {
        if (enabled) timeline.stop(System.nanoTime());
        super.stop();
    }
    @Override public void render(long positionUs, long elapsedUs) throws ExoPlaybackException {
        if (enabled && getState() == STATE_STARTED)
            rendererErrorMs = (positionUs - streamOffsetUs - timeline.read(System.nanoTime())) / 1000.0;
        super.render(positionUs, elapsedUs);
    }
    boolean recentlyRead(long now) { return lastReadNs > 0 && now - lastReadNs < 500_000_000L; }
    double rendererErrorMs() { return rendererErrorMs; }
}
