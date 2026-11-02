# Changelog

## 1.0.0 — stable, 2026-11-02

- Promote the calibrated audio-clock build to main after the user reported excellent sync on the tested setup. Retain original timing and video servo as selectable alternatives.
- Include source-timestamped audio, the remote TV clock, coordinated seek/play-pause, phone measurement/Apply and sanitized diagnostics.
- Fix premature timing timeouts, stale reply handling and false phase jumps from renderer/receipt timestamp ordering. Reconnect timing within the control session and reacquire a fresh clock before loading/starting; require explicit resume after a timing fault.
- Include calibration reference-EOF completion grace and bounded numeric detector diagnostics, plus correctly rotated/aspect-preserved phone preview and detection guide.
- Version Windows, TV and phone as 1.0.0, retaining tested package IDs/private profiles for update continuity. Add stable Windows version metadata and stable release packaging/provenance/checksums.
- Audio remains 1.0x compressed TrueHD; video remains original-byte native TV playback. Hardware/HDR-profile compatibility, absolute accuracy and long-session reliability retain the documented limits.

## 0.6.1-beta.1 — local calibration completion/diagnostics fix (unreleased)

- Phone 0.1.2-beta.1 logs numeric flash/beep detections and relative onset intervals via `DTCalibration`; capable hosts also receive bounded progress telemetry.
- Normal reference EOF permits a three-second completion window and reports missing detector counts. Manual playback/context changes still invalidate capture.
- Complete six-pair validation and explicit Apply remain required; no accuracy thresholds, audio timing or TV synchronization algorithms changed.

## 0.6.0-beta.1 — historical Robust Sync comparison

- Separate main-based branch and isolated desktop/TV identity; original timing, improved video-servo and remote-audio-clock modes with independent zero-default offset files.
- Source-timestamped mpv samples, bounded affine clock/timeline estimation and a separate authenticated timing stream on the existing control port.
- Stock Media3 video renderer with a remote audio MediaClock, lifecycle/offset handling, startup progress verification and confidence/watchdog pauses. Audio stays at 1x with original TrueHD packets.
- Optional codec-rendered feedback with bounded PTS/epoch correlation; scheduled release is kept distinct from physical presentation.
- Read-only LG S95TR settings and Windows HDMI latency inspection. Added AV delay and unknown total processing latency remain distinct; no guessed correction is applied.
- Mode/provenance/context diagnostics, profile-change indication, and phone client `0.1.1-beta.1` showing the active algorithm. Measurement precedes explicit Apply.
- New source desktop launcher and comparison guide. Software testing does not establish improved physical lip-sync; Windows/TV/S95TR acceptance is still pending.

## 0.5.0-beta.2 — historical phone calibration v1

- Separate Android phone calibration preview `0.1.0-beta.1`, LAN discovery/pairing and foreground Camera2/AudioRecord capture without a separate physical reference fixture.
- Comparable capture-clock timestamps, tone/sample detection, exposure/rolling-shutter onset intervals and complete irregular six-cue matching.
- Original 22-second SDR/stereo TrueHD reference, source cue timing verification and checksum-pinned host playback through the existing coordinator.
- Numerical results, repeat spread/capture-resolution estimates and explicit saved-offset Apply. Raw images/audio stay in memory. No validated absolute-accuracy claim.
- Cancellation/disconnect pause handling, stale-result checks and atomic offset saves. New phone build script and APK packaging in CI. Base apps/releases remain unchanged.

## 0.5.0-beta.1 — unreleased feature branch

- Additional Diagnostics page and local-browser JSON export with an explicit field allowlist that excludes personal media, network, device and pairing data.
- Bounded drift statistics, operation latency/failure counters, categorized recovery/disconnect counts and TV buffer/transfer/frame-drop telemetry.
- Playback epochs scoped to TV connections, allowing host restart and rejecting callbacks from earlier playback generations. Reconnect still requires reloading the movie.
- Separate development version; published 0.4.1 assets and the base branch remain unchanged. Physical-device acceptance is pending.
- Preview desktop profile and Android application ID are separate from the base apps, preserving their saved setup during development testing.

## 0.4.1-beta.1 — automatic mpv setup

- Download mpv directly from its official Windows release inside the desktop app; checksum verification, nested ZIP extraction, DLL retention and automatic selection.
- Private offline cache with file-integrity checks, staged installation, cancellation and manual Browse fallback.
- Go to Player is aligned with the connection buttons, avoiding clipping below the pairing instructions.
- Upstream-download and real-mpv null-output checks in release CI, plus external-player startup from the frozen EXE.

mpv is not redistributed in the EXE. HDMI passthrough with this downloaded build and physical A/V sync still need hardware testing.

## 0.4.0-beta.1 — portable Windows desktop beta

- Single-file Windows x64 EXE with included Python/Tk runtime; no installer or console required.
- Connect, Player and Settings/help pages, friendly audio-device selection, native movie picker, timeline, exact/relative seeking and track controls.
- Saved mpv/HDMI setup and private application-data storage; remembered setup starts the connection automatically when the saved endpoint is available.
- Shared host lifecycle for CLI and GUI, rollback on startup failure and coordinated shutdown/reload handling.
- Matching original dual-screen app icons for Windows/Android and a branded Android TV launcher banner.
- Windows packaging and packaged GUI/resource/start-stop smoke tests in release CI.

mpv remains a separate executable selected once. Physical A/V sync and HDR/Atmos behavior through the desktop build still need device testing.

## 0.3.0-beta.1 — experimental public beta

- Public Android TV/Google TV positioning with device-dependent HDR compatibility.
- Native TV hardware video plus Windows HDMI TrueHD passthrough.
- Coordinated transport, calibration and video-side drift correction.
- TV remote seeking/play-pause and a bottom timeline.
- Laptop discovery, one-time code entry and remembered pairing.
- Portable launch/build scripts and sanitized public documentation.

Still in testing: physical A/V sync, broader device support and long-session reliability. This prerelease is not a stable compatibility claim.
