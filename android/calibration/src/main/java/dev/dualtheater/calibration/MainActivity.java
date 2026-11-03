package dev.dualtheater.calibration;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import dev.dualtheater.shared.StorageShare;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.os.*;
import android.text.InputType;
import android.util.Log;
import android.view.*;
import android.widget.*;
import java.util.*;
import org.json.*;

/** LAN-connected, foreground-only physical flash/beep measurement client. */
public final class MainActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Map<String, Button> hosts = new LinkedHashMap<>();
    private LinearLayout hostList;
    private EditText address, port, code;
    private TextView status, progress, result, problem;
    private Button connectButton, findButton, startButton, cancelButton, applyButton;
    private StorageShare storageShare;
    private PhoneControls remote;
    private FrameLayout pages;
    private final Map<String, View> pageViews = new LinkedHashMap<>();
    private final Map<String, Button> navigation = new LinkedHashMap<>();
    private boolean clientProtocol, volumeReady, reconnectAfterPicker;
    private String activePage = "Connect";
    private CameraPreview preview;
    private PhoneClient client;
    private Discovery discovery;
    private CaptureController capture;
    private boolean foreground, connected, connecting, warming, starting, permissionStart;
    private String selectedId = "", selectedAddress = "", runId = "", remoteState = "idle";
    private int selectedPort = 8766;
    private boolean captureDiagnostics;
    private String lastCaptureProgress = "";
    private String loggedState = "";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(PhoneControls.BACKGROUND);
        getWindow().setNavigationBarColor(PhoneControls.BACKGROUND);
        storageShare = new StorageShare(this);
        LinearLayout shell = new LinearLayout(this); shell.setOrientation(LinearLayout.VERTICAL);
        shell.setBackgroundColor(PhoneControls.BACKGROUND); shell.setPadding(dp(14), dp(6), dp(14), dp(6));
        label(shell, "DualTheater", 22).setTextColor(PhoneControls.ACCENT);
        status = label(shell, "Start Windows, connect the TV, then pair this phone.", 14);
        LinearLayout nav = new LinearLayout(this); shell.addView(nav);
        for (String name : new String[]{"Connect", "Library", "Player", "Calibrate", "Help"}) {
            Button tab = new Button(this); tab.setText(name); tab.setAllCaps(false); tab.setTextColor(PhoneControls.TEXT);
            nav.addView(tab, new LinearLayout.LayoutParams(0, dp(46), 1)); navigation.put(name, tab);
            tab.setOnClickListener(v -> showPage(name));
        }
        pages = new FrameLayout(this); shell.addView(pages, new LinearLayout.LayoutParams(-1, 0, 1));
        remote = new PhoneControls(this, new PhoneControls.Commands() {
            @Override public long request(String action, JSONObject values) {
                if (!connected || !clientProtocol || client == null) {
                    problem.setText("Connect to the matching Windows version for player and library controls."); return -1;
                }
                if (warming || starting || active()) { problem.setText("Finish or cancel calibration before controlling a movie."); return -1; }
                return client.request(action, values);
            }
            @Override public void chooseStorage() { chooseStorageFolder(); }
            @Override public void stopSharing() {
                storageShare.forgetTree();
                if (connected && clientProtocol) client.request("storage_unregister", null);
                problem.setText("Phone folder is no longer shared. Windows and TV playback controls remain available.");
            }
        });
        pageViews.put("Connect", connectView()); pageViews.put("Library", remote.libraryView());
        pageViews.put("Player", remote.playerView()); pageViews.put("Calibrate", calibrationView());
        pageViews.put("Help", remote.helpView());
        for (View view : pageViews.values()) pages.addView(view, new FrameLayout.LayoutParams(-1, -1));
        problem = label(shell, "", 14); problem.setTextColor(0xffff9292);
        setContentView(shell); showPage("Connect"); controls();
    }

    private View connectView() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), dp(8), dp(12), dp(8)); scroll.addView(panel);
        label(panel, "Connect to Windows", 22);
        label(panel, "Open DualTheater on the laptop or PC and start the TV connection. Select that computer below and enter its six-digit code once. Saved pairings reconnect without a new code.", 15);
        hostList = new LinearLayout(this); hostList.setOrientation(LinearLayout.VERTICAL); panel.addView(hostList);
        findButton = button(panel, "Find computers", this::findHosts);
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        LinearLayout advanced = new LinearLayout(this); advanced.setOrientation(LinearLayout.VERTICAL);
        button(panel, "Advanced connection", () -> advanced.setVisibility(advanced.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE));
        panel.addView(advanced); advanced.setVisibility(View.GONE);
        address = edit(advanced, "Windows address (only if discovery is blocked)", prefs.getString("address", ""), InputType.TYPE_CLASS_TEXT);
        port = edit(advanced, "Control port", prefs.getString("port", "8766"), InputType.TYPE_CLASS_NUMBER);
        code = edit(panel, "Six-digit code · leave empty for saved pairing", "", InputType.TYPE_CLASS_NUMBER);
        selectedId = prefs.getString("host_id", ""); selectedAddress = address.getText().toString();
        try { selectedPort = Integer.parseInt(port.getText().toString()); } catch (NumberFormatException ignored) {}
        connectButton = button(panel, "Connect", this::connect);
        button(panel, "Disconnect", () -> { if (client != null) client.close(); });
        label(panel, "No computer found? Keep devices on the same trusted network, allow DualTheater through the Windows private-network firewall, and check that a VPN or guest network is not isolating them. Use Help for setup steps.", 14).setTextColor(PhoneControls.MUTED);
        return scroll;
    }

    private View calibrationView() {
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.HORIZONTAL);
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(12), 0, dp(16), 0); scroll.addView(panel);
        layout.addView(scroll, new LinearLayout.LayoutParams(0, -1, 1.2f));
        label(panel, "Calibrate · recommended", 22).setTextColor(PhoneControls.ACCENT);
        label(panel, "Raise the soundbar/receiver volume so the beeps are clearly audible at the phone. Place the phone steadily at your listening seat, center the TV in the guide and keep the room quiet.", 15);
        label(panel, "Start temporarily replaces the movie with a 22-second flash/beep test. Measure, review, Apply, then verify and reload the movie. Camera and microphone run only during the test; recordings are not saved.", 14).setTextColor(PhoneControls.MUTED);
        startButton = button(panel, "Start calibration / verify again", this::startCapture);
        cancelButton = button(panel, "Cancel test", this::cancel);
        progress = label(panel, "", 14);
        result = label(panel, "No measurement yet. Raise the receiver volume before starting so the microphone can detect all six beeps.", 15);
        applyButton = button(panel, "Apply suggested Video lead", this::apply);
        FrameLayout cameraArea = new FrameLayout(this); cameraArea.setBackgroundColor(Color.BLACK);
        preview = new CameraPreview(this); preview.setAlpha(0f);
        cameraArea.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        View guide = new View(this) {
            private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            private final android.graphics.RectF bounds = new android.graphics.RectF();
            @Override protected void onDraw(Canvas canvas) {
                paint.setColor(PhoneControls.ACCENT); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(2));
                preview.guideBounds(bounds); canvas.drawRect(bounds, paint);
                paint.setStyle(Paint.Style.FILL); paint.setTextSize(dp(14));
                canvas.drawText("Center the TV flash area here", dp(12), dp(28), paint);
            }
        };
        preview.setGeometryChanged(guide::invalidate); cameraArea.addView(guide, new FrameLayout.LayoutParams(-1, -1));
        layout.addView(cameraArea, new LinearLayout.LayoutParams(0, -1, 1)); return layout;
    }

    private void showPage(String name) {
        if ((warming || starting || active()) && !name.equals("Calibrate")) {
            problem.setText("Finish or cancel calibration before leaving this screen."); return;
        }
        activePage = name;
        for (Map.Entry<String, View> page : pageViews.entrySet()) page.getValue().setVisibility(page.getKey().equals(name) ? View.VISIBLE : View.GONE);
        for (Map.Entry<String, Button> tab : navigation.entrySet()) {
            tab.getValue().setTextColor(tab.getKey().equals(name) ? PhoneControls.BACKGROUND : PhoneControls.TEXT);
            tab.getValue().setBackgroundTintList(android.content.res.ColorStateList.valueOf(tab.getKey().equals(name) ? PhoneControls.ACCENT : PhoneControls.CARD));
        }
    }

    private void chooseStorageFolder() {
        if (warming || starting || active()) { problem.setText("Finish or cancel calibration before changing shared storage."); return; }
        reconnectAfterPicker = connected;
        try { startActivityForResult(StorageShare.pickerIntent(), 41); }
        catch (android.content.ActivityNotFoundException error) { problem.setText("This device has no folder picker. Share a Windows folder instead."); }
    }

    private void registerStorage() {
        if (!connected || !clientProtocol || !foreground || !storageShare.hasTree()) return;
        try { JSONObject registration = storageShare.start().put("label", "Phone storage"); client.registerStorage(registration); }
        catch (Exception error) { problem.setText("Phone folder is unavailable. Choose it again in Library; use local, seekable storage."); }
    }

    @Override protected void onActivityResult(int request, int resultCode, Intent data) {
        super.onActivityResult(request, resultCode, data);
        if (request != 41) return;
        if (resultCode == RESULT_OK && data != null && data.getData() != null) {
            try {
                Uri tree = data.getData(); getContentResolver().takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION);
                storageShare.setTree(tree);
            } catch (Exception error) { problem.setText("Folder permission was not retained. Choose a local folder and allow read access."); }
        }
        main.post(() -> { if (reconnectAfterPicker && foreground && !connected && !connecting) connect(); else registerStorage(); reconnectAfterPicker = false; });
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView label(LinearLayout parent, String text, int size) {
        TextView value = new TextView(this); value.setText(text); value.setTextSize(size); value.setTextColor(PhoneControls.TEXT);
        value.setPadding(0, dp(5), 0, dp(5)); parent.addView(value); return value;
    }
    private Button button(LinearLayout parent, String text, Runnable action) {
        Button value = new Button(this); value.setText(text); value.setAllCaps(false); value.setTextColor(PhoneControls.TEXT); PhoneControls.card(value); value.setOnClickListener(v -> action.run()); parent.addView(value); return value;
    }
    private EditText edit(LinearLayout parent, String hint, String text, int type) {
        EditText value = new EditText(this); value.setHint(hint); value.setText(text); value.setInputType(type);
        value.setSingleLine(true); value.setTextColor(PhoneControls.TEXT); value.setHintTextColor(PhoneControls.MUTED); parent.addView(value); return value;
    }

    private void findHosts() {
        if (!foreground || connected || connecting) return;
        if (discovery != null) discovery.close();
        hosts.clear(); hostList.removeAllViews();
        discovery = new Discovery((id, name, ip, controlPort) -> main.post(() -> {
            if (!foreground || connected || connecting || hosts.containsKey(id) || hosts.size() >= 8) return;
            Button value = button(hostList, name.isEmpty() ? "Connect to computer" : name, () -> {
                if (connected || connecting) return;
                selectedId = id; selectedAddress = ip; selectedPort = controlPort;
                address.setText(ip); port.setText(String.valueOf(controlPort)); connect();
            });
            hosts.put(id, value);
        }));
        discovery.start();
    }

    private void connect() {
        if (connected || connecting || !foreground) return;
        problem.setText("");
        String host = address.getText().toString().trim(), entered = code.getText().toString().trim();
        int number;
        try { number = Integer.parseInt(port.getText().toString()); if (number < 1 || number > 65535 || host.isEmpty()) throw new IllegalArgumentException(); }
        catch (Exception error) { problem.setText("Enter a Windows LAN address and valid port."); return; }
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        String token = entered;
        if (entered.isEmpty() && host.equals(selectedAddress) && number == selectedPort && !selectedId.isEmpty())
            token = prefs.getString("trusted_" + selectedId, "");
        if (token.isEmpty() || !entered.isEmpty() && !entered.matches("[0-9]{6}")) {
            problem.setText("Enter the six-digit code shown on Windows Connect, then press Connect."); code.requestFocus(); return;
        }
        String id = prefs.getString("client_id", "");
        if (id.isEmpty()) { id = UUID.randomUUID().toString(); prefs.edit().putString("client_id", id).apply(); }
        final String expectedHost = token.equals(entered) ? "" : selectedId;
        final PhoneClient[] connection = new PhoneClient[1];
        connection[0] = new PhoneClient(new PhoneClient.Listener() {
            @Override public void message(JSONObject message, String action) {
                main.post(() -> {
                    if (!foreground || client != connection[0]) return;
                    handle(message, action, expectedHost, host, number);
                });
            }
            @Override public void disconnected(String reason) {
                main.post(() -> {
                    if (client != connection[0]) return;
                    stopCapture(); storageShare.close(); connected = false; connecting = false; remoteState = "idle";
                    status.setText(reason); controls();
                });
            }
        });
        if (client != null) client.close();
        client = connection[0]; connecting = true; status.setText("Connecting…"); controls();
        client.connect(host, number, token, id);
    }

    private void handle(JSONObject message, String action, String expectedHost, String host, int controlPort) {
        try {
            if (message.optString("op").equals("client_state")) { remote.state(message.optJSONObject("state")); controls(); return; }
            if (message.optString("op").equals("client_response")) {
                remote.response(message, action);
                if (!message.optBoolean("ok", true)) problem.setText(message.optString("error", "Player request failed; check Windows."));
                return;
            }
            if (message.optString("op").equals("auth_required")) {
                problem.setText(message.optString("error", "Enter the current pairing code")); client.close(); return;
            }
            if (message.optString("op").equals("welcome")) {
                captureDiagnostics = message.optBoolean("capture_diagnostics", false);
                clientProtocol = message.optInt("client_protocol") == 1;
                if (connected || !message.optString("role").equals("calibration") || message.optInt("calibration_protocol") != 1)
                    throw new IllegalStateException("Use the matching Windows app with phone calibration support");
                String hostId = UUID.fromString(message.getString("host_id")).toString();
                if (!expectedHost.isEmpty() && !expectedHost.equals(hostId)) throw new IllegalStateException("Computer identity changed; find and pair again");
                String trusted = message.getString("trusted_token");
                if (trusted.length() < 40) throw new IllegalStateException("Host did not issue a saved pairing credential");
                getPreferences(MODE_PRIVATE).edit().putString("trusted_" + hostId, trusted).putString("host_id", hostId)
                    .putString("address", host).putString("port", String.valueOf(controlPort)).apply();
                selectedId = hostId; selectedAddress = host; selectedPort = controlPort;
                connected = true; connecting = false; code.setText("");
                if (discovery != null) discovery.close();
                client.startPolling(); registerStorage();
            }
            if (message.has("ok") && !message.optBoolean("ok")) {
                Log.w("DTCalibration", "host_rejected: " + message.optString("error", "Calibration command failed"));
                problem.setText(message.optString("error", "Calibration command failed"));
                if ("start".equals(action) || "complete".equals(action)) { stopCapture(); client.send("cancel", null); }
            }
            if ("start".equals(action)) starting = false;
            JSONObject state = message.optJSONObject("calibration");
            if (state != null) {
                if (!state.optString("fixture_id").equals("phone-v1")) throw new IllegalStateException("Calibration fixture version mismatch");
                remoteState = state.optString("state", "idle"); runId = state.optString("run_id", "");
                if (!remoteState.equals(loggedState)) {
                    loggedState = remoteState;
                    Log.i("DTCalibration", "host_state=" + remoteState);
                }
                status.setText("Connected · " + state.optString("sync_mode", "legacy") + " · " + remoteState
                    + (state.optBoolean("tv_connected") ? " · TV connected" : " · Connect the TV first"));
                if (!state.optString("error").isEmpty()) {
                    if (!state.optString("error").equals(problem.getText().toString()))
                        Log.w("DTCalibration", "host_capture_error: " + state.optString("error"));
                    problem.setText(state.optString("error"));
                }
                if (!warming && !starting && Arrays.asList("error", "cancelled", "measured", "applied").contains(remoteState)) stopCapture();
                JSONObject measured = state.optJSONObject("result");
                if (measured != null) {
                    double gap = measured.getDouble("sound_minus_light_ms");
                    result.setText(String.format(Locale.ROOT,
                        "%d pairs · Sound %s by %.1f ms\nRepeat spread: ±%.1f ms\nCapture resolution estimate: ±%.1f ms\nSuggested Video lead: %.1f ms\n%s\nNo reference fixture used; absolute accuracy unvalidated.",
                        measured.getInt("pair_count"), gap >= 0 ? "late" : "early", Math.abs(gap),
                        measured.getDouble("repeatability_ms"), measured.getDouble("capture_uncertainty_ms"),
                        measured.getDouble("proposed_video_lead_ms"), remoteState.equals("applied")
                            ? "Saved on Windows. Reload your movie, or run another test to verify." : "Review the estimate, then Apply if desired."));
                }
            }
            controls();
        } catch (Exception error) { problem.setText(error.getMessage()); if (client != null) client.close(); }
    }

    private void startCapture() {
        if (!connected || warming || starting || active()) return;
        if (!volumeReady) {
            new AlertDialog.Builder(this).setTitle("Make the test beeps audible")
                .setMessage("Increase the soundbar or receiver volume until beeps can be heard clearly at the phone. Keep the phone steady at the listening seat and the room quiet. This test temporarily replaces your movie; reload it afterward.")
                .setPositiveButton("Volume is ready · start", (dialog, which) -> { if (foreground && connected) { volumeReady = true; startCapture(); } })
                .setNegativeButton("Not yet", null).show(); return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
            || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionStart = true;
            requestPermissions(new String[]{Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO}, 10); return;
        }
        volumeReady = false; showPage("Calibrate");
        problem.setText(""); result.setText("Measuring physical light and sound. Keep the TV centered and remain quiet.");
        warming = true; controls(); preview.setAlpha(1f);
        lastCaptureProgress = "";
        final CaptureController[] source = new CaptureController[1];
        source[0] = new CaptureController(this, preview, new CaptureController.Listener() {
            @Override public void ready() { main.post(() -> {
                if (!foreground || capture != source[0] || !connected) return;
                source[0].begin(); warming = false; starting = true; status.setText("Capture ready. Preparing the test on Windows…");
                client.send("start", null); controls();
            }); }
            @Override public void progress(MeasurementEngine.Diagnostics diagnostics) { main.post(() -> {
                if (capture == source[0]) progress.setText(warming ? "Stabilizing exposure and capture clocks…"
                    : "Detected flashes: " + diagnostics.flashes + " · Beeps: " + diagnostics.beeps + " · Looking for six matched cues");
                if (capture == source[0] && captureDiagnostics && connected && !warming && !starting && active()) {
                    String key = runId + ":" + diagnostics.summary();
                    if (!key.equals(lastCaptureProgress)) {
                        try {
                            JSONObject data = new JSONObject().put("flashes", diagnostics.flashes).put("beeps", diagnostics.beeps);
                            JSONArray video = new JSONArray(), audio = new JSONArray();
                            for (double value : diagnostics.flashOnsetsMs) video.put(value);
                            for (double value : diagnostics.beepOnsetsMs) audio.put(value);
                            data.put("flash_onsets_ms", video).put("beep_onsets_ms", audio);
                            client.send("capture_progress", new JSONObject().put("run_id", runId).put("capture", data));
                            lastCaptureProgress = key;
                        } catch (JSONException error) { cancel(); problem.setText("Invalid capture diagnostics; retry"); }
                    }
                }
            }); }
            @Override public void measured(double[][] pairs) { main.post(() -> {
                if (!foreground || capture != source[0] || !connected) return;
                stopCapture();
                try {
                    JSONArray rows = new JSONArray();
                    for (double[] pair : pairs) rows.put(new JSONObject().put("gap_ms", pair[0]).put("uncertainty_ms", pair[1]));
                    client.send("complete", new JSONObject().put("run_id", runId).put("pairs", rows));
                    Log.i("DTCalibration", "six_matched_pairs_submitted");
                    progress.setText("Six pairs captured. Waiting for Windows to pause and validate the result…");
                } catch (JSONException error) { cancel(); problem.setText("Invalid measurement; retry"); }
            }); }
            @Override public void error(String reason) { main.post(() -> {
                if (capture != source[0]) return;
                cancel(); problem.setText(reason);
            }); }
        });
        capture = source[0]; source[0].start();
    }

    private boolean active() { return Arrays.asList("preparing", "playing", "awaiting_capture", "finishing").contains(remoteState); }
    private void apply() {
        if (!connected || !remoteState.equals("measured")) return;
        try { problem.setText(""); client.send("apply", new JSONObject().put("run_id", runId)); }
        catch (JSONException ignored) {}
    }
    private void cancel() { permissionStart = false; stopCapture(); if (connected) client.send("cancel", null); controls(); }
    private void stopCapture() {
        CaptureController value = capture; capture = null; warming = false; starting = false;
        if (value != null) value.close();
        preview.setAlpha(0f); controls();
    }
    private void controls() {
        if (connectButton == null) return;
        if (remote != null) remote.connected(connected && clientProtocol, warming || starting || active());
        connectButton.setEnabled(!connected && !connecting); findButton.setEnabled(!connected && !connecting);
        address.setEnabled(!connected && !connecting); port.setEnabled(!connected && !connecting); code.setEnabled(!connected && !connecting);
        startButton.setEnabled(connected && !warming && !starting && !active());
        cancelButton.setEnabled(connected && (warming || starting || active()));
        applyButton.setEnabled(connected && !warming && !starting && remoteState.equals("measured"));
    }
    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(request, permissions, grants);
        if (request != 10 || !permissionStart) return;
        permissionStart = false;
        if (foreground && connected && grants.length == 2 && grants[0] == PackageManager.PERMISSION_GRANTED && grants[1] == PackageManager.PERMISSION_GRANTED) startCapture();
        else problem.setText("Allow camera and microphone permission to run calibration.");
    }
    @Override protected void onStart() { super.onStart(); foreground = true; }
    @Override protected void onResume() { super.onResume(); if (!connected && !connecting) findHosts(); }
    @Override protected void onStop() {
        foreground = false; permissionStart = false; volumeReady = false; stopCapture(); storageShare.close();
        if (discovery != null) discovery.close();
        if (client != null) client.close();
        connected = false; connecting = false; remoteState = "idle"; controls(); super.onStop();
    }
    @Override protected void onDestroy() { main.removeCallbacksAndMessages(null); super.onDestroy(); }
}
