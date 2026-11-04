"""Exercise the actual cache controller with inert Android/cache API fixtures.

No emulator/device/network or cache performance measurement. Requires JDK 17+;
run python tools_src/verify_cache_controller.py --java-home <JDK directory>.
The fake cache writer records requested ranges and stops only on cancellation.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import tempfile

STUBS = {
    'android/os/Process.java': """package android.os; public class Process {public static final int THREAD_PRIORITY_BACKGROUND=10;public static void setThreadPriority(int n){}}""",
    'android/os/StatFs.java': """package android.os; public class StatFs {public StatFs(String s){}public long getAvailableBytes(){return 1L<<40;}}""",
    'android/content/Context.java': """package android.content; import java.io.File; public class Context {final File dir;public Context(File d){dir=d;}public Context getApplicationContext(){return this;}public File getCacheDir(){return dir;}}""",
    'android/net/Uri.java': """package android.net; public class Uri {final String value;private Uri(String v){value=v;}public static Uri parse(String v){return new Uri(v);}public String toString(){return value;}}""",
    'androidx/media3/common/C.java': """package androidx.media3.common;public class C {public static final long LENGTH_UNSET=-1;public static final int TRACK_TYPE_TEXT=3;}""",
    'androidx/media3/common/util/UnstableApi.java': """package androidx.media3.common.util;public @interface UnstableApi {}""",
    'androidx/media3/datasource/TransferListener.java': """package androidx.media3.datasource;public interface TransferListener {}""",
    'androidx/media3/datasource/DataSource.java': """package androidx.media3.datasource;import java.io.*;import java.util.*;import android.net.Uri;public interface DataSource {interface Factory{DataSource createDataSource();}void addTransferListener(TransferListener t);long open(DataSpec s)throws IOException;int read(byte[]b,int o,int n)throws IOException;Uri getUri();Map<String,List<String>>getResponseHeaders();void close()throws IOException;}""",
    'androidx/media3/datasource/DataSpec.java': """package androidx.media3.datasource;import android.net.Uri;public class DataSpec {public static final int FLAG_ALLOW_CACHE_FRAGMENTATION=4;public Uri uri;public long position,length=-1;public static class Builder {final DataSpec s=new DataSpec();public Builder setUri(Uri u){s.uri=u;return this;}public Builder setPosition(long p){s.position=p;return this;}public Builder setLength(long n){s.length=n;return this;}public Builder setFlags(int n){return this;}public DataSpec build(){return s;}}}""",
    'androidx/media3/datasource/HttpDataSource.java': """package androidx.media3.datasource;import java.io.*;import java.util.*;public interface HttpDataSource {class InvalidResponseCodeException extends IOException {public int responseCode;public Map<String,List<String>>headerFields=Map.of();}}""",
    'androidx/media3/datasource/DefaultHttpDataSource.java': """package androidx.media3.datasource;public class DefaultHttpDataSource {}""",
    'androidx/media3/database/StandaloneDatabaseProvider.java': """package androidx.media3.database;public class StandaloneDatabaseProvider {public StandaloneDatabaseProvider(android.content.Context c){}}""",
    'androidx/media3/datasource/cache/SimpleCache.java': """package androidx.media3.datasource.cache;public class SimpleCache {public SimpleCache(java.io.File f,LeastRecentlyUsedCacheEvictor e,androidx.media3.database.StandaloneDatabaseProvider p){}public long getCachedLength(String k,long p,long n){return -n;}public long getCacheSpace(){return 0;}}""",
    'androidx/media3/datasource/cache/LeastRecentlyUsedCacheEvictor.java': """package androidx.media3.datasource.cache;public class LeastRecentlyUsedCacheEvictor {public LeastRecentlyUsedCacheEvictor(long n){}}""",
    'androidx/media3/datasource/cache/CacheDataSink.java': """package androidx.media3.datasource.cache;public class CacheDataSink {public static class Factory {public Factory setCache(SimpleCache c){return this;}public Factory setFragmentSize(long n){return this;}}}""",
    'androidx/media3/datasource/cache/CacheDataSource.java': """package androidx.media3.datasource.cache;import androidx.media3.datasource.*;public class CacheDataSource {public static final int FLAG_IGNORE_CACHE_ON_ERROR=1,FLAG_BLOCK_ON_CACHE=2;public static class Factory {DataSource.Factory upstream;public Factory setCache(SimpleCache c){return this;}public Factory setUpstreamDataSourceFactory(DataSource.Factory f){upstream=f;return this;}public Factory setCacheWriteDataSinkFactory(Object f){return this;}public Factory setFlags(int n){return this;}public DataSource createDataSource(){return upstream.createDataSource();}public DataSource createDataSourceForDownloading(){return createDataSource();}}}""",
    'androidx/media3/datasource/cache/CacheWriter.java': """package androidx.media3.datasource.cache;import androidx.media3.datasource.*;import java.io.*;import java.util.*;import java.util.concurrent.*;public class CacheWriter {public interface ProgressListener {void onProgress(long a,long b,long c);}public static final List<Long> positions=Collections.synchronizedList(new ArrayList<>());public static final CountDownLatch began=new CountDownLatch(1);final DataSpec spec;final CountDownLatch cancel=new CountDownLatch(1);public CacheWriter(DataSource d,DataSpec s,byte[]b,ProgressListener l){spec=s;}public void cancel(){cancel.countDown();}public void cache()throws IOException {positions.add(spec.position);began.countDown();try{cancel.await(5,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}throw new IOException("cancelled fixture writer");}}""",
}

HARNESS = r'''
package dev.dualtheater.tv;
import java.io.*;import java.util.*;import java.lang.reflect.*;import java.util.concurrent.*;
import android.content.Context;import android.net.Uri;import androidx.media3.datasource.*;import androidx.media3.datasource.cache.CacheWriter;
public class CacheHarness {
 static final long TOTAL=512L<<20;
 static class Source implements DataSource {
  DataSpec spec;long at; public void addTransferListener(TransferListener t){}
  public long open(DataSpec s){spec=s;at=s.position;return TOTAL-at;}
  public int read(byte[]b,int o,int n){int count=(int)Math.min(n,TOTAL-at);if(count==0)return -1;for(int i=0;i<count;i++)b[o+i]=(byte)((at+i)%251);at+=count;return count;}
  public Uri getUri(){return spec.uri;}public Map<String,List<String>>getResponseHeaders(){return Map.of("Content-Range",List.of("bytes "+spec.position+"-536870911/536870912"));}public void close(){}
 }
 static long field(ReadAheadCache c,String key)throws Exception {Field f=ReadAheadCache.class.getDeclaredField(key);f.setAccessible(true);return f.getLong(c);}
 static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
 static void consume(DataSource d,long at,int count)throws Exception {
  byte[] b=new byte[4001];int read=0;
  while(read<count){int n=d.read(b,0,Math.min(count-read,b.length));require(n>0,"unexpected EOF");for(int i=0;i<n;i++)require(b[i]==(byte)((at+read+i)%251),"altered source byte");read+=n;}
 }
 static DataSpec spec(Uri uri,long position){return new DataSpec.Builder().setUri(uri).setPosition(position).build();}
 static void requestAt(long target)throws Exception {
  long end=System.nanoTime()+2_000_000_000L;
  while(System.nanoTime()<end){synchronized(CacheWriter.positions){if(CacheWriter.positions.contains(target))return;}Thread.sleep(5);}
  throw new AssertionError("worker did not request new head "+target+": "+CacheWriter.positions);
 }
 public static void main(String[]args)throws Exception {
  ReadAheadCache c=new ReadAheadCache(new Context(new File(args[0])),Source::new,Source::new,true);
  DataSource d=c.foregroundFactory().createDataSource();Uri uri=Uri.parse("http://localhost/fixture");
  try {
   d.open(spec(uri,1L<<20));consume(d,1L<<20,262144);long old=field(c,"readHead");d.close();
   long target=200L<<20;d.open(spec(uri,target));
   require(field(c,"readHead")==target,"same-URI reopen retained old head");
   require(field(c,"totalLength")==TOTAL,"same-URI length lost");
   consume(d,target,1);require(field(c,"readHead")==target,"buffer prefetch advanced consumed head");
   c.playbackReady(true);requestAt(target);
   // Reopen while a real controller worker is already owning an old range.
   d.close();target=300L<<20;d.open(spec(uri,target));requestAt(target);
   consume(d,target,262144);require(field(c,"readHead")==target+262144,"consumed threshold incorrect");
   c.playbackReady(false);d.close();target=1L<<20;d.open(spec(uri,target));
   require(field(c,"readHead")==target,"backward reopen retained old head");consume(d,target,37);
   d.close();target+=8;d.open(spec(uri,target));require(field(c,"readHead")==target,"small reopen not rebased");consume(d,target,521);
   d.close();d.open(spec(Uri.parse("http://localhost/other"), 0));require(field(c,"readHead")==0,"new URI not rebased");consume(d,0,71);
   System.out.println("{\"same_uri_rebase\":true,\"worker_range_rebased\":true,\"backward_and_small_reopen\":true,\"source_bytes_unchanged\":true}");
  } finally {c.close();d.close();}
 }
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java-home', default=os.environ.get('JAVA_HOME'))
    args = parser.parse_args()
    suffix = '.exe' if os.name == 'nt' else ''
    def binary(name):
        value = str(Path(args.java_home)/'bin'/(name+suffix)) if args.java_home else shutil.which(name)
        if not value or not Path(value).is_file():
            parser.error('JDK is required; specify --java-home')
        return value
    javac, java = binary('javac'), binary('java')
    repo = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='dualtheater-cache-proof-') as directory:
        root = Path(directory); sources = root/'src'; classes = root/'classes'
        classes.mkdir()
        def put(name, body):
            path = sources/name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding='utf-8')
        for name, body in STUBS.items(): put(name, body)
        for name in ('ReadAheadCache', 'ReadAheadWindow', 'BufferedByteReader'):
            relative = f'dev/dualtheater/tv/{name}.java'
            put(relative, (repo/'android/app/src/main/java'/relative).read_text(encoding='utf-8'))
        put('dev/dualtheater/tv/CacheHarness.java', HARNESS)
        subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(classes),
                        *map(str, sources.rglob('*.java'))], check=True, timeout=30)
        cache = root/'cache'; cache.mkdir()
        result = subprocess.check_output([java, '-cp', str(classes), 'dev.dualtheater.tv.CacheHarness', str(cache)],
                                         text=True, timeout=15)
        print(json.dumps(json.loads(result), indent=2))


if __name__ == '__main__': main()
