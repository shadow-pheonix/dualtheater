# Architecture

The Windows host serves the original seekable media file byte-for-byte over HTTP. The Android TV/Google TV companion extracts video and passes it to a supported hardware MediaCodec through Media3. It has no audio renderer. The original container includes unused audio bytes; this uses additional network bandwidth but avoids remuxing and metadata changes.

The same local file is read by mpv on Windows for compressed TrueHD output through WASAPI exclusive mode. mpv IPC stays on a randomly named local Windows pipe. The network protocol exposes only a small set of playback operations, not arbitrary mpv commands.

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

## Connection

UDP discovery advertises a laptop name, stable ID and control port, with a matching random probe nonce. Codes and credentials are not advertised. First-time six-digit pairing issues a long remembered per-TV credential. Legacy manual session tokens remain supported. See [connection setup](easy-connection.md).

The accepted control socket's local interface supplies media URLs, which helps avoid accidental VPN address advertisement. The browser controller accepts only local Host/Origin values and a session token. Media endpoints expose only the selected file.

## API references

- [mpv manual](https://mpv.io/manual/master/): WASAPI, compressed output properties, audio timing and JSON IPC.
- [Media3 supported formats](https://developer.android.com/media/media3/exoplayer/supported-formats): extraction does not guarantee device HDR support.
- [Video frame timing](https://developer.android.com/reference/androidx/media3/exoplayer/video/VideoFrameMetadataListener): presentation and scheduled release timestamps.
- [Android HDR playback](https://source.android.com/docs/core/display/hdr): platform/device decoding and display capabilities.
- [Android key events](https://developer.android.com/reference/android/view/KeyEvent): remote transport input.
