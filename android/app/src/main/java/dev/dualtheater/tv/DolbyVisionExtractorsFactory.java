package dev.dualtheater.tv;

import android.net.Uri;
import androidx.media3.common.C;
import androidx.media3.common.ParserException;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.extractor.*;
import androidx.media3.extractor.text.SubtitleParser;
import java.io.IOException;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.Supplier;

/** Uses Media3 1.9's actual TrackOutput hook, including both sampleData overload families. */
@UnstableApi
final class DolbyVisionExtractorsFactory implements ExtractorsFactory {
    private final ExtractorsFactory delegate;
    private final BooleanSupplier enabled;
    private final Supplier<DolbyVisionCompat.Engine> engine;
    private final Consumer<String> report;
    DolbyVisionExtractorsFactory(ExtractorsFactory delegate,BooleanSupplier enabled,Consumer<String> report) {
        this(delegate,enabled,DolbyVisionNative::new,report);
    }
    DolbyVisionExtractorsFactory(ExtractorsFactory delegate,BooleanSupplier enabled,
            Supplier<DolbyVisionCompat.Engine> engine,Consumer<String> report) {
        this.delegate=delegate;this.enabled=enabled;this.engine=engine;this.report=report;
    }
    @Override public Extractor[] createExtractors() { return wrap(delegate.createExtractors()); }
    @Override public Extractor[] createExtractors(Uri uri,Map<String,List<String>> headers) {
        return wrap(delegate.createExtractors(uri,headers));
    }
    @Override public ExtractorsFactory setSubtitleParserFactory(SubtitleParser.Factory factory) {
        delegate.setSubtitleParserFactory(factory);return this;
    }
    @Override public ExtractorsFactory experimentalSetTextTrackTranscodingEnabled(boolean enabled) {
        delegate.experimentalSetTextTrackTranscodingEnabled(enabled);return this;
    }
    @Override public ExtractorsFactory experimentalSetCodecsToParseWithinGopSampleDependencies(int codecs) {
        delegate.experimentalSetCodecsToParseWithinGopSampleDependencies(codecs);return this;
    }
    private Extractor[] wrap(Extractor[] extractors) {
        if(!enabled.getAsBoolean()) {report.accept("FEL compatibility off — native playback");return extractors;}
        report.accept("Automatic FEL compatibility — waiting for video");
        for(int i=0;i<extractors.length;i++) extractors[i]=new CompatExtractor(extractors[i]);
        return extractors;
    }
    private final class CompatExtractor extends ForwardingExtractor {
        private final Map<Integer,DolbyVisionTrackOutput> tracks=new HashMap<>();
        CompatExtractor(Extractor delegate) {super(delegate);}
        @Override public void init(ExtractorOutput output) {
            super.init(new ExtractorOutput() {
                @Override public TrackOutput track(int id,int type) {
                    if(type!=C.TRACK_TYPE_VIDEO) return output.track(id,type);
                    return tracks.computeIfAbsent(id,key -> new DolbyVisionTrackOutput(output.track(id,type),engine,report));
                }
                @Override public void endTracks() {output.endTracks();}
                @Override public void seekMap(SeekMap map) {output.seekMap(map);}
            });
        }
        @Override public int read(ExtractorInput input,PositionHolder position) throws IOException {
            try {
                int result=super.read(input,position);
                if(result==Extractor.RESULT_END_OF_INPUT) for(DolbyVisionTrackOutput track:tracks.values()) track.endInput();
                return result;
            } catch(DolbyVisionCompat.Failure failure) {
                report.accept("FEL compatibility failed — disable it and reload on Windows");
                throw ParserException.createForMalformedContainer(
                    "Dolby Vision FEL compatibility failed. Disable FEL compatibility on TV and reload from Windows.",failure);
            }
        }
        @Override public void seek(long position,long timeUs) {
            for(DolbyVisionTrackOutput track:tracks.values()) track.seek();
            super.seek(position,timeUs);
        }
        @Override public void release() {tracks.clear();super.release();}
    }
}
