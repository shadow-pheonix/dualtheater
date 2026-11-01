package dev.dualtheater.calibration;

/** Rear-camera geometry, independent of Android graphics for deterministic tests. */
final class PreviewGeometry {
    final float scaleX, scaleY, rotationDegrees;
    final float contentWidth, contentHeight, guideLeft, guideTop, guideRight, guideBottom;

    PreviewGeometry(int viewWidth, int viewHeight, int bufferWidth, int bufferHeight,
                    int sensorDegrees, int displayDegrees) {
        if (viewWidth <= 0 || viewHeight <= 0 || bufferWidth <= 0 || bufferHeight <= 0
            || sensorDegrees < 0 || sensorDegrees >= 360 || sensorDegrees % 90 != 0
            || displayDegrees < 0 || displayDegrees >= 360 || displayDegrees % 90 != 0)
            throw new IllegalArgumentException("Invalid preview geometry");
        boolean naturalSwap = sensorDegrees % 180 != 0;
        boolean displaySwap = (sensorDegrees - displayDegrees + 360) % 180 != 0;
        int naturalWidth = naturalSwap ? bufferHeight : bufferWidth;
        int naturalHeight = naturalSwap ? bufferWidth : bufferHeight;
        int orientedWidth = displaySwap ? bufferHeight : bufferWidth;
        int orientedHeight = displaySwap ? bufferWidth : bufferHeight;
        float fit = Math.min((float)viewWidth / orientedWidth, (float)viewHeight / orientedHeight);
        // TextureView already applies the sensor's natural orientation, then
        // stretches to the view. Undo that stretch, fit, then undo display rotation.
        scaleX = naturalWidth * fit / viewWidth;
        scaleY = naturalHeight * fit / viewHeight;
        rotationDegrees = -displayDegrees;
        contentWidth = orientedWidth * fit; contentHeight = orientedHeight * fit;
        // Analysis remains the central 20% x 10% of the unrotated YUV image.
        float guideWidth = (displaySwap ? bufferHeight * .1f : bufferWidth * .2f) * fit;
        float guideHeight = (displaySwap ? bufferWidth * .2f : bufferHeight * .1f) * fit;
        guideLeft = (viewWidth - guideWidth) / 2; guideRight = (viewWidth + guideWidth) / 2;
        guideTop = (viewHeight - guideHeight) / 2; guideBottom = (viewHeight + guideHeight) / 2;
    }
}
