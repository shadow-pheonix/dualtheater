# DualTheater 1.0.0 — stable

The tested audio-clock player is now the main release. After phone calibration and timing-recovery fixes, the user reported that sync looks perfect on the tested setup. This is a single-setup observation; other hardware, HDR profiles, absolute accuracy and whole-film reliability continue to need testing.

## Downloads and setup

Download the Windows x64 portable EXE and matching TV APK. Optional: Android phone calibration APK. All three components are version 1.0.0. Verify with SHA256SUMS.txt; BUILD-INFO.json records source commit, CI run and payload hashes. The source ZIP supports terminal operation with Python and mpv.

1. Connect your Windows laptop/desktop HDMI output (or display-capable USB-C HDMI adapter) to your soundbar/receiver's HDMI IN.
2. Open the Windows EXE, use **Download mpv** or **Browse…** for your tested player, choose HDMI audio and keep **Audio clock (recommended)** selected.
3. Start the connection. On **DualTheater TV**, select the computer and enter the six-digit code once.
4. Choose/load a TrueHD movie on Windows, then Play. TV remote left/right seeks and middle/OK controls coordinated play/pause.
5. Adjust Video lead manually or use **DualTheater Calibration** on a supported phone. Measure first; Apply is explicit. Reload the movie after a calibration test.

## Included fixes

- Source-timestamped audio anchors, remote TV clock and synchronized transport; TrueHD stays compressed at 1.0x and video is not transcoded.
- Timing timeout/stale-reply handling, TV timestamp-ordering fix, dedicated timing reconnection and fresh-clock preflight before load/start.
- Safe pause on timing faults; reconnection requires explicit resume. A full control reconnect requires reloading media.
- Reference-EOF completion grace, numeric detector diagnostics, camera-preview rotation/aspect correction and aligned detection guide.
- Diagnostics/export and optional read-only receiver/HDMI inspection. Inspection does not infer or automatically apply physical latency.

## Updating and limits

The tested Robust Sync package IDs and Windows profile are retained: TV `dev.dualtheater.tv.robustsync`, phone `dev.dualtheater.calibration.preview`, Windows `%LOCALAPPDATA%\DualTheater-RobustSync`. Matching signatures retain pairing/settings. APKs are development-signed; CI signing keys are ephemeral, so upgrading a local/older differently signed APK requires uninstall/reinstall and re-pairing. Preserve private Windows profiles. The EXE is unsigned and downloads mpv separately; mpv is not bundled.

TV codec/HDR profile support is device-dependent; Dolby Vision Profile 7/FEL reconstruction is not promised. The phone reference is SDR/stereo TrueHD without Atmos and does not establish identical movie-mode latency. Phone camera/microphone absolute bias is unvalidated. Subtitles are not implemented. Use a trusted LAN; no public port forwarding. Previous beta releases/assets remain unchanged.

[Download and operating instructions](https://github.com/shadow-pheonix/dualtheater/blob/main/README.md) · [Terminal commands](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/command-line.md) · [Phone guide](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/phone-calibration.md) · [Testing status](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/testing.md)
