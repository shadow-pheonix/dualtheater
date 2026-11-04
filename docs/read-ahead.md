# TV disk read-ahead

Version 2.0 includes an app-private cache of the original container bytes to reduce video-buffer underruns. Windows still owns transport and sends untouched compressed audio through HDMI. The TV's native decoder, encoded video/HDR metadata and heap-aware sample-buffer budget are unchanged. Older stable 1.0 downloads do not contain this feature.

## How it works

The TV keeps up to 512 MiB of committed cache data and targets up to 128 MiB ahead of the extractor's actual byte position. These are byte limits, not a guaranteed duration for a variable-bitrate remux. The background worker uses a 128 KiB I/O buffer, reads bounded ranges and commits cache fragments as they arrive. Old chunks are evicted automatically.

The worker verifies contiguous coverage using [Media3's cache-length API](https://developer.android.com/reference/androidx/media3/datasource/cache/Cache) and fills the first missing range. A previous completed-download cursor cannot establish that data remains cached after eviction. Cache-index checks run outside the UI/loader coordination lock; reported ahead bytes follow the verified prefix rather than the old download high-water mark.

After filling the target, the worker waits until coverage falls to 96 MiB, then refills toward 128 MiB in ranges of up to 8 MiB. A missing range at the read head starts immediately. This avoids repeated small HTTP/cache transactions for each 256 KiB read-head update. Foreground extraction coalesces tiny Matroska header reads into a 128 KiB buffer; logical consumed positions, original bytes and requested range boundaries remain unchanged, and seek/reopen discards unread prefetched bytes. The experimental **2.0.3-beta.1 child** also rebases the logical read head immediately on each extractor open, including same-URI forward/backward/small reopens. Far reopens cancel the old writer generation; same-URI length knowledge, consumed-byte accounting, notification throttling and existing cache budgets are preserved. It no longer waits for 256 KiB of consumption before scheduling the new position.

Foreground playback reads the cache without writing to it. When a background download owns an upcoming range, the loader consumes its committed fragments instead of racing a duplicate HTTP download. Other misses use direct HTTP. Preparation and seeking take priority: background work is cancelled/suspended until the matching native READY/seek-completion state. Existing shared Windows pause/prepare/start barriers remain in control.

The implementation uses [Media3 CacheDataSource](https://developer.android.com/reference/androidx/media3/datasource/cache/CacheDataSource) and cache fragmentation supported by [Media3 DataSpec](https://github.com/androidx/media/blob/1.9.0/libraries/datasource/src/main/java/androidx/media3/datasource/DataSpec.java). Downloads use short connection/read deadlines and bounded retry delays. Cancellation does not wait on network I/O on the UI thread. One process-scoped cache avoids reopening the same cache directory during Activity recreation; each Activity cancels its own worker when stopped/destroyed.

## Storage and fallback

The cache lives in the TV app's internal cache storage, with no storage permission or folder grant required. It is temporary data, not an exported movie library. A 1 GiB free-space reserve is retained; initialization requires enough free space for that reserve and the cache budget. Small in-flight files and the cache index add some overhead to the committed budget. Insufficient storage or a cache failure leaves direct playback available. After freeing storage, restart the TV app to retry an initially disabled cache. Android's **Clear cache** removes these temporary movie chunks.

The cache cannot compensate for indefinitely unavailable storage/network or sustained throughput below the movie's required rate. Actual exhausted buffers still trigger coordinated recovery, preserving the synchronization safety policy.

For controlled development comparisons, launching the Activity with the boolean intent extra `disable_read_ahead=true` bypasses cache allocation and background downloads for that Activity. Normal launches retain the default. This is a diagnostic switch, not an accepted cure for playback faults; earlier TCP/cache and direct-streaming comparisons interrupted playback. Current UDP/cache acceptance and its limits are recorded in [context](context.md).

## Diagnostics and verification

The diagnostic report's `telemetry.read_ahead` contains a fixed state name plus byte budgets, cached/ahead/downloaded byte counts, completed chunks and failures. States include `preparing`, `queued`, `running`, `ready`, `low_storage`, `error` and `disabled`. No cache key, URL, media name or local path is exported. Counts describe the active app/worker lifetime; ahead bytes are relative to the extractor, and the normal movie progress bar still reports Media3's timeline buffering.

`foreground_wait_ms` describes the currently active foreground open/read, or zero when none is pending. `max_foreground_wait_ms` is the longest completed open/read in the Activity lifetime, including preparation/seeks. These are I/O observations, not playback latency or physical lip-sync measurements.

Native loading, allocated sample-buffer bytes, total buffered milliseconds and Java heap use are reported separately. Cached bytes do not prove that demuxing or decoding is keeping up; native-buffer depletion must be investigated even when disk coverage is healthy.

Pure tests cover window/chunk/EOF bounds, overflow, read-head throttling and seek detection. Run `python tools_src/verify_cache_controller.py --java-home "<JDK directory>"` from the source root for the experimental scheduling regression. It compiles the actual cache controller/byte reader against inert Android/cache APIs and verifies new worker ranges plus patterned byte identity across reopens. The old parent controller fails the same-URI assertion. This does not measure real disk/network contention, throughput or Android scheduling. Device tests must separately verify original-byte range delivery, first load, repeated seek/pause/resume, cache growth, lifecycle/reconnection and sustained playback. A passing software suite or a short movie run does not establish whole-film reliability or physical lip-sync.
