package dev.dualtheater.calibration;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.View;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Foreground remote controls; camera/microphone are owned solely by calibration. */
final class PhoneControls {
    interface Commands {
        long request(String action, JSONObject values);
        void chooseStorage();
        void stopSharing();
    }
    static final int BACKGROUND = 0xff101827, CARD = 0xff1b293d, TEXT = 0xfff4f7fb,
        MUTED = 0xffb8c6d9, ACCENT = 0xff45d7c8;
    private final Activity activity;
    private final Commands commands;
    private final List<View> playbackControls = new ArrayList<>();
    private final List<Button> libraryControls = new ArrayList<>();
    private final Map<String, Button> providerButtons = new HashMap<>();
    private final Set<String> availableProviders = new HashSet<>();
    private LinearLayout library, listing;
    private TextView nowPlaying, audio, libraryStatus;
    private SeekBar timeline;
    private JSONObject state = new JSONObject();
    private boolean connected, blocked, dragging;
    private String provider = "windows", entry = "", parent = "";
    private long browseRequest = -1;
    private int cursor;

    PhoneControls(Activity activity, Commands commands) { this.activity = activity; this.commands = commands; }
    private int dp(int n) { return Math.round(n * activity.getResources().getDisplayMetrics().density); }
    static void card(View view) {
        GradientDrawable background = new GradientDrawable(); background.setColor(CARD); background.setCornerRadius(14);
        view.setBackground(background);
    }
    private LinearLayout panel() {
        LinearLayout value = new LinearLayout(activity); value.setOrientation(LinearLayout.VERTICAL);
        value.setPadding(dp(18), dp(12), dp(18), dp(18)); value.setBackgroundColor(BACKGROUND); return value;
    }
    private ScrollView scroll(LinearLayout panel) { ScrollView scroll = new ScrollView(activity); scroll.addView(panel); return scroll; }
    private TextView text(LinearLayout panel, String value, int size) {
        TextView text = new TextView(activity); text.setText(value); text.setTextSize(size); text.setTextColor(TEXT);
        text.setPadding(0, dp(6), 0, dp(6)); panel.addView(text); return text;
    }
    private Button button(LinearLayout panel, String label, Runnable action) {
        Button button = new Button(activity); button.setText(label); button.setTextColor(TEXT); button.setAllCaps(false);
        card(button); button.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(54)); params.setMargins(0, dp(4), 0, dp(4));
        panel.addView(button, params); return button;
    }
    private Button control(LinearLayout parent, String label, Runnable action) {
        Button button = button(parent, label, action); playbackControls.add(button); return button;
    }

    View playerView() {
        LinearLayout panel = panel(); text(panel, "Player", 24);
        nowPlaying = text(panel, "Connect to Windows and choose a movie from Library or the TV.", 17);
        audio = text(panel, "Audio and subtitles are shared with the Windows and TV controls.", 14);
        timeline = new SeekBar(activity); panel.addView(timeline); playbackControls.add(timeline);
        timeline.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar bar, int value, boolean user) {}
            public void onStartTrackingTouch(SeekBar bar) { dragging = true; }
            public void onStopTrackingTouch(SeekBar bar) {
                dragging = false;
                request("seek", object("seconds", bar.getProgress() / 1000.0), state);
            }
        });
        control(panel, "Play / pause", () -> request(state.optString("state").equals("playing") ? "pause" : "play", null, state));
        control(panel, "Back 10 seconds", () -> seek(-10));
        control(panel, "Forward 10 seconds", () -> seek(10));
        control(panel, "Audio track", () -> tracks(false));
        control(panel, "Subtitles", () -> tracks(true));
        control(panel, "Resynchronize", () -> request("resync", null, state));
        text(panel, "For better physical lip-sync, use Calibrate first. Gradual clock drift is corrected on the video side; the saved calibration remains applied. If timing is lost, wait for reconnection and press Play. Reload the movie after a full TV disconnect.", 14).setTextColor(MUTED);
        return scroll(panel);
    }

    View libraryView() {
        library = panel(); text(library, "Library", 24);
        text(library, "Browse folders shared by Windows, or an Android device while its app stays open. Only the folder you grant is shared.", 14).setTextColor(MUTED);
        button(library, "Choose phone folder to share", commands::chooseStorage);
        button(library, "Stop sharing phone folder", commands::stopSharing);
        libraryStatus = text(library, "Start Windows and connect to browse movies.", 15);
        providerButtons.put("windows", button(library, "Windows folders", () -> browse("windows", "", 0)));
        providerButtons.put("phone", button(library, "Phone storage", () -> browse("phone", "", 0)));
        providerButtons.put("tv", button(library, "TV storage", () -> browse("tv", "", 0)));
        libraryControls.add(button(library, "Parent folder", () -> browse(provider, parent, 0)));
        libraryControls.add(button(library, "Refresh", () -> browse(provider, entry, cursor)));
        listing = new LinearLayout(activity); listing.setOrientation(LinearLayout.VERTICAL); library.addView(listing);
        return scroll(library);
    }

    View helpView() {
        LinearLayout panel = panel(); text(panel, "Setup & help", 24);
        text(panel, "1  Start Windows", 19);
        text(panel, "Connect the laptop/PC HDMI output to your receiver's HDMI IN, select the correct Windows HDMI endpoint and start the TV connection. Keep all devices on the same trusted network.", 15);
        text(panel, "2  Pair the TV and phone", 19);
        text(panel, "Select the computer in Connect and enter the Windows six-digit code once. If discovery finds nothing, check guest-network isolation, VPN and private-network firewall permissions; Advanced connection accepts the address shown on Windows.", 15);
        text(panel, "3  Calibrate — recommended", 19);
        text(panel, "Raise the soundbar/receiver volume until the beeps are clearly audible at the phone. Keep the phone steady at the listening seat, with the TV flash area centered. Measure, review, Apply, then verify and reload your movie.", 15);
        text(panel, "Storage and playback", 19);
        text(panel, "On Windows, share a movie folder in Library. To share Android media, choose a local storage folder in the system picker. Keep the sharing app open; leaving or disconnecting it stops access. A cloud provider with no known size or random access cannot play a remux. A phone hotspot may limit high-bitrate transfers.", 15);
        text(panel, "No sound or unsupported track", 19);
        text(panel, "Select a compressed track supported by the HDMI receiver. Check its input and cable, then test standalone mpv from Windows. Atmos/DTS:X in a track title is metadata, not receiver confirmation. Subtitle availability depends on the container and Media3 decoder; advanced ASS effects may differ.", 15);
        return scroll(panel);
    }

    void connected(boolean value, boolean blocked) {
        connected = value; this.blocked = blocked; updateEnabled();
    }
    void state(JSONObject value) {
        if (value == null) return;
        state = value;
        availableProviders.clear();
        JSONArray providers = value.optJSONArray("providers");
        if (providers != null) for (int i = 0; i < providers.length(); i++) {
            JSONObject row = providers.optJSONObject(i);
            if (row != null && row.optBoolean("available")) availableProviders.add(row.optString("id"));
        }
        long position = value.optLong("position_ms"), duration = value.optLong("duration_ms");
        nowPlaying.setText(value.optString("title", "No movie loaded") + "\n" + value.optString("state", "idle")
            + " · " + time(position) + " / " + time(duration));
        audio.setText(value.optString("audio_badge", "No audio selected") + "\nSubtitle: " + subtitleLabel(value));
        if (!dragging) { timeline.setMax((int)Math.min(Integer.MAX_VALUE, Math.max(1, duration))); timeline.setProgress((int)Math.min(Integer.MAX_VALUE, Math.max(0, position))); }
        updateEnabled();
    }
    private static String subtitleLabel(JSONObject state) {
        String selected = state.optString("selected_subtitle", "off");
        JSONArray choices = state.optJSONArray("subtitle_tracks");
        if (choices != null) for (int i = 0; i < choices.length(); i++) {
            JSONObject row = choices.optJSONObject(i);
            if (row != null && row.optString("id").equals(selected)) return row.optString("label", selected);
        }
        return selected.equals("off") ? "Off" : selected;
    }
    void response(JSONObject message, String action) {
        if (!message.optBoolean("ok", true)) {
            libraryStatus.setText(message.optString("error", "Request failed. Check the Windows app.")); return;
        }
        if (message.optLong("reply", -1) != browseRequest) return;
        JSONObject result = message.optJSONObject("result");
        if (result == null) return;
        listing.removeAllViews(); parent = result.optString("parent", "");
        libraryStatus.setText(result.optString("label", "Shared movies"));
        JSONArray rows = result.optJSONArray("entries");
        if (rows == null || rows.length() == 0) text(listing, "No movie files here. Choose a subfolder, another source, or share a Windows movie folder.", 15);
        if (rows != null) for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i); if (row == null) continue;
            String id = row.optString("id"), name = row.optString("name"); boolean directory = row.optBoolean("directory");
            Button item = button(listing, (directory ? "Folder · " : "Play · ") + name,
                () -> { if (directory) browse(provider, id, 0); else load(id, name); });
            if (!row.optBoolean("available", true) || !directory && row.has("seekable") && !row.optBoolean("seekable")) { item.setTag(Boolean.FALSE); item.setEnabled(false); }
        }
        if (!result.isNull("next_cursor") && result.has("next_cursor")) {
            int next = result.optInt("next_cursor"); button(listing, "Next page", () -> browse(provider, entry, next));
        }
        if (cursor > 0) button(listing, "Previous page", () -> browse(provider, entry, Math.max(0, cursor - 100)));
    }
    private void updateEnabled() {
        boolean ready = connected && !blocked && state.optBoolean("loaded") && state.optBoolean("can_control", true);
        for (View view : playbackControls) view.setEnabled(ready);
        for (Button button : libraryControls) button.setEnabled(connected && !blocked);
        for (Map.Entry<String, Button> source : providerButtons.entrySet())
            source.getValue().setEnabled(connected && !blocked && availableProviders.contains(source.getKey()));
        if (listing != null) for (int i = 0; i < listing.getChildCount(); i++) {
            View row = listing.getChildAt(i); row.setEnabled(connected && !blocked && !Boolean.FALSE.equals(row.getTag()));
        }
    }
    private void browse(String source, String id, int page) {
        if (!connected || blocked) return;
        provider = source; entry = id; cursor = page;
        libraryStatus.setText("Opening shared folder…"); listing.removeAllViews();
        browseRequest = commands.request("browse", object("provider", source, "entry", id, "cursor", page));
    }
    private void load(String id, String title) {
        new AlertDialog.Builder(activity).setTitle("Play " + title + "?")
            .setMessage("Windows will prepare the original video and HDMI audio. Keep the source device and its sharing app open.")
            .setPositiveButton("Play", (d, w) -> commands.request("load_entry", object("provider", provider, "entry", id, "autoplay", true)))
            .setNegativeButton("Cancel", null).show();
    }
    private void seek(int delta) { request("seek", object("seconds", Math.max(0, state.optDouble("position_ms") / 1000 + delta)), state); }
    private void tracks(boolean subtitles) {
        JSONArray rows = state.optJSONArray(subtitles ? "subtitle_tracks" : "audio_tracks");
        List<String> labels = new ArrayList<>(), ids = new ArrayList<>(); int selected = -1;
        if (subtitles) { labels.add("Off"); ids.add("off"); selected = state.optString("selected_subtitle", "off").equals("off") ? 0 : -1; }
        if (rows != null) for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i); if (row == null || !row.optBoolean("supported", true)) continue;
            ids.add(row.optString("id")); labels.add(row.optString("label", "Track " + (i + 1)));
            if (row.optBoolean("selected")) selected = ids.size() - 1;
        }
        if (labels.isEmpty()) { new AlertDialog.Builder(activity).setMessage("No supported audio tracks are available. Check the Windows playback error.").setPositiveButton("OK", null).show(); return; }
        JSONObject context;
        try { context = new JSONObject(state.toString()); } catch (JSONException error) { return; }
        new AlertDialog.Builder(activity).setTitle(subtitles ? "Subtitles" : "Audio track")
            .setSingleChoiceItems(labels.toArray(new String[0]), selected, (dialog, index) -> {
                request(subtitles ? "subtitle" : "track", object(subtitles ? "sid" : "aid", ids.get(index)), context); dialog.dismiss();
            }).setNegativeButton("Cancel", null).show();
    }
    private void request(String action, JSONObject values, JSONObject context) {
        if (!connected || blocked) return;
        JSONObject message = values == null ? new JSONObject() : values;
        try { message.put("epoch", context.optLong("epoch")).put("media_generation", context.optLong("media_generation")); }
        catch (JSONException ignored) { return; }
        commands.request(action, message);
    }
    static JSONObject object(Object... values) {
        JSONObject object = new JSONObject();
        try { for (int i = 0; i < values.length; i += 2) object.put((String)values[i], values[i + 1]); }
        catch (JSONException error) { throw new IllegalArgumentException(error); }
        return object;
    }
    private static String time(long ms) {
        long s = Math.max(0, ms / 1000); return String.format(Locale.ROOT, "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60);
    }
}
