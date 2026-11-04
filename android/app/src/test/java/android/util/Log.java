package android.util;
/** JVM-only stand-in for Android's diagnostic sink, not packaged in the APK. */
public final class Log {
    public static int w(String tag, String message) { return 0; }
}
