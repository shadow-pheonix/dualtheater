package dev.dualtheater.tv;

import androidx.media3.common.C;
import androidx.media3.common.DataReader;
import androidx.media3.common.Format;
import androidx.media3.common.MimeTypes;
import androidx.media3.common.util.ParsableByteArray;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.extractor.TrackOutput;
import java.io.EOFException;
import java.io.IOException;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Reframes only classified clear P7 FEL samples. Preserves PTS, flags and part ordering. */
@UnstableApi
final class DolbyVisionTrackOutput implements TrackOutput {
    private final TrackOutput delegate;
    private final Supplier<DolbyVisionCompat.Engine> engine;
    private final Consumer<String> report;
    private DolbyVisionCompat compat;
    private Format source;
    private boolean intercept, announced;
    private byte[] queued = new byte[16384];
    private int count, heldBytes;
    private final List<Part> parts = new ArrayList<>();
    private final List<Frame> held = new ArrayList<>();
    private final byte[] scratch = new byte[8192];
    private final ParsableByteArray output = new ParsableByteArray();
    private static final int MAX_PROBE_FRAMES=8, MAX_PROBE_BYTES=Math.min(8*1024*1024,DolbyVisionCompat.MAX_SAMPLE/2);
    private static final class Part {
        int start, end; final int type;
        Part(int start,int end,int type) { this.start=start;this.end=end;this.type=type; }
    }
    private static final class Frame {
        final byte[] bytes; final List<Part> parts; final long time; final int flags; final CryptoData crypto;
        Frame(byte[] bytes,List<Part> parts,long time,int flags,CryptoData crypto) {
            this.bytes=bytes;this.parts=parts;this.time=time;this.flags=flags;this.crypto=crypto;
        }
        byte[] main() {
            int length=0; for (Part p:parts) if(p.type==SAMPLE_DATA_PART_MAIN) length+=p.end-p.start;
            byte[] data=new byte[length]; int at=0;
            for (Part p:parts) if(p.type==SAMPLE_DATA_PART_MAIN) {
                System.arraycopy(bytes,p.start,data,at,p.end-p.start);at+=p.end-p.start;
            }
            return data;
        }
    }
    DolbyVisionTrackOutput(TrackOutput delegate,Supplier<DolbyVisionCompat.Engine> engine,Consumer<String> report) {
        this.delegate=delegate;this.engine=engine;this.report=report;
    }
    static boolean isProfile7(Format format) {
        return MimeTypes.VIDEO_DOLBY_VISION.equals(format.sampleMimeType) && format.codecs!=null
            && format.codecs.matches("(?i)(dvhe|dvh1)\\.07\\.[0-9]{2}");
    }
    @Override public void durationUs(long value) { delegate.durationUs(value); }
    @Override public void format(Format format) {
        clearPending(); source=format; intercept=isProfile7(format); announced=false;
        compat=intercept ? new DolbyVisionCompat(engine) : null;
        if (!intercept) { delegate.format(format);announced=true;report.accept("Native video (not Profile 7)"); }
        else report.accept("Checking Profile 7 RPU for FEL; MEL stays native");
    }
    private void append(byte[] data,int offset,int length,int part) {
        if (length<0) throw new DolbyVisionCompat.Failure("Invalid DV sample size");
        if (length>DolbyVisionCompat.MAX_SAMPLE-count) {
            if (compat.mode()==DolbyVisionCompat.Mode.PROBING) {
                abandonProbe("Probe buffer limit reached; native playback");
                write(data,offset,length,part);return;
            }
            throw new DolbyVisionCompat.Failure("DV sample buffer limit exceeded");
        }
        if (part<0 || part>2) throw new DolbyVisionCompat.Failure("Unknown sample data part");
        int end=count+length;
        if (end>queued.length) queued=Arrays.copyOf(queued,Math.min(DolbyVisionCompat.MAX_SAMPLE,Math.max(end,queued.length*2)));
        System.arraycopy(data,offset,queued,count,length);
        if (length>0) {
            Part last=parts.isEmpty()?null:parts.get(parts.size()-1);
            if(last!=null && last.type==part) last.end=end;
            else parts.add(new Part(count,end,part));
        }
        count=end;
    }
    @Override public int sampleData(DataReader input,int length,boolean allowEnd,int part) throws IOException {
        if(!intercept) return delegate.sampleData(input,length,allowEnd,part);
        int got=input.read(scratch,0,Math.min(length,scratch.length));
        if(got<0) { if(allowEnd) return C.RESULT_END_OF_INPUT; throw new EOFException(); }
        append(scratch,0,got,part); return got;
    }
    @Override public void sampleData(ParsableByteArray data,int length,int part) {
        if(!intercept) {delegate.sampleData(data,length,part);return;}
        if(length<0 || length>data.bytesLeft()) throw new DolbyVisionCompat.Failure("Invalid sample data length");
        append(data.getData(),data.getPosition(),length,part);data.skipBytes(length);
    }
    @Override public void sampleMetadata(long time,int flags,int size,int offset,CryptoData crypto) {
        if(!intercept) {delegate.sampleMetadata(time,flags,size,offset,crypto);return;}
        if(size<0 || offset<0 || size>count-offset) throw new DolbyVisionCompat.Failure("Invalid DV sample boundaries");
        int end=count-offset,start=end-size;
        List<Part> frameParts=new ArrayList<>(),tail=new ArrayList<>();
        for(Part p:parts) {
            int a=Math.max(start,p.start),b=Math.min(end,p.end);
            if(a<b) frameParts.add(new Part(a-start,b-start,p.type));
            if(p.end>end) tail.add(new Part(Math.max(end,p.start)-end,p.end-end,p.type));
        }
        Frame frame=new Frame(Arrays.copyOfRange(queued,start,end),frameParts,time,flags,crypto);
        System.arraycopy(queued,end,queued,0,offset);count=offset;parts.clear();parts.addAll(tail);
        if(compat.mode()==DolbyVisionCompat.Mode.PROBING) {
            held.add(frame);heldBytes+=size;
            if(crypto!=null || (flags&C.BUFFER_FLAG_ENCRYPTED)!=0)
                compat.nativeUnknown("Encrypted Profile 7 cannot be classified; native playback");
            else compat.classify(frame.main());
            if(compat.mode()==DolbyVisionCompat.Mode.PROBING && (held.size()>=MAX_PROBE_FRAMES || heldBytes>=MAX_PROBE_BYTES))
                compat.nativeUnknown("No classifiable RPU found; native playback");
            if(compat.mode()==DolbyVisionCompat.Mode.PROBING) return;
            announce();
            for(Frame pending:held) emit(pending);
            held.clear();heldBytes=0;
        } else emit(frame);
        if(compat.mode()!=DolbyVisionCompat.Mode.CONVERT_FEL) {
            // Once identified as MEL/unclassified, restore true pass-through.
            for(Part p:parts) write(queued,p.start,p.end-p.start,p.type);
            count=0;parts.clear();intercept=false;
        }
    }
    private void abandonProbe(String reason) {
        compat.nativeUnknown(reason);announce();
        for(Frame frame:held) emit(frame);
        held.clear();heldBytes=0;
        for(Part p:parts) write(queued,p.start,p.end-p.start,p.type);
        count=0;parts.clear();intercept=false;
    }
    private void announce() {
        if(!announced) {
            Format selected=compat.mode()==DolbyVisionCompat.Mode.CONVERT_FEL
                ? source.buildUpon().setCodecs(source.codecs.replace(".07.",".08.")).build() : source;
            delegate.format(selected);announced=true;report.accept(compat.reason());
        }
    }
    private void emit(Frame frame) {
        boolean convert=compat.mode()==DolbyVisionCompat.Mode.CONVERT_FEL;
        if(convert && (frame.crypto!=null || (frame.flags&C.BUFFER_FLAG_ENCRYPTED)!=0))
            throw new DolbyVisionCompat.Failure("Encrypted FEL samples cannot use compatibility mode");
        byte[] transformed=convert ? compat.process(frame.main()) : null;
        boolean mainWritten=false;
        int emitted=0;
        for(Part p:frame.parts) {
            int length=p.end-p.start;
            if(convert && p.type==SAMPLE_DATA_PART_MAIN) {
                if(!mainWritten) {write(transformed,0,transformed.length,p.type);emitted+=transformed.length;mainWritten=true;}
            } else if(convert && p.start==0 && p.type==SAMPLE_DATA_PART_SUPPLEMENTAL
                    && (frame.flags&C.BUFFER_FLAG_HAS_SUPPLEMENTAL_DATA)!=0) {
                if(length!=4) throw new DolbyVisionCompat.Failure("Unexpected DV supplemental prefix");
                byte[] prefix={(byte)(transformed.length>>>24),(byte)(transformed.length>>>16),(byte)(transformed.length>>>8),(byte)transformed.length};
                write(prefix,0,4,p.type);emitted+=4;
            } else {write(frame.bytes,p.start,length,p.type);emitted+=length;}
        }
        delegate.sampleMetadata(frame.time,frame.flags,emitted,0,frame.crypto);
    }
    private void write(byte[] bytes,int offset,int length,int part) {
        output.reset(bytes,offset+length);output.setPosition(offset);delegate.sampleData(output,length,part);
    }
    void endInput() {
        if(!held.isEmpty()) {
            compat.nativeUnknown("No classifiable RPU before EOF; native playback");announce();
            for(Frame f:held) emit(f);
            held.clear();heldBytes=0;
        }
    }
    void seek() { clearPending(); }
    private void clearPending() {count=heldBytes=0;parts.clear();held.clear();}
}
