package dev.dualtheater.tv;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import androidx.media3.common.*;
import androidx.media3.extractor.*;
import androidx.media3.extractor.mkv.MatroskaExtractor;

public class DolbyVisionExtractorTest {
    static class Output implements ExtractorOutput {
        final DolbyVisionTrackOutputTest.Sink sink=new DolbyVisionTrackOutputTest.Sink();
        public TrackOutput track(int id,int type) {return sink;}
        public void endTracks() {}
        public void seekMap(SeekMap map) {}
    }
    @Test public void actualMatroskaDemuxInterceptsDefaultSampleDataOverloadsForFelAndMel()throws Exception {
        for(String kind:Arrays.asList("p7-fel","p7-mel")) {
            byte[] bytes;
            try(InputStream in=getClass().getResourceAsStream("/dovi/"+kind+".mkv")){assertNotNull(in);bytes=in.readAllBytes();}
            AtomicInteger inspections=new AtomicInteger(),conversions=new AtomicInteger();
            DolbyVisionCompat.Engine engine=new DolbyVisionCompat.Engine(){
                public int inspect(byte[] rpu){inspections.incrementAndGet();return rpu[2]==8?80:kind.endsWith("fel")?72:71;}
                public byte[] convert(byte[] rpu){conversions.incrementAndGet();return new byte[]{0x7c,1,8,7,8};}
            };
            Extractor extractor=new DolbyVisionExtractorsFactory(()->new Extractor[]{new MatroskaExtractor()},()->true,()->engine,v->{}).createExtractors()[0];
            Output output=new Output();extractor.init(output);
            ByteArrayInputStream stream=new ByteArrayInputStream(bytes);
            ExtractorInput input=new DefaultExtractorInput((data,offset,length)->stream.read(data,offset,length),0,bytes.length);
            PositionHolder position=new PositionHolder();int result=0,iterations=0;
            while(result!=Extractor.RESULT_END_OF_INPUT && iterations++<100) {
                result=extractor.read(input,position);assertNotEquals(Extractor.RESULT_SEEK,result);
            }
            assertEquals(Extractor.RESULT_END_OF_INPUT,result);assertEquals(1,output.sink.samples.size());
            assertEquals(Long.valueOf(0),output.sink.times.get(0));assertTrue(inspections.get()>0);
            assertEquals(kind.endsWith("fel")?"dvhe.08.06":"dvhe.07.06",output.sink.format.codecs);
            assertEquals(kind.endsWith("fel")?1:0,conversions.get());extractor.release();
        }
    }
    @Test public void disabledModeIsOriginalExtractorAndNeverCreatesNativeEngine() {
        Extractor original=new MatroskaExtractor();
        Extractor[] out=new DolbyVisionExtractorsFactory(()->new Extractor[]{original},()->false,
            ()->{throw new AssertionError("native engine touched");},v->{}).createExtractors();
        assertSame(original,out[0]);
    }
    @Test public void audioAndSubtitleOutputsAreDelegatedWithoutWrapping() {
        TrackOutput[] observed=new TrackOutput[3];
        Extractor fake=new ForwardingExtractor(new MatroskaExtractor()) {
            @Override public void init(ExtractorOutput output) {
                observed[0]=output.track(1,C.TRACK_TYPE_AUDIO);observed[1]=output.track(2,C.TRACK_TYPE_TEXT);
                observed[2]=output.track(3,C.TRACK_TYPE_VIDEO);assertSame(observed[2],output.track(3,C.TRACK_TYPE_VIDEO));
            }
        };
        Output sink=new Output();
        new DolbyVisionExtractorsFactory(()->new Extractor[]{fake},()->true,()->new DolbyVisionTrackOutputTest.Engine(),v->{}).createExtractors()[0].init(sink);
        assertSame(sink.sink,observed[0]);assertSame(sink.sink,observed[1]);assertTrue(observed[2] instanceof DolbyVisionTrackOutput);
    }
}
