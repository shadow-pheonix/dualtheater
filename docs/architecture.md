# Architecture

The following describes implemented playback behavior. The separate `feature/robust-sync` branch's [research and implementation decision](sync-research.md) proposes a renderer-supplied remote audio clock and explicit receiver/output-latency handling; that architecture has not been implemented or measured yet.

The Windows host serves the original seekable media file byte-for-byte over HTTP. The Android TV/Google TV companion extracts video and passes it to a supported hardware MediaCodec through Media3. It has no audio renderer. The original container includes unused audio bytes; this uses additional network bandwidth but avoids remuxing and metadata changes.

The same local file is read by mpv on Windows for compressed TrueHD output through WASAPI exclusive mode. mpv IPC stays on a randomly named local Windows pipe. The network protocol exposes only a small set of playback operations, not arbitrary mpv commands.

## Windows interfaces and storage

The native Tk desktop (`host/desktop.py`) and optional CLI share `Coordinator` and `HostRuntime` in `host/server.py`. The desktop sends slow operations to a background worker and polls status separately, keeping file selection/navigation responsive while the existing transport barrier waits for readiness. It adds no alternative timing engine and does not change mpv passthrough flags or the video servo.

On the unreleased playback-reliability branch, `host/diagnostics.py` keeps bounded timing samples and fixed session counters. Reports copy only explicitly approved numerical/boolean/enum fields, without raw snapshots or mpv IPC. The desktop worker saves reports atomically; the existing localhost controller exposes the same report under its token/Host/Origin restrictions. Android supplies observed transfer rate and reported frame-drop counts. See [diagnostic semantics and privacy](diagnostics.md).

The development desktop uses a separate `DualTheater-Preview` private profile and taskbar identity. It retains the shared single-instance mutex and default service ports, so it must not run alongside the base host. The candidate TV APK uses `dev.dualtheater.tv.preview` with the existing Java namespace, allowing it to coexist with the base TV app without replacing its private preferences.

`HostRuntime` binds the required services, rolls back partial startup failures and closes owned resources on shutdown. Desktop setup and media controls remain local Python calls; they are not new unauthenticated network endpoints. The optional browser controller retains its existing localhost/token restrictions.

The portable EXE bundles Python, Tk, HTML/Lua resources, app artwork and upstream license notices through PyInstaller. Runtime resources follow `__file__` inside the bundle; writable state is explicitly separate under `%LOCALAPPDATA%\DualTheater`. The CLI still defaults to its source folder and optionally accepts `--data-dir`. Desktop mpv/endpoint preferences are in `settings.local.json`; unreadable settings are preserved before explicit replacement. The desktop does not import old credentials automatically or overwrite a different application's settings. mpv remains a separate process. The user-initiated downloader in `host/player_download.py` fetches a pinned official x64 ZIP directly from upstream over HTTPS, verifies its size/SHA-256, validates/extracts the nested ZIP and probes the executable without audio. It keeps all runtime DLLs adjacent. Installation is staged under private app data and renamed into place only after validation; incomplete downloads do not replace an existing player. A file-hash receipt validates the managed cache before automatic reuse. Manual mpv selection remains supported. See [player setup](player-download.md).

## Timing

- Host time uses `perf_counter_ns`; TV time uses `System.nanoTime`.
- Four-timestamp exchanges estimate clock offset and round-trip delay. Recent low-RTT samples are preferred.
- mpv `audio-pts` accounts for driver delay. IPC query timing contributes measurement uncertainty.
- Media3's frame listener supplies presentation time and scheduled surface release time. Stale, unset or mismatched-generation samples are rejected.
- The servo compares video position to audio position plus a calibrated video lead. It applies a deadband/median filter and bounds video speed to 0.995–1.005×. Audio stays at 1.0×.

The timing model does not measure actual panel or acoustic latency. The TV may not respond accurately to small speed changes. Physical lip-sync remains an experimental acceptance criterion.

## Transport barrier

1. Pause both devices and cancel stale scheduled starts.
2. Retain a canonical requested media anchor, seek mpv exactly, and wait for playback restart and seek completion.
3. Seek the TV under a fresh epoch; wait for READY, completed seeking and the expected position.
4. Verify compressed TrueHD output, select a future deadline, and require the TV's start acknowledgement.
5. Resume with calibrated video/audio deadlines, then correct residual error using fresh frame/audio feedback.

Paused audio-only `time-pos` may include residual output-buffer delay, so it is not used as proof that the requested seek anchor was reached. Buffering and sustained large drift can trigger a barrier; repeated failures pause with an error.

TV remote work is queued to a separate operation worker. The socket reader continues receiving the acknowledgements that worker needs, avoiding a reader-thread deadlock. Request IDs and epochs reject duplicate or stale input. Repeated direction events form one preview before committing a seek.

The development TV scopes its playback epoch to an accepted control connection. Connection reset clears old media and advances a separate callback generation, so a restarted host can reuse lower epoch numbers without making old scheduled callbacks valid. Within a connection, epoch monotonicity is preserved. Frame-listener replacement also retains its independent callback generation.

## Connection

The `0.5.0-beta.2` preview accepts `hello` with `role: calibration` for a separately paired phone. This role does not replace `Coordinator.peer` and cannot submit arbitrary media paths or mpv commands. Its bounded, sequenced requests expose status/start/complete/apply/cancel. `host/calibration.py` owns one phone connection and one run at a time. A background run worker uses the existing coordinator lock/actions to load the pinned reference, prepare, play and pause while the TV reader continues receiving ACKs. Results are validated and only explicitly applied against the same TV/media/epoch/previous offset. The phone sends numerical measurements only. Disconnect/shutdown cancels owned work; unrelated replacement playback is not stopped. See [phone capture and protocol behavior](phone-calibration.md).

UDP discovery advertises a laptop name, stable ID and control port, with a matching random probe nonce. Codes and credentials are not advertised. First-time six-digit pairing issues a long remembered per-TV credential. Legacy manual session tokens remain supported. See [connection setup](easy-connection.md).

The accepted control socket's local interface supplies media URLs, which helps avoid accidental VPN address advertisement. The browser controller accepts only local Host/Origin values and a session token. Media endpoints expose only the selected file.

## API references

- [mpv manual](https://mpv.io/manual/master/): WASAPI, compressed output properties, audio timing and JSON IPC.
- [Media3 supported formats](https://developer.android.com/media/media3/exoplayer/supported-formats): extraction does not guarantee device HDR support.
- [Video frame timing](https://developer.android.com/reference/androidx/media3/exoplayer/video/VideoFrameMetadataListener): presentation and scheduled release timestamps.
- [Android HDR playback](https://source.android.com/docs/core/display/hdr): platform/device decoding and display capabilities.
- [Android key events](https://developer.android.com/reference/android/view/KeyEvent): remote transport input.
