package dev.dualtheater.tv;

/** RPU-only JNI. No player, timestamps, filesystem or networking in native code. */
final class DolbyVisionNative implements DolbyVisionCompat.Engine {
    static { System.loadLibrary("dualtheater_dovi"); }
    private static native int inspectRpu(byte[] rpu);
    private static native byte[] convertRpu(byte[] rpu);
    @Override public int inspect(byte[] rpu) { return inspectRpu(rpu); }
    @Override public byte[] convert(byte[] rpu) { return convertRpu(rpu); }
}
