# Beta testing status

This release is **experimental and still in testing**. Limited successful operation does not establish broad Android TV/Google TV compatibility or stable physical A/V synchronization.

## Software verification

The unreleased `feature/playback-reliability` branch adds diagnostic report, fast-reconnect and preview-profile isolation tests plus Android playback-session regressions. On the Linux development workspace, 52 Python tests passed with four Windows/mpv-only tests skipped (56 total). Android debug assembly, all 14 Gradle JVM tests and APK signature/package checks passed. Lint completed with zero errors and 23 warnings. The new Windows Diagnostics page and export flow have packaged smoke-test coverage configured for Windows CI; that configured check has not run on this branch. This Linux interpreter lacks Tkinter, so no native desktop GUI run is claimed. No new hardware acceptance results are available. See [context](context.md) and [diagnostic semantics](diagnostics.md).

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
