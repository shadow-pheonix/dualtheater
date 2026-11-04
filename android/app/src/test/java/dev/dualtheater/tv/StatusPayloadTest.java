package dev.dualtheater.tv;

import org.junit.Test;
import org.json.JSONArray;
import org.json.JSONObject;
import static org.junit.Assert.*;

public class StatusPayloadTest {
    @Test public void largeCatalogKeepsTimingAndSelectedTrackWithinByteBudget() throws Exception {
        JSONArray tracks = new JSONArray();
        for (int i = 0; i < 300; i++) tracks.put(new JSONObject().put("id", "0:"+i)
            .put("label", "字幕".repeat(200)).put("selected", i == 299));
        JSONObject frame = new JSONObject().put("epoch", 7).put("sequence", 123)
            .put("release_ns", 100_000_000_000L).put("position_ms", 8000);
        JSONObject input = new JSONObject().put("op", "status").put("epoch", 7).put("frame", frame)
            .put("subtitle_tracks", tracks).put("decoders", new JSONArray().put("x".repeat(60000)));
        JSONObject output = StatusPayload.bound(input);
        assertTrue(StatusPayload.bytes(output) <= StatusPayload.MAX_BYTES);
        assertEquals(frame.toString(), output.getJSONObject("frame").toString());
        assertEquals("0:299", output.getJSONArray("subtitle_tracks").getJSONObject(0).getString("id"));
        assertTrue(output.getBoolean("catalog_truncated")); assertEquals(300, tracks.length());
    }

    @Test public void healthyStatusRetainsMetadataAndLongPositions() throws Exception {
        JSONObject input = new JSONObject().put("op", "status").put("position_ms", 14_400_000L)
            .put("decoders", new JSONArray().put("hardware"));
        JSONObject output = StatusPayload.bound(input);
        assertEquals(14_400_000L, output.getLong("position_ms"));
        assertEquals("hardware", output.getJSONArray("decoders").getString(0));
    }
}
