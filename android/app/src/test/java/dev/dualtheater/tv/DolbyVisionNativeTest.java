package dev.dualtheater.tv;

import org.junit.*;
import static org.junit.Assert.*;
import java.io.*;

/** Actual JVM/JNI integration, enabled by -PdoviNativeDir=<host library directory>. */
public class DolbyVisionNativeTest {
    private DolbyVisionNative nativeEngine;
    static byte[] fixture(String name)throws Exception {
        try(InputStream in=DolbyVisionNativeTest.class.getResourceAsStream("/dovi/"+name+".bin")) {
            assertNotNull(in);return in.readAllBytes();
        }
    }
    @Before public void loadBridge() {
        Assume.assumeTrue("Host JNI library not configured",Boolean.getBoolean("dualtheater.dovi.native_test"));
        nativeEngine=new DolbyVisionNative();
    }
    @Test public void realRpuDetectionAndFelConversionValidateEndToEnd()throws Exception {
        byte[] mel=fixture("p7-mel"),fel=fixture("p7-fel");
        assertEquals(71,nativeEngine.inspect(mel));assertEquals(72,nativeEngine.inspect(fel));
        assertEquals(80,nativeEngine.inspect(nativeEngine.convert(fel)));
    }
    @Test public void realMalformedRpuReturnsExceptionWithoutHanging() {
        for(int size:new int[]{0,24,25,1024,65536,65537}) {
            try{nativeEngine.inspect(new byte[size]);fail("Malformed RPU accepted");}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void realTrackOutputKeepsMelAndConvertsOnlyFel()throws Exception {
        for(String name:new String[]{"p7-mel","p7-fel"}) {
            DolbyVisionTrackOutputTest.Sink sink=new DolbyVisionTrackOutputTest.Sink();
            DolbyVisionTrackOutput t=new DolbyVisionTrackOutput(sink,()->nativeEngine,value->{});
            androidx.media3.common.Format source=DolbyVisionTrackOutputTest.p7();t.format(source);
            byte[] input=DolbyVisionTrackOutputTest.join(DolbyVisionTrackOutputTest.BASE,new byte[]{0,0,0,1},fixture(name),DolbyVisionTrackOutputTest.EL);
            DolbyVisionTrackOutputTest.send(t,input,3_600_123_456L);
            if(name.equals("p7-mel")) {assertSame(source,sink.format);assertArrayEquals(input,sink.samples.get(0));}
            else {assertEquals("dvhe.08.06",sink.format.codecs);assertTrue(sink.samples.get(0).length<input.length);}
            assertEquals(Long.valueOf(3_600_123_456L),sink.times.get(0));
        }
    }
    @Test public void actualMatroskaExtractorAndJniBridgeKeepMelNativeAndConvertFel()throws Exception {
        for(String kind:new String[]{"p7-mel","p7-fel"}) {
            byte[] bytes;
            try(InputStream in=getClass().getResourceAsStream("/dovi/"+kind+".mkv")) {assertNotNull(in);bytes=in.readAllBytes();}
            androidx.media3.extractor.Extractor extractor=new DolbyVisionExtractorsFactory(
                ()->new androidx.media3.extractor.Extractor[]{new androidx.media3.extractor.mkv.MatroskaExtractor()},
                ()->true,()->nativeEngine,v->{}).createExtractors()[0];
            DolbyVisionExtractorTest.Output output=new DolbyVisionExtractorTest.Output();extractor.init(output);
            ByteArrayInputStream stream=new ByteArrayInputStream(bytes);
            androidx.media3.extractor.ExtractorInput input=new androidx.media3.extractor.DefaultExtractorInput(
                (data,offset,length)->stream.read(data,offset,length),0,bytes.length);
            androidx.media3.extractor.PositionHolder position=new androidx.media3.extractor.PositionHolder();
            int result=0,iterations=0;
            while(result!=androidx.media3.extractor.Extractor.RESULT_END_OF_INPUT && iterations++<100) {
                result=extractor.read(input,position);assertNotEquals(androidx.media3.extractor.Extractor.RESULT_SEEK,result);
            }
            assertEquals(androidx.media3.extractor.Extractor.RESULT_END_OF_INPUT,result);
            assertEquals(1,output.sink.samples.size());assertEquals(Long.valueOf(0),output.sink.times.get(0));
            assertEquals(kind.endsWith("fel")?"dvhe.08.06":"dvhe.07.06",output.sink.format.codecs);
            extractor.release();
        }
    }

}
