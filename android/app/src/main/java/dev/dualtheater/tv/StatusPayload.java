package dev.dualtheater.tv;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;

/** Keep optional metadata below the host frame limit without dropping timing. */
final class StatusPayload {
    static final int MAX_BYTES = 48 * 1024;
    private StatusPayload() {}
    static int bytes(JSONObject value) { return value.toString().getBytes(StandardCharsets.UTF_8).length; }
    static String clip(String text, int length) {
        return text == null ? "" : text.substring(0, Math.min(text.length(), length));
    }
    static JSONObject bound(JSONObject input) throws JSONException {
        JSONObject result = new JSONObject(input.toString());
        JSONArray source = result.optJSONArray("subtitle_tracks");
        JSONArray tracks = new JSONArray();
        if (source != null) {
            for (int pass = 0; pass < 2; pass++) {
                for (int i = 0; i < source.length() && tracks.length() < 128; i++) {
                    JSONObject row = source.optJSONObject(i);
                    if (row != null && row.optBoolean("selected") == (pass == 0)) tracks.put(row);
                }
            }
            result.put("subtitle_tracks", tracks);
            if (tracks.length() < source.length()) result.put("catalog_truncated", true);
        }
        result.put("error", clip(result.optString("error"), 500));
        result.put("decoder", clip(result.optString("decoder"), 128));
        if (bytes(result) > MAX_BYTES) { result.remove("decoders"); result.put("catalog_truncated", true); }
        while (bytes(result) > MAX_BYTES && tracks.length() > 1) {
            tracks.remove(tracks.length() - 1); result.put("catalog_truncated", true);
        }
        if (bytes(result) > MAX_BYTES) {
            // These format descriptions are optional; frame timing stays intact.
            JSONObject frame = result.optJSONObject("frame");
            if (frame != null) { frame.remove("color"); frame.remove("codecs"); }
            result.remove("display_hdr_types");
        }
        if (bytes(result) > MAX_BYTES) throw new JSONException("Critical status exceeds protocol budget");
        return result;
    }
}
