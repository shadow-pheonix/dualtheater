package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;
import java.lang.reflect.Proxy;
import java.util.concurrent.atomic.AtomicInteger;
import androidx.media3.exoplayer.*;

public class AudioClockRendererTest {
    @Test public void rendererOffsetsPauseResetAndExplicitSelection() throws Exception {
        AtomicInteger state = new AtomicInteger(Renderer.STATE_DISABLED);
        Renderer delegate = (Renderer) Proxy.newProxyInstance(Renderer.class.getClassLoader(),
            new Class<?>[]{Renderer.class}, (proxy, method, args) -> {
                switch (method.getName()) {
                    case "getState": return state.get();
                    case "enable": state.set(Renderer.STATE_ENABLED); return null;
                    case "start": state.set(Renderer.STATE_STARTED); return null;
                    case "stop": state.set(Renderer.STATE_ENABLED); return null;
                    default: return null;
                }
            });
        RemoteTimeline timeline = new RemoteTimeline();
        AudioClockRenderer r = new AudioClockRenderer(delegate, timeline);
        assertNull(r.getMediaClock()); r.select(true); assertSame(r, r.getMediaClock());
        long offset = 1_000_000_000_000L;
        r.enable(null, null, null, offset + 5_000_000, false, true, offset, offset, null);
        assertEquals(offset + 5_000_000, r.getPositionUs());
        r.resetPosition(offset + 90_000_000, true);
        assertEquals(offset + 90_000_000, r.getPositionUs());
        r.start();
        try { r.select(false); fail("Live algorithm change must fail"); }
        catch (IllegalStateException expected) { }
        r.stop(); r.select(false); assertNull(r.getMediaClock());
    }
}
