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
import androidx.media3.common.text.CueGroup;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.exoplayer.*;
import androidx.media3.exoplayer.analytics.AnalyticsListener;
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector;
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory;
import androidx.media3.ui.SubtitleView;
import androidx.media3.exoplayer.video.VideoFrameMetadataListener;
import androidx.media3.exoplayer.upstream.DefaultAllocator;
import dev.dualtheater.shared.StorageShare;
import org.json.*;
import java.util.*;

/** Video-only SurfaceView playback. Every player access stays on the main looper. */
@UnstableApi
public final class MainActivity extends Activity {
    private final Handler main = new Handler(Looper.getMainLooper());
    private ExoPlayer player;
    private SurfaceView surface;
    private SubtitleView subtitleView;
    private FrameLayout root;
    private float videoAspect = 16f / 9f;
    private LinearLayout setup;
    private LinearLayout advanced, discoveryPanel, hostList;
    private HostDiscovery discovery;
    private final Map<String, DiscoveredHost> foundHosts = new LinkedHashMap<>();
    private final Map<String, Button> hostButtons = new LinkedHashMap<>();
    private final Set<String> autoAttempted = new HashSet<>();
    private DiscoveredHost selectedHost;
    private boolean connecting, authRequired;
    private volatile boolean foreground;
    private AlertDialog codeDialog;
    private TextView info;
    private EditText hostInput, portInput, tokenInput;
    private volatile ControlClient client;
    private TimingClient timingClient;
    private boolean timingReconnecting;
    private static final String TIMING_ERROR = "Timing connection lost; reconnecting. Playback remains paused.";
    private final RemoteTimeline audioTimeline = new RemoteTimeline();
    private final FrameObservations observations = new FrameObservations();
    private final java.util.concurrent.atomic.AtomicLong frameSequence = new java.util.concurrent.atomic.AtomicLong();
    private AudioClockRenderer audioClockRenderer;
    private String syncMode = "baseline";
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
    private volatile boolean destroyed = false;
    private int bufferBudgetBytes;
    private DefaultAllocator bufferAllocator;
    private ReadAheadCache readAheadCache;
    private long droppedVideoFrames;
    private double transferMbps = -1;
    private long transferSampleNs;
    private final RemoteControls remote = new RemoteControls();
    private StorageShare storageShare;
    private long clientRequestId = 0;
    private long latestProvidersRequest = -1, latestBrowseRequest = -1;
    private static final class ClientRequest {
        final String action;
        final long viewGeneration, epoch, mediaGeneration;
        ClientRequest(String action, long viewGeneration, long epoch, long mediaGeneration) {
            this.action = action; this.viewGeneration = viewGeneration; this.epoch = epoch; this.mediaGeneration = mediaGeneration;
        }
    }
    private final Map<Long, ClientRequest> clientRequests = new HashMap<>();
    private long uiGeneration = 0, menuEpoch = -1, menuMediaGeneration = -1;
    private JSONObject clientState = new JSONObject();
    private String browserProvider = "windows", browserEntry = "";
    private final Deque<String> browserParents = new ArrayDeque<>();
    private TextView audioBadge;
    private String lastAudioBadge = "";
    private long lastMediaGeneration = -1;
    private long displayedBadgeGeneration = -1;
    private final Runnable hideAudioBadge = () -> { if (audioBadge != null) audioBadge.setVisibility(View.GONE); };
    private LinearLayout playbackMenu;
    private ScrollView playbackMenuScroll;
    private AlertDialog libraryDialog;
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
        subtitleView = new SubtitleView(this);
        subtitleView.setUserDefaultStyle(); subtitleView.setUserDefaultTextSize();
        subtitleView.setApplyEmbeddedStyles(true); subtitleView.setApplyEmbeddedFontSizes(true);
        subtitleView.setFocusable(false);
        root.addView(subtitleView, new FrameLayout.LayoutParams(-1, -1));
        setup = new LinearLayout(this); setup.setOrientation(LinearLayout.VERTICAL);
        setup.setPadding(dp(36), dp(22), dp(36), dp(22)); setup.setBackgroundColor(0xee101827);
        TextView title = new TextView(this); title.setText("DualTheater TV"); title.setTextSize(30);
        title.setTextColor(0xfff4f7fb);
        setup.addView(title);
        SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        TextView help = new TextView(this);
        help.setText("CONNECT  •  Choose your laptop on the same home network. Pair once with its six-digit code.");
        help.setTextSize(18); help.setTextColor(0xffb8c6d9); setup.addView(help);
        Button browseHome = new Button(this); browseHome.setText("Browse movies");
        styleButton(browseHome);
        browseHome.setOnClickListener(v -> showProviders()); setup.addView(browseHome);
        Button shareFolder = new Button(this); shareFolder.setText("Share a TV folder");
        styleButton(shareFolder);
        shareFolder.setOnClickListener(v -> chooseStorageTree()); setup.addView(shareFolder);
        TextView libraryHelp = new TextView(this);
        libraryHelp.setText("LIBRARY  •  Browse shared laptop folders or choose a folder on this TV. The file stays on its device.");
        libraryHelp.setTextSize(15); libraryHelp.setTextColor(0xffb8c6d9); setup.addView(libraryHelp);
        TextView troubleshooting = new TextView(this);
        troubleshooting.setText("If the computer is missing, start DualTheater on Windows, use the same home network and allow it through the Windows firewall.");
        troubleshooting.setTextSize(15); troubleshooting.setTextColor(0xffb8c6d9); setup.addView(troubleshooting);
        discoveryPanel = new LinearLayout(this); discoveryPanel.setOrientation(LinearLayout.VERTICAL);
        setup.addView(discoveryPanel);
        DiscoveredHost remembered = rememberedHost();
        if (remembered != null) {
            Button reconnect = new Button(this); reconnect.setText("Reconnect to " + remembered.name);
            styleButton(reconnect);
            reconnect.setOnClickListener(v -> chooseHost(remembered, false)); discoveryPanel.addView(reconnect);
        }
        ScrollView hosts = new ScrollView(this); hosts.setFillViewport(false);
        hostList = new LinearLayout(this); hostList.setOrientation(LinearLayout.VERTICAL); hosts.addView(hostList);
        discoveryPanel.addView(hosts, new LinearLayout.LayoutParams(-1, dp(112)));
        Button refresh = new Button(this); refresh.setText("Find laptops");
        styleButton(refresh);
        refresh.setOnClickListener(v -> startDiscovery(true)); discoveryPanel.addView(refresh);
        Button showAdvanced = new Button(this); showAdvanced.setText("Advanced connection");
        styleButton(showAdvanced);
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
        styleButton(connect);
        connect.setOnClickListener(v -> { selectedHost = null; connect(); }); advanced.addView(connect);
        info = new TextView(this); info.setText("Searching for laptops on your home network…");
        setup.addView(info);
        root.addView(setup, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER));
        setContentView(root);
        createTransport();
        createAudioBadge();
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
            styleButton(button);
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

    private void styleButton(Button button) {
        android.graphics.drawable.StateListDrawable states = new android.graphics.drawable.StateListDrawable();
        GradientDrawable focused = new GradientDrawable(); focused.setColor(0xff45d7c8); focused.setCornerRadius(dp(10));
        GradientDrawable normal = new GradientDrawable(); normal.setColor(0xff1b293d); normal.setCornerRadius(dp(10));
        GradientDrawable pressed = new GradientDrawable(); pressed.setColor(0xff296c6a); pressed.setCornerRadius(dp(10));
        states.addState(new int[]{android.R.attr.state_pressed}, pressed);
        states.addState(new int[]{android.R.attr.state_focused}, focused);
        states.addState(new int[]{}, normal); button.setBackground(states);
        button.setTextColor(new ColorStateList(new int[][]{new int[]{android.R.attr.state_focused}, new int[]{}},
            new int[]{0xff101827, 0xfff4f7fb})); button.setMinHeight(dp(54)); button.setFocusable(true);
    }

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
        transportHint.setText(remoteSupported ? "← / →  Seek     •     OK  Play / pause     •     ↑  Options"
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
        if (playbackMenuScroll != null && playbackMenuScroll.getParent() == root) return super.dispatchKeyEvent(event);
        int key = event.getKeyCode();
        if (key == KeyEvent.KEYCODE_MENU || key == KeyEvent.KEYCODE_SETTINGS) {
            if (event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0) showPlaybackMenu("");
            return true;
        }
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
        if (key == KeyEvent.KEYCODE_DPAD_UP) {
            if (event.getAction() == KeyEvent.ACTION_DOWN && event.getRepeatCount() == 0) showPlaybackMenu("");
            return true;
        }
        if (key == KeyEvent.KEYCODE_DPAD_DOWN) {
            if (event.getAction() == KeyEvent.ACTION_DOWN) showTransport();
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    private void createPlayer() {
        DefaultRenderersFactory defaults = new DefaultRenderersFactory(this) {
            @Override protected androidx.media3.exoplayer.mediacodec.MediaCodecAdapter.Factory getCodecAdapterFactory() {
                return new ObservingCodecFactory(super.getCodecAdapterFactory(), observations);
            }
        }
            .setEnableDecoderFallback(true)
            .setMediaCodecSelector((mime, secure, tunnel) -> {
                List<androidx.media3.exoplayer.mediacodec.MediaCodecInfo> hardware = new ArrayList<>();
                for (androidx.media3.exoplayer.mediacodec.MediaCodecInfo codec :
                     MediaCodecSelector.DEFAULT.getDecoderInfos(mime, secure, tunnel)) {
                    if (codec.hardwareAccelerated && !codec.softwareOnly) hardware.add(codec);
                }
                return hardware;
            });
        RenderersFactory videoAndText = (handler, video, audio, text, metadata) -> {
            List<Renderer> out = new ArrayList<>();
            for (Renderer r : defaults.createRenderers(handler, video, audio, text, metadata)) {
                if (r.getTrackType() == C.TRACK_TYPE_VIDEO) {
                    audioClockRenderer = new AudioClockRenderer(r, audioTimeline);
                    out.add(audioClockRenderer);
                } else if (r.getTrackType() == C.TRACK_TYPE_TEXT) out.add(r);
            }
            return out.toArray(new Renderer[0]);
        };
        DefaultHttpDataSource.Factory http = new DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(5000).setReadTimeoutMs(10000).setUserAgent("DualTheater/0.1");
        DefaultHttpDataSource.Factory readAheadHttp = new DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(2000).setReadTimeoutMs(2500).setUserAgent("DualTheater/0.1");
        readAheadCache = new ReadAheadCache(this, http, readAheadHttp,
            !getIntent().getBooleanExtra("disable_read_ahead", false));
        // Keep most of the Java heap available for the player, extractor
        // and UI rather than filling the heap with buffered samples.
        bufferBudgetBytes = (int)Math.max(8L * 1024 * 1024,
            Math.min(64L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 4));
        bufferAllocator = new DefaultAllocator(true, C.DEFAULT_BUFFER_SEGMENT_SIZE);
        DefaultLoadControl load = new DefaultLoadControl.Builder()
            .setAllocator(bufferAllocator)
            .setBufferDurationsMs(15000, 45000, 3000, 5000)
            .setTargetBufferBytes(bufferBudgetBytes)
            .setPrioritizeTimeOverSizeThresholds(false).build();
        player = new ExoPlayer.Builder(this, videoAndText)
            .setMediaSourceFactory(new DefaultMediaSourceFactory(readAheadCache.foregroundFactory()))
            .setLoadControl(load).build();
        player.setTrackSelectionParameters(player.getTrackSelectionParameters().buildUpon()
            .setTrackTypeDisabled(C.TRACK_TYPE_AUDIO, true)
            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true).build());
        player.setVideoSurfaceView(surface);
        player.setVideoScalingMode(C.VIDEO_SCALING_MODE_SCALE_TO_FIT);
        player.setVideoChangeFrameRateStrategy(C.VIDEO_CHANGE_FRAME_RATE_STRATEGY_ONLY_IF_SEAMLESS);
        player.setSeekParameters(SeekParameters.EXACT);
        player.addListener(new Player.Listener() {
            @Override public void onCues(CueGroup cueGroup) { subtitleView.setCues(cueGroup.cues); }
            @Override public void onTracksChanged(Tracks tracks) { updateSubtitleState(); status(); }
            @Override public void onVideoSizeChanged(VideoSize size) {
                if (size.height > 0) {
                    videoAspect = size.width * size.pixelWidthHeightRatio / size.height;
                    fitSurface();
                }
            }
            @Override public void onPlaybackStateChanged(int state) {
                readAheadCache.playbackReady(!seekPending && (state == Player.STATE_READY
                    || state == Player.STATE_BUFFERING && !loading));
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
        subtitleView.setLayoutParams(new FrameLayout.LayoutParams(width, height, Gravity.CENTER));
    }

    private long nextClientId() { return ++clientRequestId; }

    private long requestClient(String action, JSONObject fields) {
        if (!connected || client == null) {
            Toast.makeText(this, "Connect to a Windows computer first.", Toast.LENGTH_LONG).show();
            return -1;
        }
        if (clientRequests.size() >= 64) {
            Toast.makeText(this, "Too many computer requests are still pending. Wait a moment and retry.", Toast.LENGTH_LONG).show();
            return -1;
        }
        try {
            long id = nextClientId();
            JSONObject message = new JSONObject().put("op", "client_request").put("id", id).put("action", action);
            if (fields != null) {
                java.util.Iterator<String> keys = fields.keys();
                while (keys.hasNext()) { String key = keys.next(); message.put(key, fields.get(key)); }
            }
            long requestEpoch = -1, requestMediaGeneration = -1;
            if (action.equals("track") || action.equals("subtitle") || action.equals("play")
                || action.equals("pause") || action.equals("seek") || action.equals("resync")) {
                long currentEpoch = clientState.optLong("epoch", playback.epoch());
                long currentMediaGeneration = clientState.optLong("media_generation", -1);
                requestEpoch = fields != null && fields.has("epoch") ? fields.optLong("epoch", -1) : currentEpoch;
                requestMediaGeneration = fields != null && fields.has("media_generation")
                    ? fields.optLong("media_generation", -1) : currentMediaGeneration;
                if (requestEpoch < 0 || requestMediaGeneration < 0
                    || (currentMediaGeneration >= 0 && (requestEpoch != currentEpoch || requestMediaGeneration != currentMediaGeneration))) {
                    Toast.makeText(this, "The movie changed. Open playback options again.", Toast.LENGTH_LONG).show();
                    return -1;
                }
                message.put("epoch", requestEpoch).put("media_generation", requestMediaGeneration);
            }
            ClientRequest request = new ClientRequest(action, uiGeneration, requestEpoch, requestMediaGeneration);
            clientRequests.put(id, request); client.send(message);
            main.postDelayed(() -> {
                ClientRequest pending = clientRequests.remove(id);
                if (pending != null && !destroyed && pending.viewGeneration == uiGeneration
                    && (pending.mediaGeneration < 0 || pending.mediaGeneration == clientState.optLong("media_generation", -1)))
                    Toast.makeText(this, "The computer did not finish that request.", Toast.LENGTH_LONG).show();
            }, 30000);
            return id;
        } catch (JSONException e) {
            Toast.makeText(this, "Could not send request.", Toast.LENGTH_LONG).show();
            return -1;
        }
    }

    private void showProviders() {
        if (!connected) { Toast.makeText(this, "Connect to the Windows computer to browse its shared folders.", Toast.LENGTH_LONG).show(); return; }
        uiGeneration++;
        latestProvidersRequest = requestClient("providers", null);
    }

    private void showBrowseMenu() {
        if (!connected) { Toast.makeText(this, "Connect to browse movies.", Toast.LENGTH_LONG).show(); return; }
        JSONArray available = clientState.optJSONArray("providers");
        if (available == null || available.length() == 0) { showProviders(); return; }
        List<String> labels = new ArrayList<>(); List<String> ids = new ArrayList<>();
        for (int i = 0; i < available.length(); i++) {
            JSONObject p = available.optJSONObject(i);
            if (p != null && p.optBoolean("available", false)) { labels.add(p.optString("label", "Library")); ids.add(p.optString("id", "windows")); }
        }
        if (ids.isEmpty()) { Toast.makeText(this, "No library providers are available.", Toast.LENGTH_LONG).show(); return; }
        String[] rows = labels.toArray(new String[0]);
        uiGeneration++;
        final long dialogGeneration = uiGeneration;
        if (libraryDialog != null && libraryDialog.isShowing()) libraryDialog.dismiss();
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("Browse movies")
            .setItems(rows, (d, which) -> { libraryDialog = null; browserProvider = ids.get(which); browserEntry = ""; browserParents.clear(); browse(browserProvider, "", 0); })
            .setNegativeButton("Close", null).create();
        libraryDialog = dialog;
        dialog.setOnCancelListener(d -> { if (libraryDialog == dialog) libraryDialog = null; if (uiGeneration == dialogGeneration) uiGeneration++; });
        dialog.show();
    }

    private void browse(String provider, String entry, int cursor) {
        uiGeneration++;
        try { latestBrowseRequest = requestClient("browse", new JSONObject().put("provider", provider).put("entry", entry).put("cursor", cursor)); }
        catch (JSONException ignored) {}
    }

    private void showBrowseResult(JSONObject result) {
        browserProvider = result.optString("provider", browserProvider);
        browserEntry = result.optString("entry", "");
        JSONArray entries = result.optJSONArray("entries");
        if (entries == null) entries = new JSONArray();
        final JSONArray rows = entries;
        ArrayList<String> labels = new ArrayList<>();
        boolean canGoParent = !result.optString("parent", "").isEmpty() || !browserParents.isEmpty();
        if (canGoParent) labels.add("↑  Parent folder");
        for (int i = 0; i < rows.length(); i++) {
            JSONObject e = rows.optJSONObject(i);
            if (e == null) continue;
            labels.add((e.optBoolean("directory") ? "▸  " : "▶  ") + e.optString("name", "Item"));
        }
        final boolean hasMore = !result.isNull("next_cursor") && result.optInt("next_cursor", -1) >= 0;
        if (hasMore) labels.add("Load more…");
        String[] choices = labels.toArray(new String[0]);
        final long dialogGeneration = uiGeneration;
        if (libraryDialog != null && libraryDialog.isShowing()) libraryDialog.dismiss();
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(result.optString("label", "Library"))
            .setItems(choices, (d, which) -> {
                libraryDialog = null;
                int offset = 0;
                if (canGoParent) {
                    if (which == 0) {
                        String parent = result.optString("parent", "");
                        if (!browserParents.isEmpty()) {
                            String previous = browserParents.pop();
                            if (parent.isEmpty()) parent = previous;
                        }
                        browse(browserProvider, parent, 0); return;
                    }
                    offset = 1;
                }
                if (hasMore && which == labels.size() - 1) { browse(browserProvider, browserEntry, result.optInt("next_cursor", 0)); return; }
                JSONObject selected = rows.optJSONObject(which - offset);
                if (selected == null) return;
                String id = selected.optString("id", "");
                if (selected.optBoolean("directory")) {
                    browserParents.push(browserEntry); browse(browserProvider, id, 0);
                }
                else {
                    uiGeneration++;
                    try { requestClient("load_entry", new JSONObject().put("provider", browserProvider)
                        .put("entry", id).put("autoplay", true)); }
                    catch (JSONException ignored) {}
                }
            }).setNegativeButton("Close", null).create();
        libraryDialog = dialog;
        dialog.setOnCancelListener(d -> { if (libraryDialog == dialog) libraryDialog = null; if (uiGeneration == dialogGeneration) uiGeneration++; });
        dialog.show();
    }

    private void chooseStorageTree() {
        try {
            if (storageShare == null) storageShare = new StorageShare(this);
            startActivityForResult(storageShare.pickerIntent(), 4107);
        } catch (Exception e) { Toast.makeText(this, "Folder picker is unavailable: " + e.getMessage(), Toast.LENGTH_LONG).show(); }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != 4107 || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        try {
            int flags = data.getFlags() & (android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION | android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if ((flags & android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION) == 0)
                throw new SecurityException("The selected folder did not grant read access");
            getContentResolver().takePersistableUriPermission(data.getData(), android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION);
            if (storageShare == null) storageShare = new StorageShare(this);
            storageShare.setTree(data.getData());
            Toast.makeText(this, "TV folder saved. Connect to a computer to browse it.", Toast.LENGTH_LONG).show();
            if (connected && foreground) registerStorageShare();
        } catch (Exception e) { Toast.makeText(this, "Could not save the folder grant: " + e.getMessage(), Toast.LENGTH_LONG).show(); }
    }

    private void registerStorageShare() {
        if (!foreground || !connected || client == null) return;
        try {
            if (storageShare == null) storageShare = new StorageShare(this);
            if (!storageShare.hasTree()) return;
            JSONObject registration = storageShare.start();
            registration.put("id", nextClientId()).put("label", "TV storage");
            client.send(registration);
        } catch (Exception e) {
            Toast.makeText(this, "TV storage could not be shared: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void createAudioBadge() {
        audioBadge = new TextView(this); audioBadge.setTextColor(0xfff4f7fb); audioBadge.setTextSize(16);
        audioBadge.setGravity(Gravity.CENTER); audioBadge.setPadding(dp(14), dp(8), dp(14), dp(8));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(0xe61b293d); bg.setCornerRadius(dp(10)); audioBadge.setBackground(bg);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.RIGHT);
        lp.setMargins(0, dp(26), dp(28), 0); root.addView(audioBadge, lp); audioBadge.setVisibility(View.GONE);
    }

    private void showAudioBadge(String value, boolean force) {
        String label = value == null ? "" : value.trim();
        if (label.isEmpty() || (!force && label.equals(lastAudioBadge))) return;
        lastAudioBadge = label; audioBadge.setText(label);
        audioBadge.setVisibility(View.VISIBLE); main.removeCallbacks(hideAudioBadge); main.postDelayed(hideAudioBadge, 7500);
    }

    private void updateSubtitleState() {
        if (player == null) return;
        JSONArray tracks = new JSONArray(); String selected = "off"; int textGroup = 0;
        for (Tracks.Group group : player.getCurrentTracks().getGroups()) {
            if (group.getType() != C.TRACK_TYPE_TEXT) continue;
            for (int i = 0; i < group.length; i++) {
                String id = textGroup + ":" + i;
                boolean isSelected = group.isTrackSelected(i); if (isSelected) selected = id;
                if (tracks.length() >= 128 && !isSelected) continue;
                Format f = group.getTrackFormat(i);
                String language = StatusPayload.clip(f.language == null || f.language.equals("und") ? "" : f.language, 35);
                String codec = StatusPayload.clip(f.sampleMimeType, 64);
                String label = f.label == null || f.label.isEmpty() ? (language.isEmpty() ? "Subtitle " + (tracks.length() + 1) : language) : f.label;
                label = StatusPayload.clip(label, 120);
                try { tracks.put(new JSONObject().put("id", id).put("label", label).put("language", language)
                    .put("codec", codec).put("selected", isSelected).put("supported", group.isTrackSupported(i))
                    .put("format_label", codec)); } catch (JSONException ignored) {}
            }
            textGroup++;
        }
        try { clientState.put("local_subtitle_tracks", tracks).put("local_selected_subtitle", selected); } catch (JSONException ignored) {}
    }

    private boolean applySubtitle(String id) {
        if (id == null || id.equals("off")) {
            player.setTrackSelectionParameters(player.getTrackSelectionParameters().buildUpon()
                .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true).build());
            subtitleView.setCues(Collections.emptyList()); status(); return true;
        }
        String[] parts = id.split(":", -1);
        try {
            int targetGroup = Integer.parseInt(parts[0]), targetTrack = Integer.parseInt(parts[1]), g = 0;
            for (Tracks.Group group : player.getCurrentTracks().getGroups()) {
                if (group.getType() != C.TRACK_TYPE_TEXT) continue;
                if (g++ == targetGroup && targetTrack >= 0 && targetTrack < group.length && group.isTrackSupported(targetTrack)) {
                    player.setTrackSelectionParameters(player.getTrackSelectionParameters().buildUpon()
                        .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                        .setOverrideForType(new TrackSelectionOverride(group.getMediaTrackGroup(), targetTrack)).build());
                    status(); return true;
                }
            }
        } catch (Exception ignored) {}
        Toast.makeText(this, "That subtitle track is no longer available.", Toast.LENGTH_LONG).show();
        return false;
    }

    private JSONObject menuRequestFields(JSONObject values) throws JSONException {
        JSONObject fields = values == null ? new JSONObject() : new JSONObject(values.toString());
        fields.put("epoch", menuEpoch).put("media_generation", menuMediaGeneration);
        return fields;
    }

    private void closePlaybackMenu(boolean invalidateRequests) {
        if (playbackMenuScroll != null && playbackMenuScroll.getParent() == root) root.removeView(playbackMenuScroll);
        playbackMenuScroll = null; playbackMenu = null; menuEpoch = -1; menuMediaGeneration = -1;
        if (invalidateRequests) uiGeneration++;
    }

    private void showPlaybackMenu(String section) {
        if (playbackMenuScroll == null) {
            menuEpoch = clientState.optLong("epoch", playback.epoch());
            menuMediaGeneration = clientState.optLong("media_generation", -1);
        }
        if (playbackMenuScroll != null) root.removeView(playbackMenuScroll);
        playbackMenu = new LinearLayout(this); playbackMenu.setOrientation(LinearLayout.VERTICAL);
        playbackMenu.setPadding(dp(22), dp(16), dp(22), dp(16)); playbackMenu.setBackgroundColor(0xee1b293d);
        playbackMenu.setFocusable(false);
        playbackMenuScroll = new ScrollView(this); playbackMenuScroll.setFillViewport(false); playbackMenuScroll.setClipToPadding(false);
        playbackMenuScroll.addView(playbackMenu, new FrameLayout.LayoutParams(-1, -2));
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(430), -2, Gravity.RIGHT | Gravity.CENTER_VERTICAL);
        lp.height = Math.min(getResources().getDisplayMetrics().heightPixels - dp(48), dp(760));
        lp.setMargins(0, 0, dp(26), 0); root.addView(playbackMenuScroll, lp);
        TextView heading = new TextView(this); heading.setText(section.isEmpty() ? "Playback options" : section);
        heading.setTextSize(22); heading.setTextColor(0xff45d7c8); playbackMenu.addView(heading);
        if (section.isEmpty()) {
            menuButton("Audio track", () -> showPlaybackMenu("Audio track"));
            menuButton("Subtitles", () -> showPlaybackMenu("Subtitles"));
            menuButton("Browse movies", () -> { closePlaybackMenu(true); showBrowseMenu(); });
            menuButton("Resynchronize", () -> {
                try { requestClient("resync", menuRequestFields(null)); }
                catch (JSONException ignored) {}
            });
        } else if (section.equals("Audio track")) {
            JSONArray tracks = clientState.optJSONArray("audio_tracks");
            if (tracks == null || tracks.length() == 0) menuText("Audio tracks appear after a movie loads.");
            else for (int i = 0; i < tracks.length(); i++) {
                JSONObject track = tracks.optJSONObject(i); if (track == null) continue;
                String aid = track.optString("id", "");
                String label = track.optString("label", "Audio " + (i + 1));
                String format = track.optString("format_label", "");
                boolean supported = track.optBoolean("supported", false);
                String row = (supported ? (track.optBoolean("selected") ? "✓  " : "   ") : "Unsupported  •  ")
                    + label + (format.isEmpty() ? "" : "  •  " + format);
                Button button = menuButton(row, () -> {
                    try { requestClient("track", menuRequestFields(new JSONObject().put("aid", aid))); }
                    catch (JSONException ignored) {}
                    showPlaybackMenu("");
                });
                button.setEnabled(supported);
            }
        } else if (section.equals("Subtitles")) {
            JSONArray tracks = clientState.optJSONArray("subtitle_tracks");
            if (tracks == null || tracks.length() == 0) tracks = clientState.optJSONArray("local_subtitle_tracks");
            JSONArray options = tracks;
            boolean subtitlesOff = clientState.optString("selected_subtitle", "off").equals("off");
            menuButton((subtitlesOff ? "✓  " : "   ") + "Off", () -> {
                try { requestClient("subtitle", menuRequestFields(new JSONObject().put("sid", "off"))); }
                catch (JSONException ignored) {}
                showPlaybackMenu("");
            });
            if (options == null || options.length() == 0) menuText("No supported text subtitle tracks were found.");
            else for (int i = 0; i < options.length(); i++) {
                JSONObject track = options.optJSONObject(i); if (track == null || !track.optBoolean("supported", false)) continue;
                String sid = track.optString("id", ""); String label = track.optString("label", "Subtitle " + (i + 1));
                if (!track.optString("language", "").isEmpty()) label += "  •  " + track.optString("language");
                menuButton((track.optBoolean("selected") ? "✓  " : "   ") + label, () -> {
                    try { requestClient("subtitle", menuRequestFields(new JSONObject().put("sid", sid))); }
                    catch (JSONException ignored) {}
                    showPlaybackMenu("");
                });
            }
        }
        menuButton("Back", () -> showPlaybackMenu(""));
        for (int i = 0; i < playbackMenu.getChildCount(); i++) {
            View child = playbackMenu.getChildAt(i);
            if (child.isFocusable() && child.getVisibility() == View.VISIBLE) { child.requestFocus(); break; }
        }
    }

    private void menuText(String value) {
        TextView text = new TextView(this); text.setText(value); text.setTextColor(0xffb8c6d9); text.setTextSize(17);
        text.setPadding(dp(8), dp(10), dp(8), dp(10)); playbackMenu.addView(text);
    }

    private Button menuButton(String label, Runnable click) {
        Button button = new Button(this); button.setText(label); button.setTextSize(16);
        styleButton(button); button.setOnClickListener(v -> click.run());
        playbackMenu.addView(button, new LinearLayout.LayoutParams(-1, dp(54)));
        return button;
    }

    private void installFrameListener() {
        final long listenerEpoch = playback.epoch();
        final long sessionGeneration = playback.generation();
        final long generation = ++callbackGeneration;
        frame = new JSONObject();
        observations.clear();
        player.setVideoFrameMetadataListener((pts, release, format, mediaFormat) -> {
            if (!playback.matches(sessionGeneration) || generation != callbackGeneration) return;
            try {
                long sequence = frameSequence.incrementAndGet();
                observations.schedule(listenerEpoch, sequence, pts, release);
                frame = new JSONObject().put("epoch", listenerEpoch).put("position_ms", pts / 1000.0)
                    .put("sequence", sequence).put("kind", "scheduled_release")
                    .put("release_ns", release).put("valid", release != C.TIME_UNSET && release > 0)
                    .put("mime", format.sampleMimeType).put("codecs", format.codecs)
                    .put("width", format.width).put("height", format.height)
                    .put("color", String.valueOf(format.colorInfo));
            } catch (JSONException ignored) {}
        });
    }

    private void connect() {
        if (connecting) return;
        if (timingClient != null) timingClient.close();
        cancelStart(); player.pause(); ++seekSerial;
        resetRemote(); remoteSupported = false; coordinatorEpoch = -1; clientRequests.clear();
        closePlaybackMenu(true); if (libraryDialog != null) { libraryDialog.dismiss(); libraryDialog = null; }
        if (storageShare != null) storageShare.close();
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
                    clientRequests.clear(); if (storageShare != null) storageShare.close();
                    closePlaybackMenu(true); if (libraryDialog != null) { libraryDialog.dismiss(); libraryDialog = null; }
                    if (timingClient != null) timingClient.close();
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
                syncMode = msg.optString("sync_mode", "baseline");
                if (!syncMode.equals("baseline") && !syncMode.equals("servo") && !syncMode.equals("audio-clock"))
                    throw new IllegalArgumentException("Unsupported sync mode");
                player.createMessage(audioClockRenderer).setType(10001)
                    .setPayload(syncMode.equals("audio-clock")).send();
                audioTimeline.reset(0, 0, System.nanoTime());
                if (timingClient != null) timingClient.close();
                timingReconnecting = !syncMode.equals("baseline");
                if (!syncMode.equals("baseline")) {
                    final TimingClient timing = new TimingClient(); timingClient = timing;
                    boolean useDatagrams = "udp".equals(msg.optString("timing_transport"));
                    timing.connect(hostInput.getText().toString().trim(), useDatagrams
                            ? msg.getInt("timing_udp_port") : Integer.parseInt(portInput.getText().toString()),
                        msg.getString("timing_token"), audioTimeline, () -> main.post(() -> {
                            if (timingClient == timing && connected) {
                                timingReconnecting = false;
                                if (error.equals(TIMING_ERROR)) error = "";
                                status();
                            }
                        }), () -> main.post(() -> {
                            if (timingClient == timing && connected) {
                                timingReconnecting = true;
                                if (error.isEmpty() || error.equals(TIMING_ERROR)) error = TIMING_ERROR;
                                status();
                            }
                        }), useDatagrams, msg.optBoolean("timing_tcp_fallback", false)
                            ? Integer.parseInt(portInput.getText().toString()) : 0);
                }
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
                connected = true; clientState = new JSONObject(); clientRequests.clear();
                lastMediaGeneration = -1; displayedBadgeGeneration = -1; lastAudioBadge = "";
                info.setText("Connected. Browse a shared folder or load from the Windows controller.");
                // Refresh the catalog silently. Only an explicit Browse action
                // may open a dialog over a movie loaded from another client.
                registerStorageShare(); requestClient("providers", null); status(); return;
            }
            if (op.equals("client_state")) {
                JSONObject state = msg.optJSONObject("state");
                if (state != null) {
                    long generation = state.optLong("media_generation", -1);
                    long stateEpoch = state.optLong("epoch", -1);
                    boolean newMedia = lastMediaGeneration >= 0 && generation != lastMediaGeneration;
                    boolean staleMediaMenu = lastMediaGeneration >= 0
                        && (newMedia || stateEpoch != clientState.optLong("epoch", -1));
                    if (staleMediaMenu) closePlaybackMenu(true);
                    if (newMedia) { main.removeCallbacks(hideAudioBadge); audioBadge.setVisibility(View.GONE); }
                    lastMediaGeneration = generation;
                    clientState = state;
                    Object badge = state.opt("audio_badge");
                    String label = badge instanceof JSONObject ? ((JSONObject)badge).optString("label", "") : String.valueOf(badge == null || badge == JSONObject.NULL ? "" : badge);
                    if (state.optString("state", "").equals("playing") && !label.trim().isEmpty()
                        && (generation != displayedBadgeGeneration || !label.trim().equals(lastAudioBadge))) {
                        showAudioBadge(label, generation != displayedBadgeGeneration);
                        displayedBadgeGeneration = generation;
                    }
                    updateTransport();
                }
                return;
            }
            if (op.equals("client_response")) {
                long reply = msg.optLong("reply", -1); ClientRequest request = clientRequests.remove(reply);
                if (request == null) return;
                String action = request.action;
                boolean requestCurrent = request.viewGeneration == uiGeneration
                    && (request.mediaGeneration < 0 || (request.mediaGeneration == clientState.optLong("media_generation", -1)
                        && request.epoch == clientState.optLong("epoch", -1)));
                if (!msg.optBoolean("ok", false)) {
                    if (!requestCurrent) return;
                    String reason = msg.optString("error", "Computer request failed");
                    Toast.makeText(this, reason, Toast.LENGTH_LONG).show();
                    return;
                }
                JSONObject result = msg.optJSONObject("result");
                if (result == null) result = new JSONObject();
                if ("providers".equals(action)) {
                    if (!requestCurrent) return;
                    clientState = new JSONObject(clientState.toString());
                    clientState.put("providers", result.optJSONArray("providers") == null ? result.optJSONArray("entries") : result.optJSONArray("providers"));
                    if (reply == latestProvidersRequest) showBrowseMenu();
                } else if ("browse".equals(action) && requestCurrent && reply == latestBrowseRequest) showBrowseResult(result);
                return;
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
            if (op.equals("subtitle")) {
                long incoming = msg.optLong("epoch", playback.epoch());
                boolean ok = incoming == playback.epoch() && applySubtitle(msg.optString("sid", "off"));
                if (id >= 0) client.send(new JSONObject().put("reply", id).put("epoch", playback.epoch())
                    .put("error", ok ? "" : "Playback epoch changed or subtitle track unavailable"));
                return;
            }
            if (msg.has("error") && id < 0) throw new IllegalStateException(msg.getString("error"));
            long incomingEpoch = msg.optLong("epoch", playback.epoch());
            boolean epochChanged = playback.accept(incomingEpoch);
            if (!op.equals("speed")) { cancelStart(); player.pause(); player.setPlaybackSpeed(1f); }
            if (epochChanged) {
                audioTimeline.resetMillis(incomingEpoch, player.getCurrentPosition(), System.nanoTime());
                installFrameListener();
            }
            switch (op) {
                case "pause": break;
                case "load": {
                    readAheadCache.playbackReady(false);
                    closePlaybackMenu(true);
                    if (libraryDialog != null) { libraryDialog.dismiss(); libraryDialog = null; }
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
                    readAheadCache.playbackReady(false);
                    seekPending = true; installFrameListener();
                    player.seekTo(Math.max(0, msg.getLong("position_ms"))); seekCompletion(); break;
                case "arm": {
                    if (seekPending || loading || player.getPlaybackState() != Player.STATE_READY)
                        throw new IllegalStateException("Video not ready");
                    long target = syncMode.equals("baseline") ? msg.getLong("host_ns") + msg.getLong("offset_ns")
                        : msg.getLong("video_ns");
                    if (syncMode.equals("audio-clock")) audioTimeline.arm(playback.epoch(),
                        Math.round(msg.getDouble("position_ms") * 1000), msg.getLong("audio_ns"), target,
                        Math.round(msg.getDouble("video_lead_ms") * 1000), System.nanoTime());
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
                    if (syncMode.equals("audio-clock")) throw new IllegalArgumentException("Audio-clock mode owns video timing");
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
                    readAheadCache.playbackReady(true);
                    seekPending = false; status();
                } else if (player.getPlaybackState() == Player.STATE_READY) {
                    // isLoading also covers harmless background prefetch.
                    readAheadCache.playbackReady(true);
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
            updateSubtitleState();
            JSONObject s = new JSONObject().put("op", "status").put("epoch", playback.epoch())
                .put("state", stateName()).put("position_ms", player.getCurrentPosition())
                .put("buffered_ms", player.getBufferedPosition()).put("playing", player.isPlaying())
                .put("speed", player.getPlaybackParameters().speed).put("seek_pending", seekPending)
                .put("error", error).put("frame", frame).put("decoder", decoderName)
                .put("heap_limit_mb", Runtime.getRuntime().maxMemory() / (1024 * 1024))
                .put("buffer_budget_mb", bufferBudgetBytes / (1024 * 1024))
                .put("allocated_buffer_bytes", bufferAllocator.getTotalBytesAllocated())
                .put("total_buffered_ms", player.getTotalBufferedDuration())
                .put("native_loading", player.isLoading())
                .put("java_heap_used_mb", (Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory()) / (1024 * 1024))
                .put("dropped_video_frames", droppedVideoFrames)
                .put("transfer_mbps", transferMbps >= 0 ? transferMbps : JSONObject.NULL)
                .put("transfer_age_ms", transferSampleNs > 0 ? (System.nanoTime() - transferSampleNs) / 1000000.0 : JSONObject.NULL)
                .put("display_hdr_types", new JSONArray(hdrTypes))
                .put("decoders", capabilities).put("sample_ns", System.nanoTime())
                .put("sync_mode", syncMode).put("display_refresh_hz", getWindowManager().getDefaultDisplay().getRefreshRate());
            s.put("subtitle_tracks", clientState.optJSONArray("local_subtitle_tracks") == null ? new JSONArray() : clientState.optJSONArray("local_subtitle_tracks"));
            s.put("selected_subtitle", clientState.optString("local_selected_subtitle", "off"));
            s.put("timing_reconnecting", timingReconnecting);
            s.put("timing_error_only", timingReconnecting && error.equals(TIMING_ERROR));
            ReadAheadCache.Stats readAhead = readAheadCache.stats();
            s.put("read_ahead", new JSONObject().put("state", readAhead.state)
                .put("ahead_bytes", readAhead.aheadBytes).put("cache_bytes", readAhead.cacheBytes)
                .put("downloaded_bytes", readAhead.downloadedBytes).put("failures", readAhead.failures)
                .put("chunks", readAhead.chunks).put("cache_budget_bytes", readAhead.cacheBudgetBytes)
                .put("lookahead_bytes", readAhead.lookaheadBytes)
                .put("foreground_wait_ms", readAhead.foregroundWaitMs)
                .put("max_foreground_wait_ms", readAhead.maxForegroundWaitMs));
            long now = System.nanoTime();
            if (syncMode.equals("audio-clock")) s.put("remote_clock", new JSONObject()
                .put("state", audioTimeline.state(now)).put("phase_error_ms", audioTimeline.phaseMs())
                .put("max_dispatch_delay_ms", audioTimeline.maxDispatchDelayMs())
                .put("uncertainty_ms", audioTimeline.uncertaintyMs(now))
                .put("anchor_age_ms", audioTimeline.anchorAgeMs(now))
                .put("reads_recent", audioClockRenderer.recentlyRead(now))
                .put("renderer_error_ms", audioClockRenderer.rendererErrorMs()));
            FrameObservations.Sample rendered = observations.latest();
            if (rendered != null && rendered.epoch == playback.epoch()) s.put("rendered_frame", new JSONObject()
                .put("epoch", rendered.epoch).put("sequence", rendered.sequence)
                .put("position_ms", rendered.mediaUs / 1000.0).put("release_ns", rendered.releaseNs)
                .put("rendered_ns", rendered.renderedNs).put("received_ns", rendered.receivedNs));
            client.send(StatusPayload.bound(s));
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
        if (playbackMenuScroll != null && playbackMenuScroll.getParent() == root) { closePlaybackMenu(true); return; }
        if (remote.hasPreview()) { main.removeCallbacks(commitSeek); remote.clearPreview(); showTransport(); return; }
        setup.setVisibility(setup.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE);
        updateTransport();
    }

    @Override protected void onStop() {
        foreground = false; stopDiscovery(); connecting = false;
        if (codeDialog != null) codeDialog.dismiss();
        closePlaybackMenu(true); if (libraryDialog != null) { libraryDialog.dismiss(); libraryDialog = null; }
        if (readAheadCache != null) readAheadCache.suspend();
        super.onStop(); cancelStart(); resetRemote(); player.pause(); audioTimeline.stop(System.nanoTime());
        if (client != null) client.close(); connected = false;
        if (storageShare != null) storageShare.close();
        if (timingClient != null) timingClient.close();
        setup.setVisibility(View.VISIBLE); info.setText("Playback stopped. Reconnect and reload to continue.");
    }

    @Override protected void onStart() {
        super.onStart(); autoAttempted.clear(); foreground = true;
        if (readAheadCache != null) readAheadCache.resume();
    }

    @Override protected void onResume() {
        super.onResume();
        if (discovery == null && !connected && !connecting
            && (codeDialog == null || !codeDialog.isShowing())) startDiscovery(false);
    }

    @Override protected void onDestroy() {
        destroyed = true; main.removeCallbacksAndMessages(null);
        stopDiscovery();
        if (client != null) client.close();
        if (timingClient != null) timingClient.close();
        player.release();
        if (readAheadCache != null) readAheadCache.close();
        super.onDestroy();
    }
}
