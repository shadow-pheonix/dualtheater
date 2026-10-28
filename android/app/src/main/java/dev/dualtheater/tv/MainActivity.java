package dev.dualtheater.tv;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.content.res.ColorStateList;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import androidx.media3.common.*;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.exoplayer.*;
import androidx.media3.exoplayer.analytics.AnalyticsListener;
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.exoplayer.video.VideoFrameMetadataListener;
import org.json.*;
import java.util.*;

/** Video-only SurfaceView playback. Every player access stays on the main looper. */
@UnstableApi
public final class MainActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private ExoPlayer player;
    private SurfaceView surface;
    private FrameLayout root;
    private float videoAspect = 16f / 9f;
    private LinearLayout setup;
    private LinearLayout advanced, discoveryPanel, hostList;
    private HostDiscovery discovery;
    private final Map<String, DiscoveredHost> foundHosts = new LinkedHashMap<>();
    private final Map<String, Button> hostButtons = new LinkedHashMap<>();
    private final Set<String> autoAttempted = new HashSet<>();
    private DiscoveredHost selectedHost;
    private boolean connecting, authRequired, foreground;
    private AlertDialog codeDialog;
    private TextView info;
    private EditText hostInput, portInput, tokenInput;
    private ControlClient client;
    private boolean connected = false, seekPending = false, loading = false;
    private final PlaybackSession playback = new PlaybackSession();
    private volatile long callbackGeneration = 0;
    private String error = "", decoderName = "";
    private volatile JSONObject frame = new JSONObject();
    private Runnable scheduled;
    private long lastHostMessage = 0;
    private long seekSerial = 0;
    private JSONArray capabilities;
    private int[] hdrTypes = new int[0];
    private boolean destroyed = false;
    private int bufferBudgetBytes;
    private long droppedVideoFrames;
    private double transferMbps = -1;
    private long transferSampleNs;
    private final RemoteControls remote = new RemoteControls();
    private LinearLayout transport;
    private TextView transportTitle, transportState, transportTime, transportHint;
    private ProgressBar progress;
    private boolean remoteSupported = false;
    private String coordinatorState = "idle", movieTitle = "";
    private long coordinatorEpoch = -1, movieDurationMs = 0, controlsUntil = 0, lastNudge = 0;
    private long pendingTargetMs = -1, pendingRequest = -1;
    private final Runnable commitSeek = () -> {
        if (remote.hasPreview() && !remote.isPending()) sendRemote("seek", false);
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        root.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> {
            if (r - l != or - ol || b - t != ob - ot) fitSurface();
        });
        surface = new SurfaceView(this);
        root.addView(surface, new FrameLayout.LayoutParams(-1, -1));
        setup = new LinearLayout(this); setup.setOrientation(LinearLayout.VERTICAL);
        setup.setPadding(dp(28), dp(18), dp(28), dp(18)); setup.setBackgroundColor(0xee10151c);
        TextView title = new TextView(this); title.setText("DualTheater TV"); title.setTextSize(28);
        setup.addView(title);
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        TextView help = new TextView(this);
        help.setText("Start DualTheater on your laptop, then choose it below. Paired laptops reconnect automatically.");
        help.setTextSize(16); setup.addView(help);
        discoveryPanel = new LinearLayout(this); discoveryPanel.setOrientation(LinearLayout.VERTICAL);
        setup.addView(discoveryPanel);
        DiscoveredHost remembered = rememberedHost();
        if (remembered != null) {
            Button reconnect = new Button(this); reconnect.setText("Reconnect to " + remembered.name);
            reconnect.setOnClickListener(v -> chooseHost(remembered, false)); discoveryPanel.addView(reconnect);
        }
        ScrollView hosts = new ScrollView(this); hosts.setFillViewport(false);
        hostList = new LinearLayout(this); hostList.setOrientation(LinearLayout.VERTICAL); hosts.addView(hostList);
        discoveryPanel.addView(hosts, new LinearLayout.LayoutParams(-1, dp(112)));
        Button refresh = new Button(this); refresh.setText("Find laptops");
        refresh.setOnClickListener(v -> startDiscovery(true)); discoveryPanel.addView(refresh);
        Button showAdvanced = new Button(this); showAdvanced.setText("Advanced connection");
        setup.addView(showAdvanced);
        advanced = new LinearLayout(this); advanced.setOrientation(LinearLayout.VERTICAL); advanced.setVisibility(View.GONE);
        setup.addView(advanced);
        showAdvanced.setOnClickListener(v -> {
            boolean show = advanced.getVisibility() != View.VISIBLE;
            advanced.setVisibility(show ? View.VISIBLE : View.GONE);
            discoveryPanel.setVisibility(show ? View.GONE : View.VISIBLE);
            showAdvanced.setText(show ? "Back to laptop list" : "Advanced connection");
        });
        hostInput = input("Laptop LAN IPv4", prefs.getString("host", ""), InputType.TYPE_CLASS_TEXT);
        portInput = input("Control port", prefs.getString("port", "8766"), InputType.TYPE_CLASS_NUMBER);
        tokenInput = input("Pairing code from Windows controller", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        Button connect = new Button(this); connect.setText("Connect");
        connect.setOnClickListener(v -> { selectedHost = null; connect(); }); advanced.addView(connect);
        info = new TextView(this); info.setText("Searching for laptops on your home network…");
        setup.addView(info);
        root.addView(setup, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER));
        setContentView(root);
        createTransport();
        createPlayer();
        capabilities = codecCapabilities();
        Display display = getWindowManager().getDefaultDisplay();
        if (display != null) hdrTypes = display.getHdrCapabilities().getSupportedHdrTypes();
        main.post(telemetry);
        String provisionHost = getIntent().getStringExtra("host");
        String provisionToken = getIntent().getStringExtra("token");
        if (provisionHost != null && provisionToken != null) {
            hostInput.setText(provisionHost);
            portInput.setText(String.valueOf(getIntent().getIntExtra("port", 8766)));
            tokenInput.setText(provisionToken);
            main.post(this::connect);
        } else main.post(() -> startDiscovery(false));
    }

    private EditText input(String hint, String value, int type) {
        EditText edit = new EditText(this); edit.setHint(hint); edit.setText(value);
        edit.setInputType(type); edit.setSingleLine(true); advanced.addView(edit); return edit;
    }

    private DiscoveredHost rememberedHost() {
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        try {
            String id = prefs.getString("last_host_id", "");
            if (prefs.getString("trusted_" + id, "").isEmpty()) return null;
            return new DiscoveredHost(id, prefs.getString("last_host_name", "Laptop"),
                prefs.getString("host", ""), Integer.parseInt(prefs.getString("port", "8766")));
        } catch (Exception e) { return null; }
    }

    private void stopDiscovery() { if (discovery != null) discovery.close(); discovery = null; }

    private void startDiscovery(boolean clear) {
        if (destroyed || !foreground || connected || connecting) return;
        stopDiscovery();
        if (clear) { foundHosts.clear(); hostButtons.clear(); hostList.removeAllViews(); }
        info.setText("Searching for laptops… Start DualTheater on the laptop and keep both devices on the same network.");
        discovery = new HostDiscovery(new HostDiscovery.Listener() {
            @Override public void onFound(DiscoveredHost host) { main.post(() -> foundHost(host)); }
            @Override public void onError(String reason) { main.post(() -> { if (!destroyed && !connected && !connecting) info.setText(reason); }); }
        });
        discovery.start();
    }

    private void foundHost(DiscoveredHost host) {
        if (destroyed || !foreground || connected) return;
        if (!hostButtons.containsKey(host.id) && hostButtons.size() >= 16) return;
        foundHosts.put(host.id, host);
        boolean trusted = !getPreferences(MODE_PRIVATE).getString("trusted_" + host.id, "").isEmpty();
        Button button = hostButtons.get(host.id);
        if (button == null) {
            button = new Button(this); hostButtons.put(host.id, button); hostList.addView(button);
            final String id = host.id;
            button.setOnClickListener(v -> chooseHost(foundHosts.get(id), false));
            if (hostButtons.size() == 1 && advanced.getVisibility() != View.VISIBLE && !connecting) button.requestFocus();
        }
        button.setText((trusted ? "Connect to " : "Pair with ") + host.name);
        if (!connecting) info.setText("Choose your laptop. You only need its six-digit code the first time.");
        if (trusted && host.id.equals(getPreferences(MODE_PRIVATE).getString("last_host_id", ""))
            && autoAttempted.add(host.id) && !connecting) chooseHost(host, false);
    }

    private void chooseHost(DiscoveredHost host, boolean requireCode) {
        if (host == null || connected || connecting) return;
        autoAttempted.add(host.id);
        selectedHost = host;
        hostInput.setText(host.address); portInput.setText(String.valueOf(host.port));
        String trusted = getPreferences(MODE_PRIVATE).getString("trusted_" + host.id, "");
        if (!requireCode && !trusted.isEmpty()) { tokenInput.setText(trusted); connect(); return; }
        if (codeDialog != null && codeDialog.isShowing()) return;
        EditText code = new EditText(this); code.setInputType(InputType.TYPE_CLASS_NUMBER);
        code.setSingleLine(true); code.setHint("Six-digit code"); code.setTextSize(28);
        code.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(6)});
        codeDialog = new AlertDialog.Builder(this).setTitle("Pair with " + host.name)
            .setMessage("Enter the six-digit code shown in DualTheater on your laptop. It will be remembered for next time.")
            .setView(code).setNegativeButton("Cancel", null).setPositiveButton("Pair", null).create();
        codeDialog.setOnShowListener(dialog -> codeDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try { tokenInput.setText(ConnectionCode.normalize(code.getText().toString())); }
            catch (IllegalArgumentException e) { code.setError(e.getMessage()); return; }
            codeDialog.dismiss(); connect();
        }));
        codeDialog.show(); code.requestFocus();
    }

    private String clientId() {
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        String id = prefs.getString("client_id", null);
        if (id == null) { id = UUID.randomUUID().toString(); prefs.edit().putString("client_id", id).apply(); }
        return id;
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView transportText(float size, int color) {
        TextView text = new TextView(this); text.setTextSize(size); text.setTextColor(color);
        text.setSingleLine(true); return text;
    }

    private void createTransport() {
        transport = new LinearLayout(this); transport.setOrientation(LinearLayout.VERTICAL);
        transport.setPadding(dp(32), dp(26), dp(32), dp(24));
        transport.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            new int[]{0x0010151c, 0xe610151c, 0xf510151c}));
        transport.setFocusable(false);
        transportTitle = transportText(17, 0xffcfdae7); transport.addView(transportTitle);
        LinearLayout row = new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL);
        transportState = transportText(21, Color.WHITE);
        row.addView(transportState, new LinearLayout.LayoutParams(0, dp(42), 1));
        transportTime = transportText(20, Color.WHITE); row.addView(transportTime);
        transport.addView(row);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(10000); progress.setIndeterminate(false); progress.setFocusable(false);
        progress.setProgressTintList(ColorStateList.valueOf(0xff6ed8ed));
        progress.setSecondaryProgressTintList(ColorStateList.valueOf(0xff718397));
        progress.setProgressBackgroundTintList(ColorStateList.valueOf(0xff344151));
        transport.addView(progress, new LinearLayout.LayoutParams(-1, dp(12)));
        transportHint = transportText(15, 0xffcfdae7);
        transportHint.setPadding(0, dp(8), 0, 0); transport.addView(transportHint);
        root.addView(transport, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));
        transport.setVisibility(View.GONE);
    }

    private long durationMs() {
        long value = player.getDuration();
        return value > 0 ? value : movieDurationMs;
    }

    private boolean hostBusy() {
        return coordinatorState.equals("loading") || coordinatorState.equals("seeking")
            || coordinatorState.equals("armed");
    }

    private void showTransport() { controlsUntil = SystemClock.uptimeMillis() + 5000; updateTransport(); }

    private void updateTransport() {
        if (transport == null || player == null || setup.getVisibility() == View.VISIBLE
            || player.getMediaItemCount() == 0) {
            if (transport != null) transport.setVisibility(View.GONE);
            return;
        }
        boolean visible = SystemClock.uptimeMillis() < controlsUntil || remote.hasPreview()
            || remote.isPending() || !player.isPlaying() || hostBusy();
        transport.setVisibility(visible ? View.VISIBLE : View.GONE);
        if (!visible) return;
        long duration = durationMs();
        long position = remote.hasPreview() ? remote.previewMs()
            : remote.isPending() && pendingTargetMs >= 0 ? pendingTargetMs : player.getCurrentPosition();
        transportTitle.setText(movieTitle.isEmpty() ? "DualTheater" : movieTitle);
        String state = remote.hasPreview() ? "Seek to" : remote.isPending() || hostBusy() || seekPending
            ? "Synchronizing…" : player.getPlaybackState() == Player.STATE_BUFFERING
            ? "Buffering…" : coordinatorState.equals("playing") ? "Playing" : "Paused";
        transportState.setText(state);
        transportTime.setText(RemoteControls.time(position) + " / " + (duration > 0 ? RemoteControls.time(duration) : "--:--"));
        progress.setProgress(duration > 0 ? (int)Math.max(0, Math.min(10000, position * 10000 / duration)) : 0);
        progress.setSecondaryProgress(duration > 0
            ? (int)Math.max(0, Math.min(10000, player.getBufferedPosition() * 10000 / duration)) : 0);
        transportHint.setText(remoteSupported ? "← / →  Seek 10 seconds     •     OK  Play / pause"
            : "Update the Windows host to enable TV remote controls");
    }

    private void coordinator(JSONObject message) {
        long incoming = message.optLong("epoch", -1);
        if (incoming < coordinatorEpoch) return;
        coordinatorEpoch = incoming;
        coordinatorState = message.optString("state", "idle");
        movieDurationMs = message.optLong("duration_ms", 0);
        movieTitle = message.optString("title", "");
        updateTransport();
    }

    private void resetRemote() {
        main.removeCallbacks(commitSeek); remote.reset(); pendingRequest = -1; pendingTargetMs = -1;
    }

    private void sendRemote(String action, boolean toggleAfterSeek) {
        if (!connected || !remoteSupported || remote.isPending()) return;
        long request = remote.begin();
        if (request < 0) return;
        main.removeCallbacks(commitSeek);
        pendingRequest = request;
        try {
            JSONObject message = new JSONObject().put("op", "remote").put("request", request)
                .put("epoch", playback.epoch()).put("action", action);
            if (action.equals("seek")) {
                pendingTargetMs = remote.previewMs();
                message.put("seconds", pendingTargetMs / 1000.0).put("toggle", toggleAfterSeek);
            }
            remote.clearPreview(); showTransport(); client.send(message);
            // A lost command/result must not leave local-only playback or an
            // indefinitely disabled remote. Disconnect and let both watchdogs pause.
            main.postDelayed(() -> {
                if (!destroyed && pendingRequest == request && remote.isPending()) {
                    info.setText("Windows did not finish the playback command. Reconnect and reload.");
                    client.close();
                }
            }, 60000);
        } catch (JSONException e) { resetRemote(); }
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (player == null || setup.getVisibility() == View.VISIBLE || player.getMediaItemCount() == 0)
            return super.dispatchKeyEvent(event);
        int key = event.getKeyCode();
        boolean back = key == KeyEvent.KEYCODE_DPAD_LEFT || key == KeyEvent.KEYCODE_MEDIA_REWIND;
        boolean forward = key == KeyEvent.KEYCODE_DPAD_RIGHT || key == KeyEvent.KEYCODE_MEDIA_FAST_FORWARD;
        boolean toggle = key == KeyEvent.KEYCODE_DPAD_CENTER || key == KeyEvent.KEYCODE_ENTER
            || key == KeyEvent.KEYCODE_NUMPAD_ENTER || key == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
            || key == KeyEvent.KEYCODE_SPACE;
        boolean media = toggle || key == KeyEvent.KEYCODE_MEDIA_PLAY || key == KeyEvent.KEYCODE_MEDIA_PAUSE;
        if (back || forward || media) {
            if (event.getAction() == KeyEvent.ACTION_UP) {
                if ((back || forward) && remote.hasPreview()) {
                    main.removeCallbacks(commitSeek); main.postDelayed(commitSeek, 350);
                }
                return true;
            }
            if (event.getAction() != KeyEvent.ACTION_DOWN) return true;
            showTransport();
            if (!connected || !remoteSupported || remote.isPending() || hostBusy()) return true;
            if (back || forward) {
                long now = SystemClock.uptimeMillis();
                if (durationMs() <= 0 || event.getRepeatCount() > 0 && now - lastNudge < 150) return true;
                lastNudge = now;
                remote.nudge(player.getCurrentPosition(), durationMs(), forward ? 10000 : -10000);
                main.removeCallbacks(commitSeek); main.postDelayed(commitSeek, 1500);
                showTransport();
            } else if (event.getRepeatCount() == 0) {
                if (remote.hasPreview() && toggle) sendRemote("seek", true);
                else {
                    remote.clearPreview(); main.removeCallbacks(commitSeek);
                    sendRemote(toggle ? "toggle" : key == KeyEvent.KEYCODE_MEDIA_PLAY ? "play" : "pause", false);
                }
            }
            return true;
        }
        if (key == KeyEvent.KEYCODE_DPAD_UP || key == KeyEvent.KEYCODE_DPAD_DOWN) {
            if (event.getAction() == KeyEvent.ACTION_DOWN) showTransport();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    private void createPlayer() {
        DefaultRenderersFactory defaults = new DefaultRenderersFactory(this)
            .setEnableDecoderFallback(true)
            .setMediaCodecSelector((mime, secure, tunnel) -> {
                List<androidx.media3.exoplayer.mediacodec.MediaCodecInfo> hardware = new ArrayList<>();
                for (androidx.media3.exoplayer.mediacodec.MediaCodecInfo codec :
                     MediaCodecSelector.DEFAULT.getDecoderInfos(mime, secure, tunnel)) {
                    if (codec.hardwareAccelerated && !codec.softwareOnly) hardware.add(codec);
                }
                return hardware;
            });
        RenderersFactory videoOnly = (handler, video, audio, text, metadata) -> {
            List<Renderer> out = new ArrayList<>();
            for (Renderer r : defaults.createRenderers(handler, video, audio, text, metadata)) {
                if (r.getTrackType() == C.TRACK_TYPE_VIDEO) out.add(r);
            }
            return out.toArray(new Renderer[0]);
        };
        DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(5000).setReadTimeoutMs(10000).setUserAgent("DualTheater/0.1");
        // Keep most of the Java heap available for the player, extractor
        // and UI rather than filling the heap with buffered samples.
        bufferBudgetBytes = (int)Math.max(8L * 1024 * 1024,
            Math.min(64L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 4));
        DefaultLoadControl load = new DefaultLoadControl.Builder()
            .setBufferDurationsMs(15000, 45000, 3000, 5000)
            .setTargetBufferBytes(bufferBudgetBytes)
            .setPrioritizeTimeOverSizeThresholds(false).build();
        player = new ExoPlayer.Builder(this, videoOnly)
            .setMediaSourceFactory(new DefaultMediaSourceFactory(http))
            .setLoadControl(load).build();
        player.setTrackSelectionParameters(player.getTrackSelectionParameters().buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, true)
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true).build());
        player.setVideoSurfaceView(surface);
        player.setVideoScalingMode(C.VIDEO_SCALING_MODE_SCALE_TO_FIT);
        player.setVideoChangeFrameRateStrategy(C.VIDEO_CHANGE_FRAME_RATE_STRATEGY_ONLY_IF_SEAMLESS);
        player.setSeekParameters(SeekParameters.EXACT);
        player.addListener(new Player.Listener() {
            @Override public void onVideoSizeChanged(VideoSize size) {
                if (size.height > 0) {
                    videoAspect = size.width * size.pixelWidthHeightRatio / size.height;
                    fitSurface();
                }
            }
            @Override public void onPlaybackStateChanged(int state) {
                if (state == Player.STATE_READY) loading = false;
                status();
            }
            @Override public void onPlayerError(PlaybackException e) {
                error = e.getErrorCodeName() + ": " + e.getMessage();
                cancelStart(); player.pause();
                info.setText(error); setup.setVisibility(View.VISIBLE); status();
            }
        });
        player.addAnalyticsListener(new AnalyticsListener() {
            @Override public void onVideoDecoderInitialized(EventTime time, String name, long stamp, long duration) {
                decoderName = name;
            }
            @Override public void onDroppedVideoFrames(EventTime time, int count, long elapsedMs) {
                droppedVideoFrames += Math.max(0, count);
            }
            @Override public void onBandwidthEstimate(EventTime time, int loadMs, long bytes, long estimate) {
                if (loadMs > 0 && bytes > 0) {
                    transferMbps = bytes * 8.0 / loadMs / 1000;
                    transferSampleNs = System.nanoTime();
                }
            }
        });
        installFrameListener();
    }

    private void fitSurface() {
        int width = root.getWidth(), height = root.getHeight();
        if (width <= 0 || height <= 0 || videoAspect <= 0) return;
        if (width / (float) height > videoAspect) width = Math.round(height * videoAspect);
        else height = Math.round(width / videoAspect);
        surface.setLayoutParams(new FrameLayout.LayoutParams(width, height, Gravity.CENTER));
    }

    private void installFrameListener() {
        final long listenerEpoch = playback.epoch();
        final long sessionGeneration = playback.generation();
        final long generation = ++callbackGeneration;
        frame = new JSONObject();
        player.setVideoFrameMetadataListener((pts, release, format, mediaFormat) -> {
            if (!playback.matches(sessionGeneration) || generation != callbackGeneration) return;
            try {
                frame = new JSONObject().put("epoch", listenerEpoch).put("position_ms", pts / 1000.0)
                    .put("release_ns", release).put("valid", release != C.TIME_UNSET && release > 0)
                    .put("mime", format.sampleMimeType).put("codecs", format.codecs)
                    .put("width", format.width).put("height", format.height)
                    .put("color", String.valueOf(format.colorInfo));
            } catch (JSONException ignored) {}
        });
    }

    private void connect() {
        if (connecting) return;
        cancelStart(); player.pause(); ++seekSerial;
        resetRemote(); remoteSupported = false; coordinatorEpoch = -1;
        if (client != null) client.close();
        String host = hostInput.getText().toString().trim();
        String code = tokenInput.getText().toString().trim();
        int port;
        try {
            port = Integer.parseInt(portInput.getText().toString());
            if (port < 1 || port > 65535 || host.isEmpty() || code.isEmpty()) throw new IllegalArgumentException();
        } catch (Exception e) { info.setText("Enter a laptop IP, port and pairing code."); return; }
        getPreferences(MODE_PRIVATE).edit().putString("host", host).putString("port", String.valueOf(port)).apply();
        connected = false; connecting = true; authRequired = false;
        error = ""; info.setText(selectedHost == null ? "Connecting…" : "Connecting to " + selectedHost.name + "…");
        final ControlClient[] session = new ControlClient[1];
        session[0] = new ControlClient(new ControlClient.Listener() {
            @Override public void onMessage(JSONObject msg) {
                main.post(() -> { if (!destroyed && foreground && client == session[0]) handle(msg); });
            }
            @Override public void onDisconnected(String reason) {
                main.post(() -> {
                    if (destroyed || client != session[0]) return;
                    connected = false; connecting = false; cancelStart(); resetRemote(); player.pause();
                    if (authRequired) { authRequired = false; return; }
                    info.setText(reason + "\nReconnect, then reload the media on Windows.");
                    setup.setVisibility(View.VISIBLE);
                    if (foreground) startDiscovery(false);
                });
            }
        });
        client = session[0];
        client.connect(host, port, code, clientId());
    }

    private void handle(JSONObject msg) {
        long id = msg.optLong("id", -1);
        try {
            lastHostMessage = System.nanoTime();
            String op = msg.optString("op");
            if (op.equals("auth_required")) {
                connecting = false; authRequired = true;
                String reason = msg.optString("error", "Enter the pairing code shown on the laptop");
                info.setText(reason); Toast.makeText(this, reason, Toast.LENGTH_LONG).show();
                if (selectedHost != null) chooseHost(selectedHost, true);
                return;
            }
            if (op.equals("welcome")) {
                connecting = false; authRequired = false;
                String hostId = msg.optString("host_id", "");
                String trusted = msg.optString("trusted_token", "");
                if (selectedHost != null && !hostId.isEmpty() && !selectedHost.id.equals(hostId)) {
                    info.setText("Laptop identity changed. Find and select it again."); client.close(); return;
                }
                // A restarted host begins at epoch zero. Retire all previous media
                // and callbacks before accepting commands from this connection.
                cancelStart(); ++seekSerial; resetRemote();
                player.stop(); player.clearMediaItems(); player.setPlaybackSpeed(1f);
                playback.reset(); installFrameListener();
                loading = false; seekPending = false; error = ""; decoderName = "";
                coordinatorEpoch = -1; coordinatorState = "idle"; movieTitle = ""; movieDurationMs = 0;
                droppedVideoFrames = 0; transferMbps = -1; transferSampleNs = 0;
                setup.setVisibility(View.VISIBLE);
                if (!hostId.isEmpty() && !trusted.isEmpty()) {
                    getPreferences(MODE_PRIVATE).edit().putString("trusted_" + hostId, trusted)
                        .putString("last_host_id", hostId).putString("last_host_name", msg.optString("host_name", "Laptop")).apply();
                }
                stopDiscovery();
                remoteSupported = msg.optBoolean("remote_controls", false);
                connected = true; info.setText("Connected. Load a file from the Windows controller."); status(); return;
            }
            if (op.equals("coordinator")) { coordinator(msg); return; }
            if (op.equals("remote_result")) {
                if (remote.complete(msg.optLong("request", -1))) {
                    pendingRequest = -1; pendingTargetMs = -1;
                    JSONObject state = msg.optJSONObject("coordinator");
                    if (state != null) coordinator(state);
                    if (!msg.optBoolean("ok")) Toast.makeText(this, msg.optString("error", "Playback command failed"), Toast.LENGTH_LONG).show();
                    showTransport();
                }
                return;
            }
            if (msg.has("error") && id < 0) throw new IllegalStateException(msg.getString("error"));
            long incomingEpoch = msg.optLong("epoch", playback.epoch());
            boolean epochChanged = playback.accept(incomingEpoch);
            if (!op.equals("speed")) { cancelStart(); player.pause(); player.setPlaybackSpeed(1f); }
            if (epochChanged) installFrameListener();
            switch (op) {
                case "pause": break;
                case "load": {
                    resetRemote();
                    error = ""; loading = true; seekPending = true;
                    droppedVideoFrames = 0; transferMbps = -1; transferSampleNs = 0;
                    String url = msg.getString("url");
                    android.net.Uri uri = android.net.Uri.parse(url);
                    if (!"http".equals(uri.getScheme())) throw new IllegalArgumentException("Only host HTTP media is supported");
                    String suffix = uri.getLastPathSegment();
                    String mime = "mkv".equals(suffix) ? MimeTypes.VIDEO_MATROSKA :
                        "mp4".equals(suffix) ? MimeTypes.VIDEO_MP4 : MimeTypes.VIDEO_MP2T;
                    player.setMediaItem(new MediaItem.Builder().setUri(uri).setMimeType(mime).build(), msg.optLong("position_ms", 0));
                    player.prepare();
                    seekCompletion();
                    setup.setVisibility(View.GONE);
                    break;
                }
                case "seek":
                    seekPending = true; installFrameListener();
                    player.seekTo(Math.max(0, msg.getLong("position_ms"))); seekCompletion(); break;
                case "arm": {
                    if (seekPending || loading || player.getPlaybackState() != Player.STATE_READY)
                        throw new IllegalStateException("Video not ready");
                    long target = msg.getLong("host_ns") + msg.getLong("offset_ns");
                    long delta = target - System.nanoTime();
                    if (delta < 100_000_000L || delta > 10_000_000_000L)
                        throw new IllegalStateException("Start deadline invalid or late");
                    final long startGeneration = playback.generation();
                    scheduled = new Runnable() {
                        @Override public void run() {
                            if (!playback.matches(startGeneration) || !connected) return;
                            long left = target - System.nanoTime();
                            if (left > 1_000_000L) { main.postDelayed(this, Math.max(1, left / 1_000_000L - 1)); return; }
                            scheduled = null;
                            if (player.getPlaybackState() != Player.STATE_READY || seekPending) {
                                error = "Video became unready at start"; status(); return;
                            }
                            player.play(); status();
                        }
                    };
                    main.postDelayed(scheduled, Math.max(1, delta / 1_000_000L - 1));
                    break;
                }
                case "speed": {
                    double value = msg.getDouble("value");
                    if (!Double.isFinite(value) || value < .995 || value > 1.005)
                        throw new IllegalArgumentException("Video speed outside servo bounds");
                    player.setPlaybackSpeed((float)value); break;
                }
                default: throw new IllegalArgumentException("Unknown command: " + op);
            }
            if (id >= 0) client.send(new JSONObject().put("reply", id).put("epoch", playback.epoch()));
            updateTransport();
            status();
        } catch (Exception e) {
            cancelStart(); player.pause();
            try { if (id >= 0) client.send(new JSONObject().put("reply", id).put("error", String.valueOf(e.getMessage()))); }
            catch (JSONException ignored) {}
        }
    }

    private void seekCompletion() {
        final long serial = ++seekSerial, generation = playback.generation();
        // Wait for asynchronous Media3 seek processing and fresh READY state.
        main.postDelayed(new Runnable() {
            @Override public void run() {
                if (destroyed || serial != seekSerial || !playback.matches(generation)) return;
                if (player.getPlaybackState() == Player.STATE_READY && !player.isLoading()) {
                    seekPending = false; status();
                } else if (player.getPlaybackState() == Player.STATE_READY) {
                    // isLoading also covers harmless background prefetch.
                    seekPending = false; status();
                } else if (player.getPlayerError() == null) main.postDelayed(this, 50);
            }
        }, 150);
    }

    private void cancelStart() {
        if (scheduled != null) main.removeCallbacks(scheduled);
        scheduled = null;
    }

    private String stateName() {
        switch (player.getPlaybackState()) {
            case Player.STATE_BUFFERING: return "buffering";
            case Player.STATE_READY: return "ready";
            case Player.STATE_ENDED: return "ended";
            default: return "idle";
        }
    }

    private void status() {
        if (!connected || client == null || destroyed) return;
        try {
            JSONObject s = new JSONObject().put("op", "status").put("epoch", playback.epoch())
                .put("state", stateName()).put("position_ms", player.getCurrentPosition())
                .put("buffered_ms", player.getBufferedPosition()).put("playing", player.isPlaying())
                .put("speed", player.getPlaybackParameters().speed).put("seek_pending", seekPending)
                .put("error", error).put("frame", frame).put("decoder", decoderName)
                .put("heap_limit_mb", Runtime.getRuntime().maxMemory() / (1024 * 1024))
                .put("buffer_budget_mb", bufferBudgetBytes / (1024 * 1024))
                .put("dropped_video_frames", droppedVideoFrames)
                .put("transfer_mbps", transferMbps >= 0 ? transferMbps : JSONObject.NULL)
                .put("transfer_age_ms", transferSampleNs > 0 ? (System.nanoTime() - transferSampleNs) / 1000000.0 : JSONObject.NULL)
                .put("display_hdr_types", new JSONArray(hdrTypes))
                .put("decoders", capabilities).put("sample_ns", System.nanoTime());
            client.send(s);
        } catch (JSONException ignored) {}
    }

    private final Runnable telemetry = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            // Reader's socket timeout is also a watchdog; this guards a stalled main connection.
            status(); updateTransport(); main.postDelayed(this, 100);
        }
    };

    private JSONArray codecCapabilities() {
        JSONArray result = new JSONArray();
        for (MediaCodecInfo codec : new MediaCodecList(MediaCodecList.ALL_CODECS).getCodecInfos()) {
            if (codec.isEncoder()) continue;
            for (String type : codec.getSupportedTypes()) {
                if (!type.equals("video/hevc") && !type.equals("video/dolby-vision")) continue;
                try {
                    JSONArray profiles = new JSONArray();
                    for (MediaCodecInfo.CodecProfileLevel p : codec.getCapabilitiesForType(type).profileLevels)
                        profiles.put(new JSONObject().put("profile", p.profile).put("level", p.level));
                    result.put(new JSONObject().put("name", codec.getName()).put("mime", type)
                        .put("profiles", profiles).put("hardware", Build.VERSION.SDK_INT >= 29 ? codec.isHardwareAccelerated() : JSONObject.NULL));
                } catch (Exception ignored) {}
            }
        }
        return result;
    }

    @Override public void onBackPressed() {
        if (remote.hasPreview()) { main.removeCallbacks(commitSeek); remote.clearPreview(); showTransport(); return; }
        setup.setVisibility(setup.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE);
        updateTransport();
    }

    @Override protected void onStop() {
        foreground = false; stopDiscovery(); connecting = false;
        if (codeDialog != null) codeDialog.dismiss();
        super.onStop(); cancelStart(); resetRemote(); player.pause();
        if (client != null) client.close(); connected = false;
        setup.setVisibility(View.VISIBLE); info.setText("Playback stopped. Reconnect and reload to continue.");
    }

    @Override protected void onStart() { super.onStart(); autoAttempted.clear(); foreground = true; }

    @Override protected void onResume() {
        super.onResume();
        if (discovery == null && !connected && !connecting
            && (codeDialog == null || !codeDialog.isShowing())) startDiscovery(false);
    }

    @Override protected void onDestroy() {
        destroyed = true; main.removeCallbacksAndMessages(null);
        stopDiscovery();
        if (client != null) client.close();
        player.release(); super.onDestroy();
    }
}
