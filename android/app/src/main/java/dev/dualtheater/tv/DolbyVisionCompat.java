package dev.dualtheater.tv;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.function.Supplier;

/** FEL is determined from parsed RPU NLQ metadata, never from the filename or EL presence. */
final class DolbyVisionCompat {
    static final int MAX_SAMPLE = (int)Math.min(16L * 1024 * 1024,
        Math.max(2L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 16));
    static final int MAX_RPU = 65536;
    static final class Failure extends IllegalStateException {
        Failure(String message) { super(message); }
        Failure(String message, Throwable cause) { super(message, cause); }
    }
    interface Engine { int inspect(byte[] rpu); byte[] convert(byte[] rpu); }
    enum Mode { PROBING, NATIVE_MEL, CONVERT_FEL, NATIVE_UNKNOWN }
    private final Supplier<Engine> engineFactory;
    private Engine engine;
    private Mode mode = Mode.PROBING;
    long convertedRpus, droppedNals;
    private String reason = "Waiting for Profile 7 RPU metadata";
    DolbyVisionCompat(Supplier<Engine> factory) { engineFactory = factory; }
    Mode mode() { return mode; }
    String reason() { return reason; }
    void nativeUnknown(String why) { mode = Mode.NATIVE_UNKNOWN; reason = why; }
    private static final class Nal {
        final int start, payload, end, type, layer;
        Nal(byte[] data, int start, int payload, int end) {
            this.start=start; this.payload=payload; this.end=end;
            if (end-payload<2 || (data[payload]&0x80)!=0 || (data[payload+1]&7)==0)
                throw new IllegalArgumentException("Malformed HEVC NAL header");
            type=(data[payload]&0x7e)>>>1;
            layer=((data[payload]&1)<<5)|((data[payload+1]&0xf8)>>>3);
        }
    }
    private static int prefix(byte[] data, int at) {
        if (at+3>data.length || data[at]!=0 || data[at+1]!=0) return 0;
        if (data[at+2]==1) return 3;
        return at+4<=data.length && data[at+2]==0 && data[at+3]==1 ? 4 : 0;
    }
    private static List<Nal> nals(byte[] data) {
        if (data.length>MAX_SAMPLE) throw new IllegalArgumentException("HEVC sample exceeds compatibility limit");
        List<Nal> out=new ArrayList<>(); int start=0, length=prefix(data,0);
        if (length==0) throw new IllegalArgumentException("Expected Annex B HEVC sample");
        while (start<data.length) {
            int payload=start+length, end=payload;
            while (end<data.length && prefix(data,end)==0) end++;
            out.add(new Nal(data,start,payload,end));
            if (out.size()>8192) throw new IllegalArgumentException("Too many HEVC NAL units");
            start=end; length=prefix(data,start);
        }
        return out;
    }
    void classify(byte[] sample) {
        if (mode==Mode.NATIVE_MEL || mode==Mode.NATIVE_UNKNOWN) return;
        List<Nal> nals;
        try { nals=nals(sample); }
        catch (IllegalArgumentException bad) {
            if (mode==Mode.CONVERT_FEL) throw bad;
            nativeUnknown("Unrecognized HEVC layout; using native playback"); return;
        }
        if (mode==Mode.PROBING) {
            for (Nal nal:nals) if (nal.type==62) {
                if (nal.end-nal.payload>MAX_RPU) {
                    nativeUnknown("RPU exceeds compatibility limit; using native playback"); return;
                }
                try {
                    if (engine==null) engine=engineFactory.get();
                    int info=engine.inspect(Arrays.copyOfRange(sample,nal.payload,nal.end));
                    if (info==71) { mode=Mode.NATIVE_MEL; reason="Profile 7 MEL — native playback"; return; }
                    if (info==72) { mode=Mode.CONVERT_FEL; reason="Profile 7 FEL → Profile 8.1"; break; }
                    // A reuse-only RPU may omit NLQ classification. Keep probing;
                    // it is not evidence of FEL and cannot enable conversion.
                } catch (RuntimeException | LinkageError unavailable) {
                    nativeUnknown("RPU could not be classified; using native playback"); return;
                }
            }
        }
    }
    byte[] process(byte[] sample) {
        try { return processInternal(sample); }
        catch (RuntimeException | LinkageError problem) { throw new Failure("Dolby Vision FEL conversion failed", problem); }
    }
    private byte[] processInternal(byte[] sample) {
        classify(sample);
        if (mode!=Mode.CONVERT_FEL) return sample;
        List<Nal> nals=nals(sample);
        ByteArrayOutputStream output=new ByteArrayOutputStream(sample.length);
        for (Nal nal:nals) {
            if (nal.type==63 || nal.layer!=0) { droppedNals++; continue; }
            if (nal.type==62) {
                if (nal.end-nal.payload>MAX_RPU) throw new IllegalArgumentException("Oversized Dolby Vision RPU");
                byte[] rpu=engine.convert(Arrays.copyOfRange(sample,nal.payload,nal.end));
                if (rpu==null || rpu.length<2 || rpu.length>MAX_RPU || engine.inspect(rpu)/10!=8)
                    throw new IllegalStateException("FEL conversion did not produce valid Profile 8 metadata");
                output.write(sample,nal.start,nal.payload-nal.start); output.write(rpu,0,rpu.length); convertedRpus++;
            } else output.write(sample,nal.start,nal.end-nal.start);
            if (output.size()>MAX_SAMPLE) throw new IllegalArgumentException("Converted HEVC sample is too large");
        }
        return output.toByteArray();
    }
}
