# Beta testing status

This release is **experimental and still in testing**. Limited successful operation does not establish broad Android TV/Google TV compatibility or stable physical A/V synchronization.

## Software verification

2026-10-30 publication validation: Windows CI passed **46 main**, **66 preview** and **85 Robust Sync** Python tests without skips, including the configured real-mpv/null-output checks. Each line built and smoke-tested its portable EXE and passed Android assembly/JVM tests/lint. Robust Sync also passed its source-timestamp and CNG AES checks. Published downloads, source commits, signatures and hashes were independently verified. The previous Linux-only results below are historical; actual HDMI/CIM routing and physical TV/phone/S95TR accuracy remain untested. See [branch/release/commit provenance](context.md#branch-publication--completed-2026-10-30).

The experimental `feature/robust-sync` version 0.6.0-beta.1 includes the three-mode comparison engine, source timestamps, dedicated timing transport, remote renderer clock, receiver inspection and optional phone 0.1.1-beta.1. On the Linux development workspace, **79 Python tests passed and six Windows-only tests were skipped (85 total)**. Both Android debug apps assembled; **33 JVM tests passed (22 TV, 11 phone)**. Lint completed with zero errors, 23 TV warnings and 14 phone warnings. APK signatures, package identities and launcher activities were checked. Source/JavaScript syntax, documentation links and archive/privacy verification are recorded in [context](context.md).

New tests exercise known clock skew/asymmetry/large origins, replay/outlier rejection, holdover uncertainty, source-position regression, time-based servo behavior, renderer clock lifecycle/stream offsets, monotonic slew and expiry, signed start leads and retired codec callback rejection. Real local sockets with simulated endpoints verify advancing startup rather than ACK alone, seek, timing-link loss with audio pause, role authentication, independent mode offsets, applying saved audio-clock changes only at the next barrier, and phone measurement before explicit Apply. Receiver tests cover fragmented/bounded read-only protocol messages, malformed settings, EDID checksums/unknown fields and sanitized export. These are software checks, not hardware accuracy results.

Windows CNG AES and real mpv source-sampler/null-output tests are included but were skipped here. The packaged smoke check requires the new Lua resource. The real Windows WASAPI source clock, CNG/CIM/HDMI route, frozen EXE/native GUI and physical TV/S95TR/phone capture remain unvalidated. The earlier feature branch's recorded 66-test/25-JVM result is historical. No new hardware acceptance results are available.

Phone tests exercise synthetic sample clocks, jitter/discontinuity rejection, quiet/noisy tone detection, read boundaries, event intervals, missing cues and same-phone clock-origin invariance. Host integration checks cover the phone role alongside a connected simulated TV, explicit Apply, stale-result rejection, cancel/disconnect and atomic save failure. The original reference was decoded with external FFmpeg: all six video flashes matched their specified source frames, and detected audio onsets differed by at most one 48 kHz sample (about 0.021 ms), below the 0.1 ms source check. This validates source cue alignment only. It does not prove physical camera/microphone accuracy, panel latency, HDMI reception or movie-mode compatibility. See [phone setup and limitations](phone-calibration.md).

Downloader coverage includes verified nested extraction and DLL retention, offline reuse, checksum failures, cancellation, unsafe paths, wrong architecture, cache damage/recovery, manual selection and worker shutdown/error recovery. CI downloads the actual pinned upstream package and uses it for the optional real-mpv TrueHD/null-output tests. The frozen EXE also enumerates audio devices through that external runtime, without opening HDMI. These checks do not establish HDMI capability of that mpv build on a particular device.

The desktop beta adds checks for private settings persistence/corruption recovery, friendly WASAPI device selection, partial bind rollback, full host shutdown and queued desktop transport against a simulated TV. A packaged-EXE smoke test opens the native GUI invisibly, verifies its embedded HTML/Lua resources, starts temporary local host services and closes them. It never loads a film or opens HDMI. Local visual checks cover the Connect, Player and Settings/help layouts and Windows icon. Android build/lint/JVM tests also check packaging after the icon/banner change; they do not establish how a specific TV launcher displays it.

The development suite includes Python clock/servo tests, HTTP integrity and range tests, authenticated remote command/barrier tests, UDP discovery, remembered pairing and failure recovery. Optional Windows tests exercise real mpv with TrueHD packets and **null output**. Android JVM tests cover seek previews, request matching, time formatting, discovered-host validation and pairing-code handling.

Null-output tests do not open an HDMI receiver, decode HDR on a TV or prove acoustic lip-sync. Passing simulated clock/barrier tests is not a hardware accuracy guarantee. Android build/lint and APK signature checks provide packaging evidence, not device compatibility evidence.

## Limited hardware observations

Simultaneous native TV video decoding and receiver-reported TrueHD Atmos playback have been observed on one Android TV setup. A heap-aware buffer budget corrected an observed allocation failure. A physical HDMI connection issue was also encountered during testing.

These observations are intentionally anonymized. No raw device/network logs, private endpoint IDs, movie names, user paths or personal test reports are distributed.

## Still needs validation

- More Android TV/Google TV hardware and firmware combinations.
- Actual HDR mode and Dolby Vision profile behavior, including any enhancement-layer limitations.
- Discovery/pairing behavior across real home networks.
- TV remote actions, receiver relock and physical lip-sync after seek/resume.
- Long-session drift, high-bitrate peaks and network disruption recovery.

Use the [hardware test guide](hardware-test.md) before treating a setup as reliable.
