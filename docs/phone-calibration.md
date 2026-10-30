# DualTheater Calibration Preview — phone client

Experimental phone version `0.1.1-beta.1` accompanies Windows/TV Robust Sync `0.6.0-beta.1` and remains compatible with the earlier preview protocol. No separate physical reference fixture is required. The client estimates sound/picture offset from camera exposure timestamps and microphone capture-sample timestamps. Absolute physical accuracy remains unvalidated.

## Install and connect

1. Run the matching Windows Robust Sync host and connect **DualTheater TV Robust Sync** normally. Preserve the base apps; published `0.4.1-beta.1` does not support this phone client. Run only one Windows host at a time.
2. Sideload the phone APK, `calibration-debug.apk` from the module build output or `DualTheater-Calibration-v0.1.1-beta.1-debug.apk` when packaged. Open **DualTheater Calibration Preview**. Android 8 or newer is required. Its package, `dev.dualtheater.calibration.preview`, is separate from the TV/base apps.
3. Put the phone, TV and computer on the same trusted LAN. On the phone, press **Find computers**, select the computer, enter the six-digit code shown on Windows **Connect** (or its source-host terminal/browser) and press **Connect**.
4. Later connections reuse a private per-phone credential; leave the code empty for saved pairing. If discovery is blocked, enter the LAN address and control port manually. Default control TCP 8766 and discovery UDP 8767 are shared with the TV; no additional port is required. The phone has a separate calibration role and does not occupy the TV socket.

Connections retain the project's cleartext, trusted-LAN model. Do not expose them to the Internet. Phone and TV receive distinct remembered credentials, using the same displayed short code for first pairing.

## Run and apply

For a build comparison, select the desired mode on Windows **Connect** while disconnected, reconnect/reload and start at zero Video lead. The phone status identifies the mode. Complete a test without Apply to measure first; each mode saves its own correction only after Apply. See the [comparison procedure](robust-sync.md). The unchanged published main host does not support this protocol; use the new branch's baseline mode for the same-clip numerical comparison.

1. Position the phone steadily at the listening seat, in landscape, with the TV centered in the camera guide. Keep the room quiet and use the built-in microphone; Bluetooth, USB and headset input are unsupported in v1.
2. Press **Start calibration / verify again** and grant camera/microphone permissions. This replaces the current movie with the reference clip; reload the movie afterward.
3. The phone stabilizes exposure and capture clocks before asking Windows to play the reference through the existing coordinated TV/HDMI path. Keep still until six flash/beep pairs are detected. The 22-second reference uses irregular intervals and 1 kHz/40 ms beeps, avoiding silent whole-period pairing errors.
4. Capture stops and numerical measurements go to Windows. Both players pause. Review sound-early/sound-late timing, repeat spread, capture-resolution estimate and suggested **Video lead**.
5. Press **Apply suggested Video lead** to save it on Windows. Nothing is applied automatically. The test stays paused; the next coordinated start uses the new setting. Run another test to verify, or reload the movie on Windows.

**Cancel test**, app backgrounding, capture failure or phone disconnection cancels the test. Windows pauses it when it still owns that playback. A transport/TV/offset or observed media/receiver-context change invalidates old results. Stale run IDs and repeated Apply are rejected. Offset saves are atomic and preserve the previous value if replacement fails.

The reference is original SDR H.264 with stereo TrueHD and **no Atmos**. It exercises the normal compressed-audio path but does not prove HDR/Atmos reception or identical latency for every movie. Keep TV/receiver modes consistent and check the actual movie afterward.

## Timing and accuracy

Camera2 must report REALTIME timestamps, exposure-lock support and usable exposure/rolling-shutter metadata. Images match capture metadata by timestamp. The center-region flash onset is bracketed using exposure intervals; image callback arrival time is not event time.

AudioRecord captures mono 48 kHz PCM and requests TIMEBASE_BOOTTIME timestamps, comparable to the same elapsed-realtime clock. Recent sample-position anchors map beep samples to capture time. The app checks clock jumps, stale extrapolation, route changes and stalled reads. It requests UNPROCESSED audio where advertised, otherwise VOICE_RECOGNITION; zero input-processing bias is not guaranteed.

The detector matches all six cues independently in each stream. Windows uses the median sound-minus-light gap: positive means sound is late. Proposed Video lead is `previous lead − median gap`. Repeat spread is the maximum deviation from that median. The capture-resolution estimate combines camera onset brackets and microphone timing intervals. It does not include an independently measured phone bias.

All six pairs are required. Gap/setting values outside ±2000 ms, repeat spread above 40 ms or capture-resolution estimates above 40 ms are rejected. Mode selection requests a stable 30–60 fps analysis stream, with runtime continuity checks. Missing or unknown timestamps are rejected; callback timestamps are not substituted. No Windows/phone clock synchronization or network trigger timing enters the event difference.

No generic camera/microphone delivery delay is added. A separate reference fixture is optional future validation, not a prerequisite. Repetition shows consistency; it cannot independently prove absolute accuracy.

## Privacy and recovery

Camera frames and PCM stay in memory and are discarded. No recordings are saved/uploaded. Only numerical measurements, status and pairing/control messages travel to Windows. Private Android preferences retain pairing and host selection; backup is disabled. There is no background camera/microphone service.

- **Unsupported timestamps / exposure lock:** this phone's selected camera is unsupported in v1.
- **Missing cues / excessive variation:** center the TV, steady the phone, reduce noise, make the test beep audible and retry. Brighten the screen/room if shorter exposure is requested.
- **Stalled capture / changed microphone route:** close other capture apps, disconnect headsets and retry.
- **Playback changed / resynchronization occurred:** wait for stability and start a new test; measurements across recovery/seek are rejected.
- **TV missing:** connect the matching TV companion first. The phone cannot replace it.

## Build

With the [documented JDK/SDK](../README.md#build-and-test), on Windows run:

```powershell
.\Build-Calibration.ps1
```

This copies `DualTheater-Calibration-debug.apk`. Direct module build/check commands are:

```powershell
.\android\gradlew.bat --project-dir android :calibration:assembleDebug :calibration:testDebugUnitTest :calibration:lintDebug
```

Linux/macOS use `./android/gradlew`. The module APK is `android/calibration/build/outputs/apk/debug/calibration-debug.apk`. Root `assembleDebug testDebugUnitTest lintDebug` checks both Android modules. See the [Windows EXE build instructions](../README.md#build-and-test) or [source CLI guide](command-line.md). A fresh source ZIP/checkout with `Start.cmd` supports the phone without building an EXE; use a separate source folder or `--data-dir` for private state.

`tests/make_phone_calibration.py` regenerates the original reference using an external FFmpeg build tool. Regeneration requires reviewing decoded cue timing and deliberately updating the pinned SHA-256. FFmpeg is not a playback dependency or bundled app binary.

Synthetic tests cover capture-clock drift/discontinuities, quiet/noisy tones, read boundaries, onset brackets, missing cues and clock-origin invariance. Host tests cover paired phone/TV coexistence, explicit Apply, stale results, cancellation/disconnect and save failure. These checks do not replace real phone/TV/HDMI acceptance.
