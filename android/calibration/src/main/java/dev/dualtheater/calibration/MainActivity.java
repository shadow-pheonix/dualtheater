package dev.dualtheater.calibration;

import android.Manifest;
import android.app.Activity;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.os.*;
import android.text.InputType;
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
    private TextureView preview;
    private PhoneClient client;
    private Discovery discovery;
    private CaptureController capture;
    private boolean foreground, connected, connecting, warming, starting, permissionStart;
    private String selectedId = "", selectedAddress = "", runId = "", remoteState = "idle";
    private int selectedPort = 8766;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setPadding(dp(14), dp(10), dp(14), dp(10));
        ScrollView scroll = new ScrollView(this);
        LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(0, 0, dp(16), 0); scroll.addView(panel);
        layout.addView(scroll, new LinearLayout.LayoutParams(0, -1, 1.2f));
        TextView title = label(panel, "DualTheater Calibration Preview", 22);
        title.setPadding(0, 0, 0, dp(8));
        label(panel, "Place the phone at your listening seat and center the TV in the guide. Camera and microphone run only during a test; captures are not saved or uploaded.", 14);
        hostList = new LinearLayout(this); hostList.setOrientation(LinearLayout.VERTICAL); panel.addView(hostList);
        findButton = button(panel, "Find computers", this::findHosts);
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        address = edit(panel, "Windows LAN address", prefs.getString("address", ""), InputType.TYPE_CLASS_TEXT);
        port = edit(panel, "Control port", prefs.getString("port", "8766"), InputType.TYPE_CLASS_NUMBER);
        code = edit(panel, "Six-digit pairing code (leave empty for saved pairing)", "", InputType.TYPE_CLASS_NUMBER);
        selectedId = prefs.getString("host_id", ""); selectedAddress = address.getText().toString();
        try { selectedPort = Integer.parseInt(port.getText().toString()); } catch (NumberFormatException ignored) {}
        connectButton = button(panel, "Connect", this::connect);
        status = label(panel, "Start the matching Windows preview and connect its TV companion first.", 16);
        label(panel, "Start replaces the current movie with a 22-second SDR/stereo TrueHD test, without Atmos. Keep the camera still and the room quiet. No reference fixture is required.", 14);
        startButton = button(panel, "Start calibration / verify again", this::startCapture);
        cancelButton = button(panel, "Cancel test", this::cancel);
        progress = label(panel, "", 14);
        result = label(panel, "No measurement yet. Capture timestamps provide an estimate; absolute accuracy has not been externally validated.", 15);
        applyButton = button(panel, "Apply suggested Video lead", this::apply);
        problem = label(panel, "", 15); problem.setTextColor(0xffffb4a8);
        FrameLayout cameraArea = new FrameLayout(this); cameraArea.setBackgroundColor(Color.BLACK);
        preview = new TextureView(this); preview.setAlpha(0f);
        cameraArea.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        cameraArea.addView(new View(this) {
            private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
            @Override protected void onDraw(Canvas canvas) {
                paint.setColor(0xff44dfcd); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(2));
                canvas.drawRect(getWidth() * .4f, getHeight() * .45f, getWidth() * .6f, getHeight() * .55f, paint);
                paint.setStyle(Paint.Style.FILL); paint.setTextSize(dp(15));
                canvas.drawText("Center the TV flash area here", dp(12), dp(30), paint);
            }
        }, new FrameLayout.LayoutParams(-1, -1));
        layout.addView(cameraArea, new LinearLayout.LayoutParams(0, -1, 1));
        setContentView(layout); controls();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView label(LinearLayout parent, String text, int size) {
        TextView value = new TextView(this); value.setText(text); value.setTextSize(size);
        value.setPadding(0, dp(5), 0, dp(5)); parent.addView(value); return value;
    }
    private Button button(LinearLayout parent, String text, Runnable action) {
        Button value = new Button(this); value.setText(text); value.setOnClickListener(v -> action.run()); parent.addView(value); return value;
    }
    private EditText edit(LinearLayout parent, String hint, String text, int type) {
        EditText value = new EditText(this); value.setHint(hint); value.setText(text); value.setInputType(type);
        value.setSingleLine(true); parent.addView(value); return value;
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
                    stopCapture(); connected = false; connecting = false; remoteState = "idle";
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
            if (message.optString("op").equals("auth_required")) {
                problem.setText(message.optString("error", "Enter the current pairing code")); client.close(); return;
            }
            if (message.optString("op").equals("welcome")) {
                if (connected || !message.optString("role").equals("calibration") || message.optInt("calibration_protocol") != 1)
                    throw new IllegalStateException("Use the matching Windows preview with phone calibration support");
                String hostId = UUID.fromString(message.getString("host_id")).toString();
                if (!expectedHost.isEmpty() && !expectedHost.equals(hostId)) throw new IllegalStateException("Computer identity changed; find and pair again");
                String trusted = message.getString("trusted_token");
                if (trusted.length() < 40) throw new IllegalStateException("Host did not issue a saved pairing credential");
                getPreferences(MODE_PRIVATE).edit().putString("trusted_" + hostId, trusted).putString("host_id", hostId)
                    .putString("address", host).putString("port", String.valueOf(controlPort)).apply();
                selectedId = hostId; selectedAddress = host; selectedPort = controlPort;
                connected = true; connecting = false; code.setText("");
                if (discovery != null) discovery.close();
                client.startPolling();
            }
            if (message.has("ok") && !message.optBoolean("ok")) {
                problem.setText(message.optString("error", "Calibration command failed"));
                if ("start".equals(action) || "complete".equals(action)) { stopCapture(); client.send("cancel", null); }
            }
            if ("start".equals(action)) starting = false;
            JSONObject state = message.optJSONObject("calibration");
            if (state != null) {
                if (!state.optString("fixture_id").equals("phone-v1")) throw new IllegalStateException("Calibration fixture version mismatch");
                remoteState = state.optString("state", "idle"); runId = state.optString("run_id", "");
                status.setText("Connected · " + state.optString("sync_mode", "legacy") + " · " + remoteState
                    + (state.optBoolean("tv_connected") ? " · TV connected" : " · Connect the TV first"));
                if (!state.optString("error").isEmpty()) problem.setText(state.optString("error"));
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
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
            || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            permissionStart = true;
            requestPermissions(new String[]{Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO}, 10); return;
        }
        problem.setText(""); result.setText("Measuring physical light and sound. Keep the TV centered and remain quiet.");
        warming = true; controls(); preview.setAlpha(1f);
        final CaptureController[] source = new CaptureController[1];
        source[0] = new CaptureController(this, preview, new CaptureController.Listener() {
            @Override public void ready() { main.post(() -> {
                if (!foreground || capture != source[0] || !connected) return;
                source[0].begin(); warming = false; starting = true; status.setText("Capture ready. Preparing the test on Windows…");
                client.send("start", null); controls();
            }); }
            @Override public void progress(int flashes, int tones) { main.post(() -> {
                if (capture == source[0]) progress.setText(warming ? "Stabilizing exposure and capture clocks…"
                    : "Detected flashes: " + flashes + " · Beeps: " + tones + " · Looking for six matched cues");
            }); }
            @Override public void measured(double[][] pairs) { main.post(() -> {
                if (!foreground || capture != source[0] || !connected) return;
                stopCapture();
                try {
                    JSONArray rows = new JSONArray();
                    for (double[] pair : pairs) rows.put(new JSONObject().put("gap_ms", pair[0]).put("uncertainty_ms", pair[1]));
                    client.send("complete", new JSONObject().put("run_id", runId).put("pairs", rows));
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

    private boolean active() { return Arrays.asList("preparing", "playing", "finishing").contains(remoteState); }
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
        foreground = false; permissionStart = false; stopCapture();
        if (discovery != null) discovery.close();
        if (client != null) client.close();
        connected = false; connecting = false; remoteState = "idle"; controls(); super.onStop();
    }
    @Override protected void onDestroy() { main.removeCallbacksAndMessages(null); super.onDestroy(); }
}
