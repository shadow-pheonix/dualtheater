# Playback diagnostics and phone calibration preview

Branch: `feature/playback-reliability`. This is separate from the preserved main baseline `v0.4.1-beta.1` and the Robust Sync comparison build `v0.6.0-beta.1`.

Download the Windows x64 EXE and matching TV APK. The EXE includes Python/Tk. On Connect, use Download mpv or Browse to the same runtime used for your baseline test, choose your HDMI endpoint and pair the TV app. The optional phone APK is **0.1.0-beta.1**. Use SHA256SUMS.txt to verify assets.

This build adds sanitized diagnostics/export, host-restart/reconnect protection and the first timestamp-based camera/microphone calibration client. Phone calibration uses an original SDR/stereo TrueHD reference without Atmos and requires no separate physical reference fixture. Measure first, then explicitly Apply if desired; reload your movie afterward. Camera frames and microphone PCM stay in memory.

The Windows app is **DualTheater Preview**, with private state under `%LOCALAPPDATA%\DualTheater-Preview`. The TV app **DualTheater TV Preview** uses `dev.dualtheater.tv.preview`, preserving the base app. Phone ID: `dev.dualtheater.calibration.preview`. Run only one Windows host at a time. Reconnect requires reloading the movie.

Original media, TrueHD packets and audio speed remain untouched. This is experimental; real TV/phone/HDMI behavior, physical lip-sync and long-session reliability remain unvalidated. Software/null-output testing does not prove acoustic sync or HDR/Atmos reception.

The Windows EXE is unsigned, and APKs are development-signed. A different APK certificate requires uninstall/reinstall and re-pairing. Only use the services on a trusted home LAN; mpv is downloaded explicitly and is not bundled.

[Setup](https://github.com/shadow-pheonix/dualtheater/blob/feature/playback-reliability/README.md) · [Phone guide](https://github.com/shadow-pheonix/dualtheater/blob/feature/playback-reliability/docs/phone-calibration.md) · [Diagnostics](https://github.com/shadow-pheonix/dualtheater/blob/feature/playback-reliability/docs/diagnostics.md)

Build provenance: [`17a2057519c50da71a910dafb385d355a1df300f`](https://github.com/shadow-pheonix/dualtheater/commit/17a2057519c50da71a910dafb385d355a1df300f) on `feature/playback-reliability`. [Successful Windows/Android CI](https://github.com/shadow-pheonix/dualtheater/actions/runs/41021504117) passed all 66 Windows Python tests, real-mpv/null-output checks, the frozen GUI smoke test, Android assembly/JVM tests and lint. BUILD-INFO.json maps the branch/commit/run to the CI artifact hashes; SHA256SUMS.txt covers every attached payload. No physical playback was tested.
