package dev.dualtheater.tv;

import android.media.MediaCodec;
import android.os.Handler;
import android.os.Looper;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.exoplayer.mediacodec.MediaCodecAdapter;
import java.io.IOException;
import java.lang.reflect.*;
import java.util.HashMap;

/** Delegates the full pinned adapter API; multiplexes optional rendered feedback. */
@UnstableApi
final class ObservingCodecFactory implements MediaCodecAdapter.Factory {
    private final MediaCodecAdapter.Factory factory;
    private final FrameObservations observations;
    ObservingCodecFactory(MediaCodecAdapter.Factory factory, FrameObservations observations) {
        this.factory = factory; this.observations = observations;
    }
    @Override public MediaCodecAdapter createAdapter(MediaCodecAdapter.Configuration config) throws IOException {
        MediaCodecAdapter delegate = factory.createAdapter(config);
        final long codecGeneration = observations.beginCodec();
        HashMap<Integer, Long> outputs = new HashMap<>();
        final MediaCodecAdapter.OnFrameRenderedListener[] original = new MediaCodecAdapter.OnFrameRenderedListener[1];
        final MediaCodecAdapter[] proxy = new MediaCodecAdapter[1];
        MediaCodecAdapter.OnFrameRenderedListener observer = (codec, pts, time) -> {
            observations.rendered(codecGeneration, pts, time, System.nanoTime());
            if (original[0] != null) original[0].onFrameRendered(proxy[0], pts, time);
        };
        proxy[0] = (MediaCodecAdapter) Proxy.newProxyInstance(MediaCodecAdapter.class.getClassLoader(),
            new Class<?>[]{MediaCodecAdapter.class}, (instance, method, args) -> {
                String name = method.getName();
                if (name.equals("setOnFrameRenderedListener")) {
                    original[0] = (MediaCodecAdapter.OnFrameRenderedListener) args[0];
                    delegate.setOnFrameRenderedListener(observer, (Handler) args[1]); return null;
                }
                if (name.equals("releaseOutputBuffer")) {
                    Long pts = outputs.remove((Integer) args[0]);
                    if (pts != null && args[1] instanceof Long) observations.submit(codecGeneration, pts, (Long) args[1]);
                }
                if (name.equals("flush")) { outputs.clear(); observations.clearCodec(codecGeneration); }
                if (name.equals("release")) { outputs.clear(); observations.retireCodec(codecGeneration); }
                try {
                    Object result = method.invoke(delegate, args);
                    if (name.equals("dequeueOutputBufferIndex") && (Integer) result >= 0) {
                        outputs.put((Integer) result, ((MediaCodec.BufferInfo) args[0]).presentationTimeUs);
                    }
                    return result;
                } catch (InvocationTargetException e) { throw e.getCause(); }
            });
        try { delegate.setOnFrameRenderedListener(observer, new Handler(Looper.myLooper())); }
        catch (RuntimeException ignored) { /* Observation is optional; scheduling never depends on it. */ }
        return proxy[0];
    }
}
