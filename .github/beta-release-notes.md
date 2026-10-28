## Experimental beta — still in testing

DualTheater separates local playback across an Android TV/Google TV and a Windows HDMI audio path: native TV hardware video decoding, original TrueHD Atmos packets through mpv, and coordinated controls/timing over the home network.

This candidate adds a **Diagnostics** page with bounded drift statistics, TV buffer/transfer/frame-drop measurements and operation/recovery/failure counters. **Export sanitized report…** saves an allowlisted JSON summary without movie names, paths, addresses, device identifiers, pairing data or raw logs. The optional localhost browser controller offers the same export. Missing or stale telemetry is identified explicitly. [Report meaning and privacy](https://github.com/shadow-pheonix/dualtheater/blob/feature/playback-reliability/docs/diagnostics.md).

The TV resets playback epochs per accepted connection and invalidates earlier callbacks, allowing a restarted Windows host to use lower epochs. Reconnect and reload the movie before resuming; automatic position restoration is not included. This development branch is separate from the preserved 0.4.1 base build and is not yet published.

The candidate desktop is **DualTheater Preview**, with a separate `%LOCALAPPDATA%\DualTheater-Preview` profile. **DualTheater TV Preview** uses `dev.dualtheater.tv.preview`, so it can coexist with the base TV app without replacing its settings. Use the matching preview apps together and run only one Windows host at a time.

The portable Windows x64 EXE retains Connect, Player and Settings/help, friendly audio-device selection, a native movie picker, timeline/seek controls, saved setup and explicit checksum-verified mpv download. Python/Tk are included; no installer or terminal is required. Original-file streaming, strict TrueHD passthrough and the shared audio-led synchronization barrier are retained.

**Not a stable release.** Physical lip-sync, long-session reliability, broader device coverage and newer connection/remote features still need real-device testing. API timing values and null-output tests do not prove acoustic sync or correct HDR/Atmos reception.

Download the **Windows EXE** and matching **Android debug APK**. Click **Download mpv** on Connect (first setup needs Internet), or Browse to your existing compatible `mpv.exe`, choose the HDMI soundbar/receiver and start the TV connection. Python is needed only for the optional source ZIP/command-line host. Prove standalone HDMI TrueHD passthrough before testing dual-device playback. See the repository README for setup, operation, limitations and checksums.

The EXE is an unsigned experimental build. Settings, pairing and calibration are stored privately under `%LOCALAPPDATA%\DualTheater` and survive EXE replacement. First-time migration from the older source launcher may require re-pairing; older source-folder state is left intact. mpv is not bundled in our assets; its download starts only when you click **Download mpv**. Its private cache survives EXE replacement. [Download provenance/recovery](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/player-download.md).

Debug APKs are development-signed. A differently signed existing installation may need to be uninstalled before this APK can be installed. CI-generated debug keys are not kept or published.

Use only on a trusted home network. No media films, pairing credentials, personal network details, private logs or signing keys are included.
