package dev.dualtheater.calibration;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.*;
import android.os.*;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import android.view.TextureView;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Foreground-only capture. No images/PCM are written to disk or sent over the network. */
final class CaptureController implements AutoCloseable {
    interface Listener {
        void ready();
        void progress(int flashes, int tones);
        void measured(double[][] pairs);
        void error(String reason);
    }
    private final Context context;
    private final TextureView preview;
    private final Listener listener;
    private final MeasurementEngine engine = new MeasurementEngine();
    private final AudioTimeline timeline = new AudioTimeline();
    private final AtomicBoolean ready = new AtomicBoolean(), delivered = new AtomicBoolean(), failed = new AtomicBoolean();
    private final Object resources = new Object();
    private final TreeMap<Long, long[]> metadata = new TreeMap<>();
    private final TreeMap<Long, Double> luminance = new TreeMap<>();
    private final HandlerThread cameraThread = new HandlerThread("calibration-camera");
    private Handler cameraHandler;
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader images;
    private Surface previewSurface;
    private AudioRecord audio;
    private CaptureRequest.Builder request;
    private Rect activeArray;
    private volatile boolean closed, collecting, exposureLocked;
    private long lockAfterNs, openedNs, beginNs, lastProgress;

    CaptureController(Context context, TextureView preview, Listener listener) {
        this.context = context; this.preview = preview; this.listener = listener;
    }

    @SuppressLint("MissingPermission")
    void start() {
        if (context.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
            || context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            fail("Camera and microphone permission are required"); return;
        }
        if (!preview.isAvailable()) { fail("Camera preview is not ready; retry"); return; }
        cameraThread.start(); cameraHandler = new Handler(cameraThread.getLooper());
        openedNs = SystemClock.elapsedRealtimeNanos();
        try {
            CameraManager manager = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            String selected = null;
            CameraCharacteristics characteristics = null;
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics candidate = manager.getCameraCharacteristics(id);
                Integer facing = candidate.get(CameraCharacteristics.LENS_FACING);
                Integer clock = candidate.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE);
                if (facing != null && facing == CameraCharacteristics.LENS_FACING_BACK
                    && clock != null && clock == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                    && Boolean.TRUE.equals(candidate.get(CameraCharacteristics.CONTROL_AE_LOCK_AVAILABLE))) {
                    selected = id; characteristics = candidate; break;
                }
            }
            if (selected == null) throw new IllegalStateException("This phone needs a rear camera with comparable capture timestamps and exposure lock");
            activeArray = characteristics.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            if (activeArray == null) throw new IllegalStateException("Camera sensor geometry is unavailable");
            StreamConfigurationMap map = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            if (map == null) throw new IllegalStateException("Camera output formats unavailable");
            Size chosen = null;
            for (Size size : map.getOutputSizes(ImageFormat.YUV_420_888)) {
                if (size.getWidth() >= 320 && size.getWidth() <= 1280 && size.getHeight() <= 720
                    && map.getOutputMinFrameDuration(ImageFormat.YUV_420_888, size) <= 34_000_000L
                    && (chosen == null || Math.abs(size.getWidth() * size.getHeight() - 640 * 480)
                        < Math.abs(chosen.getWidth() * chosen.getHeight() - 640 * 480))) chosen = size;
            }
            if (chosen == null) throw new IllegalStateException("No suitable 30 fps camera analysis stream");
            Range<Integer> fps = null;
            Range<Integer>[] ranges = characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
            if (ranges != null) for (Range<Integer> range : ranges) {
                if (range.getLower() >= 30 && range.getUpper() <= 60
                    && map.getOutputMinFrameDuration(ImageFormat.YUV_420_888, chosen) <= 1_000_000_000L / range.getUpper()
                    && (fps == null || range.getUpper() > fps.getUpper())) fps = range;
            }
            if (fps == null) throw new IllegalStateException("A stable 30–60 fps camera mode is required");
            images = ImageReader.newInstance(chosen.getWidth(), chosen.getHeight(), ImageFormat.YUV_420_888, 4);
            images.setOnImageAvailableListener(this::imageAvailable, cameraHandler);
            preview.getSurfaceTexture().setDefaultBufferSize(chosen.getWidth(), chosen.getHeight());
            previewSurface = new Surface(preview.getSurfaceTexture());
            final Range<Integer> targetFps = fps;
            manager.openCamera(selected, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) {
                    synchronized (resources) {
                        if (closed) { device.close(); return; }
                        camera = device;
                    }
                    try {
                        request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                        request.addTarget(images.getSurface()); request.addTarget(previewSurface);
                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, targetFps);
                        device.createCaptureSession(Arrays.asList(images.getSurface(), previewSurface), new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession value) {
                                synchronized (resources) {
                                    if (closed) { value.close(); return; }
                                    session = value;
                                }
                                try { session.setRepeatingRequest(request.build(), captures, cameraHandler); }
                                catch (Exception error) { fail("Could not start camera capture"); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession value) { fail("Camera cannot run preview and timestamped analysis together"); }
                        }, cameraHandler);
                    } catch (Exception error) { fail("Camera capture setup failed"); }
                }
                @Override public void onDisconnected(CameraDevice device) { device.close(); fail("Camera disconnected"); }
                @Override public void onError(CameraDevice device, int error) { device.close(); fail("Camera is unavailable; close other camera apps and retry"); }
            }, cameraHandler);
            new Thread(this::captureAudio, "calibration-microphone").start();
            cameraHandler.postDelayed(() -> { if (!ready.get() && !closed) fail("Capture timing did not stabilize; brighten the TV and retry"); }, 12000);
        } catch (Exception error) { fail(error.getMessage() == null ? "Camera setup failed" : error.getMessage()); }
    }

    private final CameraCaptureSession.CaptureCallback captures = new CameraCaptureSession.CaptureCallback() {
        @Override public void onCaptureCompleted(CameraCaptureSession session, CaptureRequest unused, TotalCaptureResult result) {
            if (closed) return;
            try {
                long now = SystemClock.elapsedRealtimeNanos();
                Integer ae = result.get(CaptureResult.CONTROL_AE_STATE);
                if (!exposureLocked && now - openedNs > 1_000_000_000L && ae != null
                    && (ae == CaptureResult.CONTROL_AE_STATE_CONVERGED || ae == CaptureResult.CONTROL_AE_STATE_FLASH_REQUIRED)) {
                    request.set(CaptureRequest.CONTROL_AE_LOCK, true);
                    session.setRepeatingRequest(request.build(), this, cameraHandler);
                    exposureLocked = true; lockAfterNs = now + 500_000_000;
                }
                Long stamp = result.get(CaptureResult.SENSOR_TIMESTAMP), exposure = result.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                Long skew = result.get(CaptureResult.SENSOR_ROLLING_SHUTTER_SKEW);
                Rect crop = result.get(CaptureResult.SCALER_CROP_REGION);
                if (!exposureLocked || stamp == null || stamp < lockAfterNs) return;
                if (!Boolean.TRUE.equals(result.get(CaptureResult.CONTROL_AE_LOCK))) return;
                if (exposure == null || skew == null || crop == null || exposure <= 0 || skew < 0
                    || Math.abs(now - stamp) > 2_000_000_000L) throw new IllegalStateException("Camera exposure timestamps are not usable on this phone");
                // Center 10% of output rows mapped into the reported active sensor array.
                double rowLo = (crop.top + crop.height() * .45 - activeArray.top) / activeArray.height();
                double rowHi = (crop.top + crop.height() * .55 - activeArray.top) / activeArray.height();
                metadata.put(stamp, new long[]{stamp + Math.round(rowLo * skew), stamp + Math.round(rowHi * skew) + exposure});
                consume(stamp);
                while (metadata.size() > 24) metadata.pollFirstEntry();
            } catch (Exception error) { fail(error.getMessage() == null ? "Camera timestamp failure" : error.getMessage()); }
        }
    };

    private void imageAvailable(ImageReader reader) {
        if (closed) return;
        try {
            Image image;
            while ((image = reader.acquireNextImage()) != null) {
                try {
                    if (!exposureLocked) continue;
                    Image.Plane plane = image.getPlanes()[0];
                    ByteBuffer bytes = plane.getBuffer();
                    Rect crop = image.getCropRect();
                    int x0 = crop.left + crop.width() * 4 / 10, x1 = crop.left + crop.width() * 6 / 10;
                    int y0 = crop.top + crop.height() * 45 / 100, y1 = crop.top + crop.height() * 55 / 100;
                    double sum = 0; int count = 0, origin = bytes.position();
                    for (int y = y0; y < y1; y += 4) for (int x = x0; x < x1; x += 4) {
                        sum += bytes.get(origin + y * plane.getRowStride() + x * plane.getPixelStride()) & 255; count++;
                    }
                    if (count > 0) { luminance.put(image.getTimestamp(), sum / count); consume(image.getTimestamp()); }
                    while (luminance.size() > 24) luminance.pollFirstEntry();
                } finally { image.close(); }
            }
        } catch (Exception error) { fail(error.getMessage() == null ? "Camera analysis failed" : error.getMessage()); }
    }

    private void consume(long stamp) {
        if (!metadata.containsKey(stamp) || !luminance.containsKey(stamp)) return;
        long[] span = metadata.remove(stamp);
        engine.frame(luminance.remove(stamp), span[0], span[1]);
        update();
    }

    @SuppressLint("MissingPermission")
    private void captureAudio() {
        try {
            if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                throw new IllegalStateException("Microphone permission is required");
            AudioManager manager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            int source = "true".equals(manager.getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED))
                ? MediaRecorder.AudioSource.UNPROCESSED : MediaRecorder.AudioSource.VOICE_RECOGNITION;
            int minimum = AudioRecord.getMinBufferSize(48000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("48 kHz microphone capture unavailable");
            AudioRecord recorder = new AudioRecord.Builder().setAudioSource(source)
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(48000).setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(Math.max(19200, minimum * 4)).build();
            synchronized (resources) { if (closed) { recorder.release(); return; } audio = recorder; }
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("Microphone initialization failed");
            AudioDeviceInfo builtin = null;
            for (AudioDeviceInfo device : manager.getDevices(AudioManager.GET_DEVICES_INPUTS))
                if (device.getType() == AudioDeviceInfo.TYPE_BUILTIN_MIC) { builtin = device; break; }
            if (builtin == null || !recorder.setPreferredDevice(builtin)) throw new IllegalStateException("Built-in microphone is required");
            recorder.startRecording();
            AudioTimestamp timestamp = new AudioTimestamp();
            ToneDetector detector = new ToneDetector((lo, hi) -> {
                if (timeline.ready()) {
                    long error = timeline.errorNs();
                    engine.tone(timeline.time(lo) - error, timeline.time(hi) + error);
                    update();
                }
            });
            short[] block = new short[480]; long framesRead = 0, lastRead = SystemClock.elapsedRealtimeNanos();
            int reads = 0;
            while (!closed) {
                int count = recorder.read(block, 0, block.length, AudioRecord.READ_BLOCKING);
                if (closed) break;
                long now = SystemClock.elapsedRealtimeNanos();
                if (count <= 0 || now - lastRead > 150_000_000L)
                    throw new IllegalStateException("Microphone capture stalled; retry");
                lastRead = now; framesRead += count;
                if (++reads % 10 == 0) {
                    AudioDeviceInfo route = recorder.getRoutedDevice();
                    if (route == null || route.getType() != AudioDeviceInfo.TYPE_BUILTIN_MIC)
                        throw new IllegalStateException("Microphone route changed; use the built-in microphone");
                    if (recorder.getTimestamp(timestamp, AudioTimestamp.TIMEBASE_BOOTTIME) == AudioRecord.SUCCESS) {
                        if (Math.abs(timestamp.framePosition - framesRead) > recorder.getBufferSizeInFrames() * 2L)
                            throw new IllegalStateException("Microphone samples no longer match capture timestamps");
                        timeline.add(timestamp.framePosition, timestamp.nanoTime);
                    }
                }
                detector.accept(block, count); update();
            }
        } catch (Exception error) { if (!closed) fail(error.getMessage() == null ? "Microphone capture failed" : error.getMessage()); }
    }

    void begin() {
        if (!ready.get()) throw new IllegalStateException("Capture is not ready");
        engine.begin(); beginNs = SystemClock.elapsedRealtimeNanos(); collecting = true;
    }

    private synchronized void update() {
        if (closed || failed.get()) return;
        if (exposureLocked && engine.ready() && timeline.ready() && ready.compareAndSet(false, true)) listener.ready();
        long now = SystemClock.elapsedRealtimeNanos();
        if (now - lastProgress < 250_000_000L) return;
        lastProgress = now;
        listener.progress(engine.flashCount(), engine.toneCount());
        if (collecting) {
            if (now - beginNs > 75_000_000_000L) { fail("Test timed out; center the TV and retry"); return; }
            double[][] pairs = engine.pairs();
            if (pairs != null && delivered.compareAndSet(false, true)) { collecting = false; listener.measured(pairs); }
        }
    }

    private void fail(String reason) { if (!closed && failed.compareAndSet(false, true)) listener.error(reason); }

    @Override public void close() {
        closed = true;
        synchronized (resources) {
            if (audio != null) { try { audio.stop(); } catch (Exception ignored) {} audio.release(); audio = null; }
            if (session != null) session.close();
            if (camera != null) camera.close();
        }
        if (images != null) images.close();
        if (previewSurface != null) previewSurface.release();
        if (cameraHandler != null) cameraHandler.removeCallbacksAndMessages(null);
        cameraThread.quitSafely();
    }
}
