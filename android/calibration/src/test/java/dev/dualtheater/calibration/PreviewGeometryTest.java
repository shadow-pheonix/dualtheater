package dev.dualtheater.calibration;

import org.junit.Test;
import static org.junit.Assert.*;

public class PreviewGeometryTest {
    @Test public void landscapePhoneShowsWideImageWithoutStretching() {
        PreviewGeometry g = new PreviewGeometry(1000, 900, 640, 480, 90, 90);
        assertEquals(1000, g.contentWidth, .001);
        assertEquals(750, g.contentHeight, .001);
        assertEquals(-90, g.rotationDegrees, .001);
        assertEquals(400, g.guideLeft, .001);
        assertEquals(600, g.guideRight, .001);
        assertEquals(412.5, g.guideTop, .001);
        assertEquals(487.5, g.guideBottom, .001);
    }

    @Test public void oppositeLandscapeRotatesImageButKeepsCenteredGuide() {
        PreviewGeometry a = new PreviewGeometry(1000, 900, 640, 480, 90, 90);
        PreviewGeometry b = new PreviewGeometry(1000, 900, 640, 480, 90, 270);
        assertEquals(-270, b.rotationDegrees, .001);
        assertEquals(a.contentWidth, b.contentWidth, .001);
        assertEquals(a.guideLeft, b.guideLeft, .001);
        assertEquals(a.guideTop, b.guideTop, .001);
        double[] p = map(a, 100, 200, 1000, 900);
        double[] q = map(b, 100, 200, 1000, 900);
        assertEquals(1000, p[0] + q[0], .001);
        assertEquals(900, p[1] + q[1], .001);
    }

    @Test public void allSensorDisplayRotationsFitAndPreservePixelAspect() {
        for (int[] view : new int[][] {{1000, 900}, {1200, 400}, {500, 1000}}) {
            int w = view[0], h = view[1];
            for (int sensor = 0; sensor < 360; sensor += 90) for (int display = 0; display < 360; display += 90) {
                PreviewGeometry g = new PreviewGeometry(w, h, 640, 480, sensor, display);
                // Trace the actual default TextureView edges through the matrix.
                double[] origin = map(g, 0, 0, w, h), x = map(g, w, 0, w, h), y = map(g, 0, h, w, h);
                double xPixels = sensor % 180 == 0 ? 640 : 480;
                double yPixels = sensor % 180 == 0 ? 480 : 640;
                assertEquals(Math.hypot(x[0]-origin[0], x[1]-origin[1]) / xPixels,
                             Math.hypot(y[0]-origin[0], y[1]-origin[1]) / yPixels, .00001);
                assertTrue(g.contentWidth <= w + .001 && g.contentHeight <= h + .001);
                assertTrue(Math.abs(g.contentWidth-w) < .001 || Math.abs(g.contentHeight-h) < .001);
                assertEquals(w, g.guideLeft + g.guideRight, .001);
                assertEquals(h, g.guideTop + g.guideBottom, .001);
                // Raw central sensor ROI changes axes, never its area.
                double scale = g.contentWidth / ((sensor-display+360)%180 == 0 ? 640 : 480);
                assertEquals(128 * 48 * scale * scale,
                    (g.guideRight-g.guideLeft) * (g.guideBottom-g.guideTop), .02);
            }
        }
    }

    @Test public void invalidGeometryCannotBuildTransform() {
        try { new PreviewGeometry(0, 900, 640, 480, 90, 90); fail(); }
        catch (IllegalArgumentException expected) {}
        try { new PreviewGeometry(1000, 900, 640, 480, 45, 90); fail(); }
        catch (IllegalArgumentException expected) {}
    }

    private double[] map(PreviewGeometry g, double x, double y, int w, int h) {
        double dx = (x-w/2.0)*g.scaleX, dy = (y-h/2.0)*g.scaleY;
        double angle = Math.toRadians(g.rotationDegrees);
        return new double[] {w/2.0+dx*Math.cos(angle)-dy*Math.sin(angle),
                             h/2.0+dx*Math.sin(angle)+dy*Math.cos(angle)};
    }
}
