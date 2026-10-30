# Robust Sync comparison build

Branch: `feature/robust-sync`. Compare main baseline **v0.4.1-beta.1** first, then this separate experimental build at zero Video lead before applying phone calibration. No experimental timing has been merged into main.

Download the Windows x64 EXE and matching TV APK. The EXE includes Python/Tk. Use Download mpv or Browse to the identical runtime and HDMI endpoint used for baseline. Optional phone APK: **0.1.1-beta.1**. Verify assets with SHA256SUMS.txt.

Select the timing algorithm on Connect while disconnected:

- **Original timing (baseline):** main's timing algorithm with branch diagnostics/reconnect/phone support.
- **Video servo (experimental):** source-timestamped audio, affine clock estimation and uncertainty-aware video correction.
- **Audio clock (experimental):** default; the TV renderer clock follows Windows audio anchors, with startup progress checks and timing-failure pauses.

Each mode saves a separate zero-default offset. In Audio clock mode a saved change takes effect at the next coordinated start/resynchronization. Phone measurements can be reviewed without Apply. The SDR/stereo TrueHD reference does not establish identical HDR/Atmos or 4K-load behavior.

Settings includes read-only LG S95TR status and Windows HDMI latency inspection. Added AV delay and declared HDMI latency remain separate from unknown total soundbar processing delay; no guessed compensation is applied. The unofficial S95TR protocol and actual route/firmware remain unverified on the user's unit.

Windows app: **DualTheater Robust Sync**, private state `%LOCALAPPDATA%\DualTheater-RobustSync`. TV app: **DualTheater TV Robust Sync**, ID `dev.dualtheater.tv.robustsync`, preserving base and preview installations. Phone retains `dev.dualtheater.calibration.preview`; a different CI signing certificate can require uninstall/reinstall and re-pairing. Run one Windows host at a time. Reload media after reconnect or calibration.

Original media, compressed TrueHD and audio 1x are preserved. This remains experimental: no improved physical lip-sync or real TV/phone/S95TR/HDMI accuracy is established. The Windows EXE is unsigned; APKs are development-signed. Use a trusted home LAN. mpv downloads explicitly and is not bundled.

[Installation and comparison guide](https://github.com/shadow-pheonix/dualtheater/blob/feature/robust-sync/docs/robust-sync.md) · [Phone guide](https://github.com/shadow-pheonix/dualtheater/blob/feature/robust-sync/docs/phone-calibration.md) · [Research](https://github.com/shadow-pheonix/dualtheater/blob/feature/robust-sync/docs/sync-research.md)

Build provenance: [`d06248b5d66005e2121b3adc46ebabb22287d5b5`](https://github.com/shadow-pheonix/dualtheater/commit/d06248b5d66005e2121b3adc46ebabb22287d5b5) on `feature/robust-sync`. [Successful Windows/Android CI](https://github.com/shadow-pheonix/dualtheater/actions/runs/41021507447) passed all 85 Windows Python tests, real-mpv/null-output checks, the frozen GUI smoke test, Android assembly/JVM tests and lint. BUILD-INFO.json maps the branch/commit/run to the CI artifact hashes; SHA256SUMS.txt covers every attached payload. No physical playback was tested.
