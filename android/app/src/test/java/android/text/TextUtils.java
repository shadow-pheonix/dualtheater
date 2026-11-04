package android.text;
/** JVM-only implementation needed by Media3's language normalization, never packaged in the TV APK. */
public final class TextUtils {
    public static boolean isEmpty(CharSequence text) {return text==null || text.length()==0;}
}
