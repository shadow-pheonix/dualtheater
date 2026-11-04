package dev.dualtheater.tv;

import android.content.Context;
import android.net.Uri;
import android.os.StatFs;
import androidx.media3.common.C;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DataSource;
import androidx.media3.datasource.DataSpec;
import androidx.media3.datasource.DefaultHttpDataSource;
import androidx.media3.datasource.HttpDataSource;
import androidx.media3.datasource.TransferListener;
import androidx.media3.datasource.cache.CacheDataSink;
import androidx.media3.datasource.cache.CacheDataSource;
import androidx.media3.datasource.cache.CacheWriter;
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor;
import androidx.media3.datasource.cache.SimpleCache;
import androidx.media3.database.StandaloneDatabaseProvider;
import java.io.File;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/** App-private disk read-ahead, with direct HTTP fallback when no writer owns a hole. */
@UnstableApi
final class ReadAheadCache implements AutoCloseable {
    static final long DISK_CACHE_BYTES = 512L * 1024 * 1024;
    private static final long FREE_SPACE_RESERVE_BYTES = 1024L * 1024 * 1024;
    private static final int IO_BUFFER_BYTES = 128 * 1024;
    private static final long CACHE_FRAGMENT_BYTES = 2L * 1024 * 1024;
    private static final long[] RETRY_DELAYS_NS = {250_000_000L, 1_000_000_000L, 2_000_000_000L};
    private static final Object PROCESS_CACHE_LOCK = new Object();
    private static SimpleCache processCache;
    private static File processCacheDirectory;
    private static String processCacheState = "disabled";

    static final class Stats {
        final String state;
        final long aheadBytes, cacheBytes, downloadedBytes, failures, chunks, cacheBudgetBytes, lookaheadBytes;
        final double foregroundWaitMs, maxForegroundWaitMs;
        Stats(String state, long aheadBytes, long cacheBytes, long downloadedBytes, long failures,
              long chunks, long cacheBudgetBytes, long lookaheadBytes, double foregroundWaitMs,
              double maxForegroundWaitMs) {
            this.state = state; this.aheadBytes = aheadBytes; this.cacheBytes = cacheBytes;
            this.downloadedBytes = downloadedBytes; this.failures = failures; this.chunks = chunks;
            this.cacheBudgetBytes = cacheBudgetBytes; this.lookaheadBytes = lookaheadBytes;
            this.foregroundWaitMs = foregroundWaitMs; this.maxForegroundWaitMs = maxForegroundWaitMs;
        }
    }

    private final Object lock = new Object();
    private final SimpleCache cache;
    private final DataSource.Factory upstreamFactory;
    private final DataSource.Factory writerUpstreamFactory;
    private final CacheDataSource.Factory foregroundCacheFactory, writerCacheFactory;
    private final long lookaheadBytes;
    private final byte[] workerBuffer = new byte[IO_BUFFER_BYTES];
    private final Thread worker;
    private final File cacheDirectory;

    private volatile String state;
    private volatile long aheadBytes, cacheBytes, downloadedBytes, failures, completedChunks;
    private volatile CacheWriter activeWriter;
    private final AtomicLong foregroundOperationNs = new AtomicLong(), maxForegroundWaitNs = new AtomicLong();
    private String activeUri;
    private long generation, readHead = -1, totalLength = C.LENGTH_UNSET, cursor = -1;
    private long failedGeneration = -1;
    private long retryAtNs, failedAtReadHead = -1;
    private int retryAttempts;
    private boolean suspended, closed, playbackReady, refilling = true;

    ReadAheadCache(Context context, DataSource.Factory upstreamFactory,
                   DataSource.Factory writerUpstreamFactory, boolean enabled) {
        this.upstreamFactory = upstreamFactory;
        this.writerUpstreamFactory = writerUpstreamFactory;
        CacheAllocation allocation = enabled ? processCache(context) : new CacheAllocation(null, null, "disabled");
        cache = allocation.cache;
        cacheDirectory = allocation.directory;
        state = allocation.state;
        lookaheadBytes = ReadAheadWindow.lookaheadBytes(DISK_CACHE_BYTES);
        if (cache != null) {
            foregroundCacheFactory = new CacheDataSource.Factory()
                .setCache(cache).setUpstreamDataSourceFactory(upstreamFactory)
                // Never write from the foreground. Consume committed fragments
                // from an active writer instead of racing a duplicate download.
                .setCacheWriteDataSinkFactory(null)
                .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR | CacheDataSource.FLAG_BLOCK_ON_CACHE);
            writerCacheFactory = new CacheDataSource.Factory()
                .setCache(cache).setUpstreamDataSourceFactory(writerUpstreamFactory)
                .setCacheWriteDataSinkFactory(new CacheDataSink.Factory()
                    .setCache(cache).setFragmentSize(CACHE_FRAGMENT_BYTES))
                .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR);
            worker = new Thread(this::runWorker, "dualtheater-read-ahead");
            worker.setDaemon(true);
            worker.start();
        } else {
            foregroundCacheFactory = null;
            writerCacheFactory = null;
            worker = null;
        }
    }

    private static final class CacheAllocation {
        final SimpleCache cache;
        final File directory;
        final String state;
        CacheAllocation(SimpleCache cache, File directory, String state) {
            this.cache = cache; this.directory = directory; this.state = state;
        }
    }

    private static CacheAllocation processCache(Context context) {
        synchronized (PROCESS_CACHE_LOCK) {
            if (processCache != null) return new CacheAllocation(processCache, processCacheDirectory, "idle");
            if ("low_storage".equals(processCacheState)) return new CacheAllocation(null, null, processCacheState);
            Context app = context.getApplicationContext();
            File directory = new File(app.getCacheDir(), "video-read-ahead");
            try {
                File parent = directory.getParentFile();
                if (parent != null && !parent.exists() && !parent.mkdirs())
                    throw new IOException("Cache directory unavailable");
                File storage = parent == null ? directory : parent;
                if (new StatFs(storage.getAbsolutePath()).getAvailableBytes()
                    < DISK_CACHE_BYTES + FREE_SPACE_RESERVE_BYTES) {
                    processCacheState = "low_storage";
                    return new CacheAllocation(null, null, processCacheState);
                }
                if (!directory.exists() && !directory.mkdirs()) throw new IOException("Cache directory unavailable");
                processCache = new SimpleCache(directory, new LeastRecentlyUsedCacheEvictor(DISK_CACHE_BYTES),
                    new StandaloneDatabaseProvider(app));
                processCacheDirectory = directory;
                processCacheState = "idle";
                return new CacheAllocation(processCache, processCacheDirectory, processCacheState);
            } catch (IOException | RuntimeException ignored) {
                processCacheState = "disabled";
                return new CacheAllocation(null, null, processCacheState);
            }
        }
    }

    DataSource.Factory foregroundFactory() {
        return () -> new TrackingDataSource(
            cache == null ? upstreamFactory.createDataSource() : foregroundCacheFactory.createDataSource(), this);
    }

    Stats stats() {
        long activeOperation = foregroundOperationNs.get();
        return new Stats(state, aheadBytes, cacheBytes, downloadedBytes, failures,
            completedChunks, cache == null ? 0 : DISK_CACHE_BYTES, cache == null ? 0 : lookaheadBytes,
            activeOperation == 0 ? 0 : Math.max(0, System.nanoTime() - activeOperation) / 1e6,
            maxForegroundWaitNs.get() / 1e6);
    }

    private long foregroundStarted() {
        long now = System.nanoTime(); foregroundOperationNs.set(now); return now;
    }

    private void foregroundFinished(long started) {
        maxForegroundWaitNs.accumulateAndGet(System.nanoTime() - started, Math::max);
        foregroundOperationNs.compareAndSet(started, 0);
    }

    void playbackReady(boolean ready) {
        synchronized (lock) {
            if (closed || playbackReady == ready) return;
            playbackReady = ready;
            if (!ready) {
                refilling = true;
                generation++; failedGeneration = -1; retryAttempts = 0;
                cancelWriterLocked();
            }
            if (cache != null && !suspended) state = ready ? "queued" : "preparing";
            lock.notifyAll();
        }
    }

    void suspend() {
        synchronized (lock) {
            suspended = true;
            generation++;
            activeUri = null;
            cursor = -1;
            aheadBytes = 0;
            cancelWriterLocked();
            if (cache != null && !closed) state = "suspended";
            lock.notifyAll();
        }
    }

    void resume() {
        synchronized (lock) {
            if (closed) return;
            suspended = false;
            if (cache != null) state = "idle";
            lock.notifyAll();
        }
    }

    @Override public void close() {
        synchronized (lock) {
            if (closed) return;
            closed = true;
            generation++;
            state = "closing";
            cancelWriterLocked();
            lock.notifyAll();
        }
        // SimpleCache is process-scoped and intentionally survives Activity recreation.
    }

    private void opening(String uri, long position) {
        synchronized (lock) {
            if (closed || cache == null) return;
            // An extractor reopen is a new logical byte position even when the
            // URI is unchanged. Rebase before READY can wake the prefetch worker;
            // do not wait for the first 256 KiB consumption notification.
            boolean same = uri.equals(activeUri);
            if (!same || ReadAheadWindow.isFarSeek(readHead, position)) {
                resetRequestLocked(uri, position, same ? totalLength : C.LENGTH_UNSET);
            } else {
                readHead = position;
                updateAheadLocked();
                lock.notifyAll();
            }
        }
    }

    private void opened(String uri, long position, long openedLength, long total, boolean originalLengthUnset) {
        synchronized (lock) {
            if (closed || cache == null || !uri.equals(activeUri)) return;
            if (total >= 0) totalLength = total;
            else if (originalLengthUnset && openedLength >= 0 && totalLength == C.LENGTH_UNSET)
                totalLength = position > Long.MAX_VALUE - openedLength ? Long.MAX_VALUE : position + openedLength;
            lock.notifyAll();
        }
    }

    private void readHead(String uri, long position, long total) {
        synchronized (lock) {
            if (closed || suspended || cache == null || !uri.equals(activeUri)) return;
            if (ReadAheadWindow.isFarSeek(readHead, position)) resetRequestLocked(uri, position, total);
            else {
                readHead = position;
                if (total >= 0) totalLength = total;
            }
            updateAheadLocked();
            if (!suspended && failedGeneration != generation) state = playbackReady ? "queued" : "preparing";
            lock.notifyAll();
        }
    }

    private void resetRequestLocked(String uri, long position, long total) {
        generation++;
        failedGeneration = -1;
        failedAtReadHead = -1;
        retryAttempts = 0;
        retryAtNs = 0;
        activeUri = uri;
        readHead = position;
        totalLength = total;
        cursor = position;
        refilling = true;
        aheadBytes = 0;
        cancelWriterLocked();
        if (!suspended) state = playbackReady ? "queued" : "preparing";
        lock.notifyAll();
    }

    private void cancelWriterLocked() {
        CacheWriter writer = activeWriter;
        if (writer != null) writer.cancel();
    }

    private void updateAheadLocked() {
        long end = ReadAheadWindow.targetEnd(readHead, totalLength, lookaheadBytes);
        aheadBytes = cursor < 0 ? 0 : Math.max(0, Math.min(end, cursor) - readHead);
    }

    private void runWorker() {
        try {
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_BACKGROUND);
            while (true) {
                final String uri;
                final long gen, position, chunkLength, end, head;
                synchronized (lock) {
                    while (!closed && (suspended || !playbackReady || activeUri == null || readHead < 0)) {
                        if (cache != null && suspended) state = "suspended";
                        else if (cache != null && !playbackReady) state = "preparing";
                        lock.wait();
                    }
                    if (closed) return;
                    if (failedGeneration == generation) {
                        if (failedAtReadHead >= 0 && readHead - failedAtReadHead >= 1024 * 1024L) {
                            failedGeneration = -1; retryAttempts = 0; failedAtReadHead = -1;
                        } else if (retryAttempts > RETRY_DELAYS_NS.length) {
                            lock.wait();
                            continue;
                        } else {
                            long delay = retryAtNs - System.nanoTime();
                            if (delay > 0) {
                                lock.wait(delay / 1_000_000L, (int)(delay % 1_000_000L));
                                continue;
                            }
                            failedGeneration = -1;
                        }
                    }
                    end = ReadAheadWindow.targetEnd(readHead, totalLength, lookaheadBytes);
                    uri = activeUri; gen = generation; head = readHead;
                }

                // A completed-download cursor is not proof of current coverage:
                // LRU eviction and seeks can leave holes behind it. Query the
                // first contiguous span, outside the UI/loader coordination lock.
                long cached = end > head ? cache.getCachedLength(uri, head, end - head) : 0;
                synchronized (lock) {
                    if (closed) return;
                    if (suspended || !playbackReady || gen != generation || head != readHead) continue;
                    cursor = ReadAheadWindow.firstMissingPosition(head, end, cached);
                    aheadBytes = Math.max(0, cursor - head);
                    if (cursor >= end) {
                        refilling = false;
                        state = "ready";
                        lock.wait();
                        continue;
                    }
                    if (!ReadAheadWindow.needsRefill(aheadBytes, lookaheadBytes, refilling)) {
                        // Avoid a new HTTP/cache transaction for every 256 KiB
                        // read-head notification. Refill a 32 MiB reserve gap in
                        // full chunks; a hole at the read head still starts now.
                        state = "ready";
                        lock.wait();
                        continue;
                    }
                    refilling = true;
                    position = cursor;
                    chunkLength = ReadAheadWindow.nextChunkLength(position, end);
                    state = "running";
                }

                if (cacheDirectory != null && cacheDirectory.getUsableSpace()
                    < FREE_SPACE_RESERVE_BYTES + CACHE_FRAGMENT_BYTES) {
                    synchronized (lock) {
                        if (gen == generation) {
                            failedGeneration = gen; failedAtReadHead = readHead;
                            retryAttempts = RETRY_DELAYS_NS.length + 1; state = "low_storage";
                        }
                    }
                    continue;
                }

                Uri requestUri = Uri.parse(uri);
                DataSpec spec = new DataSpec.Builder().setUri(requestUri).setPosition(position)
                    .setLength(chunkLength).setFlags(DataSpec.FLAG_ALLOW_CACHE_FRAGMENTATION).build();
                AtomicLong newBytes = new AtomicLong();
                CacheWriter writer = null;
                Exception failure = null;
                try {
                    writer = new CacheWriter(writerCacheFactory.createDataSourceForDownloading(), spec, workerBuffer,
                        (requestLength, bytesCached, newlyCachedBytes) -> newBytes.addAndGet(newlyCachedBytes));
                    synchronized (lock) {
                        if (closed || suspended || gen != generation) writer.cancel();
                        else activeWriter = writer;
                    }
                    writer.cache();
                } catch (IOException | RuntimeException e) { failure = e; }
                finally {
                    synchronized (lock) { if (writer != null && activeWriter == writer) activeWriter = null; }
                }

                long currentCacheBytes = cacheBytes;
                if (failure == null) {
                    try { currentCacheBytes = cache.getCacheSpace(); }
                    catch (RuntimeException e) { failure = e; }
                }
                synchronized (lock) {
                    if (closed) return;
                    if (gen != generation || suspended) continue;
                    if (failure != null) {
                        boolean rangeEof = failure instanceof HttpDataSource.InvalidResponseCodeException
                            && ((HttpDataSource.InvalidResponseCodeException) failure).responseCode == 416;
                        long eof = responseTotalLength(failure);
                        if (rangeEof) {
                            if (eof >= 0) totalLength = eof;
                            else totalLength = position;
                            cursor = Math.max(cursor, totalLength);
                            failedGeneration = generation;
                            failedAtReadHead = readHead;
                            retryAttempts = RETRY_DELAYS_NS.length + 1;
                            state = "ready";
                            aheadBytes = 0;
                            continue;
                        }
                        failedGeneration = generation;
                        failedAtReadHead = readHead;
                        failures++;
                        retryAttempts++;
                        if (retryAttempts <= RETRY_DELAYS_NS.length) {
                            retryAtNs = System.nanoTime() + RETRY_DELAYS_NS[retryAttempts - 1];
                            state = "queued";
                        } else state = "error";
                        aheadBytes = Math.max(0, cursor - readHead);
                        continue;
                    }
                    cursor = position + chunkLength;
                    retryAttempts = 0; failedAtReadHead = -1;
                    completedChunks++;
                    downloadedBytes += newBytes.get();
                    cacheBytes = currentCacheBytes;
                    updateAheadLocked();
                    state = cursor >= ReadAheadWindow.targetEnd(readHead, totalLength, lookaheadBytes)
                        ? "ready" : "running";
                }
            }
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        } catch (RuntimeException ignored) {
            synchronized (lock) {
                failures++;
                state = "error";
                failedGeneration = generation;
                failedAtReadHead = readHead;
                retryAttempts = RETRY_DELAYS_NS.length + 1;
                lock.notifyAll();
            }
        } finally {
            if (closed) state = "closed";
        }
    }

    private static long responseTotalLength(Exception failure) {
        if (!(failure instanceof HttpDataSource.InvalidResponseCodeException)) return C.LENGTH_UNSET;
        Map<String, List<String>> headers = ((HttpDataSource.InvalidResponseCodeException) failure).headerFields;
        for (Map.Entry<String, List<String>> entry : headers.entrySet()) {
            if (!"content-range".equalsIgnoreCase(entry.getKey()) || entry.getValue().isEmpty()) continue;
            String value = entry.getValue().get(0).trim();
            int slash = value.lastIndexOf('/');
            if (slash < 0 || slash == value.length() - 1 || "*".equals(value.substring(slash + 1))) return C.LENGTH_UNSET;
            try { return Long.parseLong(value.substring(slash + 1)); }
            catch (NumberFormatException ignored) { return C.LENGTH_UNSET; }
        }
        return C.LENGTH_UNSET;
    }

    private static long totalFromHeaders(Map<String, List<String>> headers, long position, long openedLength,
                                         boolean originalLengthUnset) {
        for (Map.Entry<String, List<String>> entry : headers.entrySet()) {
            if (!"content-range".equalsIgnoreCase(entry.getKey()) || entry.getValue().isEmpty()) continue;
            String value = entry.getValue().get(0).trim();
            int slash = value.lastIndexOf('/');
            if (slash >= 0 && slash + 1 < value.length() && !"*".equals(value.substring(slash + 1))) {
                try { return Long.parseLong(value.substring(slash + 1)); }
                catch (NumberFormatException ignored) { return C.LENGTH_UNSET; }
            }
        }
        return originalLengthUnset && openedLength >= 0 && position <= Long.MAX_VALUE - openedLength
            ? position + openedLength : C.LENGTH_UNSET;
    }

    private static final class TrackingDataSource implements DataSource {
        private final DataSource delegate;
        private final ReadAheadCache owner;
        private final BufferedByteReader buffered = new BufferedByteReader(IO_BUFFER_BYTES);
        private final BufferedByteReader.Source physicalReader;
        private DataSpec dataSpec;
        private String uri;
        private long openedLength, totalLength, bytesRead, lastSignalBytes = -1;

        TrackingDataSource(DataSource delegate, ReadAheadCache owner) {
            this.delegate = delegate; this.owner = owner;
            physicalReader = this::readPhysical;
        }

        @Override public void addTransferListener(TransferListener listener) { delegate.addTransferListener(listener); }

        @Override public long open(DataSpec spec) throws IOException {
            dataSpec = spec; uri = spec.uri.toString(); bytesRead = 0; lastSignalBytes = -1;
            buffered.reset(0);
            owner.opening(uri, spec.position);
            long started = owner.foregroundStarted();
            try { openedLength = delegate.open(spec); }
            finally { owner.foregroundFinished(started); }
            buffered.reset(openedLength);
            totalLength = totalFromHeaders(delegate.getResponseHeaders(), spec.position, openedLength,
                spec.length == C.LENGTH_UNSET);
            owner.opened(uri, spec.position, openedLength, totalLength, spec.length == C.LENGTH_UNSET);
            return openedLength;
        }

        @Override public int read(byte[] buffer, int offset, int length) throws IOException {
            // Matroska reads many 1-10 byte headers. FileDataSource otherwise
            // turns each of those into a RandomAccessFile read, starving sample
            // queues even with ample cached data. Track consumed, not prefetched,
            // bytes so extractor positions and seek/read-ahead ownership stay exact.
            int count = buffered.read(physicalReader, buffer, offset, length);
            if (count > 0) {
                bytesRead += count;
                if (ReadAheadWindow.shouldSignalReadHead(bytesRead, lastSignalBytes)) {
                    lastSignalBytes = bytesRead;
                    owner.readHead(uri, dataSpec.position + bytesRead, totalLength);
                }
            }
            return count;
        }

        private int readPhysical(byte[] target, int offset, int length) throws IOException {
            long started = owner.foregroundStarted();
            try { return delegate.read(target, offset, length); }
            finally { owner.foregroundFinished(started); }
        }

        @Override public Uri getUri() { return delegate.getUri(); }
        @Override public Map<String, List<String>> getResponseHeaders() { return delegate.getResponseHeaders(); }
        @Override public void close() throws IOException {
            dataSpec = null; uri = null; bytesRead = 0; lastSignalBytes = -1;
            buffered.reset(0);
            delegate.close();
        }
    }
}
