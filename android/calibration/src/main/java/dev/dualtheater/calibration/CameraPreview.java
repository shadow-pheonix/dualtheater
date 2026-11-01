package dev.dualtheater.calibration;

import android.content.Context;
import android.graphics.Matrix;
import android.graphics.RectF;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.Looper;
import android.view.Display;
import android.view.TextureView;

/** Aspect-preserving Camera2 preview. Camera/analysis buffers are never rotated. */
final class CameraPreview extends TextureView {
    private int bufferWidth, bufferHeight, sensorDegrees;
    private PreviewGeometry geometry;
    private Runnable geometryChanged = () -> {};
    private final DisplayManager displays;
    private final DisplayManager.DisplayListener displayListener = new DisplayManager.DisplayListener() {
        @Override public void onDisplayAdded(int id) {}
        @Override public void onDisplayRemoved(int id) {}
        @Override public void onDisplayChanged(int id) {
            Display display = getDisplay();
            if (display != null && display.getDisplayId() == id) updateTransform();
        }
    };

    CameraPreview(Context context) {
        super(context); displays = (DisplayManager) context.getSystemService(Context.DISPLAY_SERVICE);
    }
    void setGeometryChanged(Runnable listener) { geometryChanged = listener; }
    void configure(int width, int height, int sensorOrientation) {
        bufferWidth = width; bufferHeight = height; sensorDegrees = sensorOrientation;
        updateTransform();
    }
    void guideBounds(RectF bounds) {
        if (geometry == null) bounds.set(getWidth() * .4f, getHeight() * .45f, getWidth() * .6f, getHeight() * .55f);
        else bounds.set(geometry.guideLeft, geometry.guideTop, geometry.guideRight, geometry.guideBottom);
    }
    private void updateTransform() {
        Display display = getDisplay();
        if (display == null || getWidth() <= 0 || getHeight() <= 0 || bufferWidth <= 0) return;
        geometry = new PreviewGeometry(getWidth(), getHeight(), bufferWidth, bufferHeight,
                                       sensorDegrees, display.getRotation() * 90);
        float cx = getWidth() / 2f, cy = getHeight() / 2f;
        Matrix matrix = new Matrix();
        matrix.setScale(geometry.scaleX, geometry.scaleY, cx, cy);
        matrix.postRotate(geometry.rotationDegrees, cx, cy);
        setTransform(matrix); geometryChanged.run();
    }
    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight); updateTransform();
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        displays.registerDisplayListener(displayListener, new Handler(Looper.getMainLooper()));
        updateTransform();
    }
    @Override protected void onDetachedFromWindow() {
        displays.unregisterDisplayListener(displayListener); super.onDetachedFromWindow();
    }
}
