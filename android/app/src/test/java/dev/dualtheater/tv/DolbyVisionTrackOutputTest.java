package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.*;
import androidx.media3.common.*;
import androidx.media3.common.util.ParsableByteArray;
import androidx.media3.extractor.TrackOutput;

public class DolbyVisionTrackOutputTest {
    static final byte[] BASE={0,0,0,1,0x26,1,4,5,6};
    static final byte[] EL={0,0,1,0x7e,1,9,8,7};
    static byte[] nal(int marker) {return new byte[]{0,0,0,1,0x7c,1,(byte)marker,7,8};}
    static byte[] join(byte[]... arrays) {
        ByteArrayOutputStream out=new ByteArrayOutputStream();for(byte[]a:arrays)out.write(a,0,a.length);return out.toByteArray();
    }
    static class Engine implements DolbyVisionCompat.Engine {
        int conversions,inspections;
        public int inspect(byte[] data) {inspections++;return data[2]==7?72:data[2]==8?80:data[2]==1?71:70;}
        public byte[] convert(byte[] data) {conversions++;return new byte[]{0x7c,1,8,7,8};}
    }
    static class Sink implements TrackOutput {
        Format format; final List<Long> times=new ArrayList<>(); final List<Integer> flags=new ArrayList<>();
        final List<byte[]> samples=new ArrayList<>(); final List<Integer> dataParts=new ArrayList<>();
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        public void format(Format f) {format=f;}
        public int sampleData(DataReader in,int length,boolean allow,int part)throws IOException {
            byte[] b=new byte[length];int n=in.read(b,0,length);if(n>0){bytes.write(b,0,n);dataParts.add(part);}return n;
        }
        public void sampleData(ParsableByteArray data,int length,int part) {
            bytes.write(data.getData(),data.getPosition(),length);data.skipBytes(length);dataParts.add(part);
        }
        public void sampleMetadata(long time,int f,int size,int offset,CryptoData crypto) {
            byte[] all=bytes.toByteArray();assertEquals(size+offset,all.length);
            samples.add(Arrays.copyOf(all,size));times.add(time);flags.add(f);
            bytes.reset();bytes.write(all,size,offset);
        }
    }
    static Format p7() {return new Format.Builder().setSampleMimeType(MimeTypes.VIDEO_DOLBY_VISION).setCodecs("dvhe.07.06").build();}
    static DolbyVisionTrackOutput track(Sink sink,Engine engine) {return new DolbyVisionTrackOutput(sink,()->engine, value->{});}
    static void send(DolbyVisionTrackOutput t,byte[] data,long time) {
        t.sampleData(new ParsableByteArray(data),data.length);t.sampleMetadata(time,C.BUFFER_FLAG_KEY_FRAME,data.length,0,null);
    }
    @Test public void melRetainsIdenticalFormatAndAllEncodedBytesIncludingEl() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);Format original=p7();t.format(original);
        byte[] bytes=join(BASE,nal(1),EL);send(t,bytes,123456789012L);send(t,BASE,123456790000L);
        assertSame(original,sink.format);assertArrayEquals(bytes,sink.samples.get(0));assertArrayEquals(BASE,sink.samples.get(1));
        assertEquals(0,engine.conversions);assertEquals(1,engine.inspections);assertEquals(Long.valueOf(123456789012L),sink.times.get(0));
    }
    @Test public void felRewritesCodecBeforeSamplesRemovesElPreservesBaseAndPts() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        send(t,join(BASE,nal(7),EL),987654321012L);
        assertEquals("dvhe.08.06",sink.format.codecs);assertArrayEquals(join(BASE,nal(8)),sink.samples.get(0));
        assertEquals(Long.valueOf(987654321012L),sink.times.get(0));assertEquals(Integer.valueOf(C.BUFFER_FLAG_KEY_FRAME),sink.flags.get(0));
        assertEquals(1,engine.conversions);
    }
    @Test public void noFalseFelFromEnhancementNalAloneAndLateRpuFlushesHeldPts() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        send(t,join(BASE,EL),1000);assertNull(sink.format);assertTrue(sink.samples.isEmpty());assertEquals(0,engine.conversions);
        send(t,join(BASE,nal(7),EL),2000);assertEquals(Arrays.asList(1000L,2000L),sink.times);
        assertArrayEquals(BASE,sink.samples.get(0));assertEquals("dvhe.08.06",sink.format.codecs);
    }
    @Test public void absentOrUnclassifiableRpuUsesBoundedNativeProbe() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);Format f=p7();t.format(f);
        for(int i=0;i<8;i++)send(t,join(BASE,nal(0),EL),i*40000L);
        assertSame(f,sink.format);assertEquals(8,sink.samples.size());assertEquals(0,engine.conversions);
        assertArrayEquals(join(BASE,nal(0),EL),sink.samples.get(7));
    }
    @Test public void offsetTailIsRetainedUntilItsOwnMetadataAfterSizeChange() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        byte[] frame=join(BASE,nal(7),EL),both=join(frame,frame);
        t.sampleData(new ParsableByteArray(both),both.length);
        t.sampleMetadata(40,0,frame.length,frame.length,null);t.sampleMetadata(80,0,frame.length,0,null);
        assertEquals(Arrays.asList(40L,80L),sink.times);assertEquals(2,sink.samples.size());
        assertArrayEquals(join(BASE,nal(8)),sink.samples.get(0));assertArrayEquals(sink.samples.get(0),sink.samples.get(1));
    }
    @Test public void supplementalPrefixSizeUpdatesAndPayloadAndFlagsRemain() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        byte[] data=join(BASE,nal(7),EL),extra={11,12,13};byte[] size={0,0,0,(byte)data.length};
        t.sampleData(new ParsableByteArray(size),4,TrackOutput.SAMPLE_DATA_PART_SUPPLEMENTAL);
        t.sampleData(new ParsableByteArray(data),data.length);
        t.sampleData(new ParsableByteArray(extra),3,TrackOutput.SAMPLE_DATA_PART_SUPPLEMENTAL);
        t.sampleMetadata(100,C.BUFFER_FLAG_HAS_SUPPLEMENTAL_DATA,data.length+7,0,null);
        byte[] expected=join(new byte[]{0,0,0,(byte)join(BASE,nal(8)).length},BASE,nal(8),extra);
        assertArrayEquals(expected,sink.samples.get(0));assertEquals(Integer.valueOf(C.BUFFER_FLAG_HAS_SUPPLEMENTAL_DATA),sink.flags.get(0));
    }
    @Test public void dataReaderShortReadsAndDefaultOverloadFeedRealWrapper()throws Exception {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        byte[] sample=join(BASE,nal(7));ByteArrayInputStream input=new ByteArrayInputStream(sample);
        DataReader reader=(b,o,n)->input.read(b,o,Math.min(n,3));int total=0;
        while(total<sample.length)total+=t.sampleData(reader,sample.length-total,false);
        t.sampleMetadata(1,0,total,0,null);assertEquals("dvhe.08.06",sink.format.codecs);
        assertEquals(C.RESULT_END_OF_INPUT,t.sampleData(reader,1,true));
        try{t.sampleData(reader,1,false);fail("EOF expected");}catch(EOFException expected){}
    }
    @Test public void seekDiscardsPartialBytesAndKeepsClassifiedFelChoice() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);t.format(p7());
        send(t,join(BASE,nal(7)),100);t.sampleData(new ParsableByteArray(BASE),3);t.seek();
        send(t,join(BASE,nal(7),EL),5_000_000_000L);assertEquals(2,sink.samples.size());assertEquals("dvhe.08.06",sink.format.codecs);
        assertArrayEquals(join(BASE,nal(8)),sink.samples.get(1));
    }
    @Test public void otherFormatsBypassMetadataEngineAndRetainExactFormat() {
        for(String codec:Arrays.asList("dvhe.05.06","dvh1.08.06","hvc1.2.4.L153.B0","avc1.640028")) {
            Sink sink=new Sink();DolbyVisionTrackOutput t=new DolbyVisionTrackOutput(sink,()->{throw new AssertionError("Native engine loaded");},value->{});
            Format f=new Format.Builder().setCodecs(codec).setSampleMimeType(codec.startsWith("dv")?MimeTypes.VIDEO_DOLBY_VISION:MimeTypes.VIDEO_H265).build();
            t.format(f);send(t,BASE,1);assertSame(f,sink.format);assertArrayEquals(BASE,sink.samples.get(0));
        }
    }
    @Test public void conversionFailureCannotEmitUnconvertedFelAsProfileEight() {
        Sink sink=new Sink();Engine e=new Engine(){public byte[] convert(byte[] data){return data;}};
        DolbyVisionTrackOutput t=track(sink,e);t.format(p7());
        try{send(t,join(BASE,nal(7)),1);fail("Expected conversion failure");}catch(IllegalStateException expected){}
        assertTrue(sink.samples.isEmpty());
    }
    @Test public void missingNativeLibraryKeepsNativePathWithoutClaimingConversion() {
        Sink sink=new Sink();DolbyVisionTrackOutput t=new DolbyVisionTrackOutput(sink,()->{throw new UnsatisfiedLinkError();}, value->{});
        Format f=p7();t.format(f);byte[] data=join(BASE,nal(7),EL);send(t,data,1);
        assertSame(f,sink.format);assertArrayEquals(data,sink.samples.get(0));
    }
    @Test public void endBeforeClassificationReleasesHeldNativeSample() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);Format f=p7();t.format(f);
        send(t,BASE,1);t.endInput();assertSame(f,sink.format);assertArrayEquals(BASE,sink.samples.get(0));
    }
    @Test public void oversizedUnclassifiedProbeReturnsToNativeWithoutBreakingSampleBoundaries() {
        Sink sink=new Sink();Engine engine=new Engine();DolbyVisionTrackOutput t=track(sink,engine);Format source=p7();t.format(source);
        byte[] first=new byte[DolbyVisionCompat.MAX_SAMPLE],last={3,4,5};
        t.sampleData(new ParsableByteArray(first),first.length);
        t.sampleData(new ParsableByteArray(last),last.length);
        t.sampleMetadata(7,0,first.length+last.length,0,null);
        assertSame(source,sink.format);assertEquals(0,engine.conversions);
        assertArrayEquals(join(first,last),sink.samples.get(0));
    }

}
