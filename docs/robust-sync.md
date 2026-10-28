# Robust Sync experimental build and comparison

Branch: `feature/robust-sync`, based on main commit `7debf90`. Windows/TV version: **0.6.0-beta.1**. Phone version: **0.1.1-beta.1**. This is a local experimental implementation, not a published release or a physical accuracy guarantee. The original `main` and `feature/playback-reliability` builds are preserved.

## Install and launch

Keep the published base apps installed. Sideload this build's TV APK and open **DualTheater TV Robust Sync**. Its application ID, `dev.dualtheater.tv.robustsync`, is separate from the base and earlier preview apps. Use the matching Windows host. Only one Windows host can run at a time because service ports and the desktop mutex are shared.

For the source ZIP, install Windows Python 3.10+ with Tk support, extract into a fresh folder and double-click **Start-Desktop.cmd**. Alternatively, run:

```powershell
python desktop_main.py
```

The desktop saves setup under `%LOCALAPPDATA%\DualTheater-RobustSync`. It does not import or overwrite either previous profile. Choose the same mpv executable and WASAPI HDMI endpoint used for your baseline test. **Download mpv** is still available; use **Browse…** to select the identical existing runtime for a controlled comparison. Connect the PC to the soundbar's HDMI input as before.

On **Connect**, select a **Sync mode**, then **Start TV connection** and pair the Robust Sync TV app. Disconnect before changing modes. Reload the movie after connecting/reconnecting. The choices are:

| UI choice | Behavior |
| --- | --- |
| Original timing (baseline) | Main's lowest-RTT clock filter, frame-release comparison, median/deadband and video-speed servo. Shares branch diagnostics/reconnect/phone support; it is not a byte-identical main build. |
| Video servo (experimental) | Source-timestamped audio, affine clock estimation, media-timeline comparison and uncertainty-aware phase/frequency correction. Video remains within 0.995–1.005x. |
| Audio clock (experimental) | Default. A renderer-supplied TV media clock follows timestamped Windows audio anchors. Media3 retains hardware decode and refresh-aware frame scheduling. The host does not run a competing speed servo. |

Each mode starts with a zero offset and stores its own `calibration-baseline.json`, `calibration-servo.json` or `calibration-audio-clock.json` in private app data. Existing base/preview calibration is not copied. Saved values include manual/phone provenance and the observed media/receiver context. A changed context is flagged on Player; unknown receiver processing delay remains unknown. A saved audio-clock adjustment takes effect at the next coordinated start/resynchronization, rather than jumping the live clock.

For a terminal/source host instead of the desktop:

```powershell
.\Start.ps1 -SyncMode audio-clock
.\Start.ps1 -SyncMode servo
.\Start.ps1 -SyncMode baseline
```

Run one command at a time. Each prompts for the existing mpv/HDMI selection if needed. Direct Python also supports `--sync-mode baseline|servo|audio-clock` and `--data-dir`; the default source-host data directory is the isolated RobustSync profile. Default ports are unchanged: UI TCP 8764, media TCP 8765, control/timing TCP 8766, discovery UDP 8767. Timing uses a second, session-authorized TCP connection on the same listener; no new firewall port is required.

## Compare before calibrating

1. Test the unchanged published/main build first. Record the movie, selected track, TV picture/refresh mode, receiver input/sound mode and whether playback/seek/resume looks synchronized. Keep these details locally; do not publish personal media or addresses.
2. Close the base Windows host. Start this host, select **Original timing (baseline)**, connect the matching TV app and set **Video lead** to **0** for the initial comparison. Export a sanitized report from **Diagnostics** after a comparable segment.
3. Disconnect, select **Audio clock (experimental)**, reconnect/reload and repeat at zero lead. Try **Video servo (experimental)** as a separately recorded compatibility comparison. Never silently change algorithms during a measurement.
4. Compare startup, seek/resume, a sustained high-bitrate scene, dropped frames, recoveries, clock uncertainty and timing distributions. A small reported drift is software evidence, not measured panel/speaker sync.
5. Only after the uncorrected comparison, use the optional phone app in each desired mode. Its status shows the host's mode. **Start calibration / verify again** measures first; inspect the result without pressing Apply to retain the zero offset. **Apply suggested Video lead** saves only that mode's correction. Repeat to verify, then reload the movie.

The phone's own capture resolution/bias limits what size of improvement it can establish. The current reference remains 720p SDR H.264, 24 fps and stereo TrueHD without Atmos; it does not validate a different HDR/Atmos processing mode or 4K bitrate load. No separate physical reference fixture is required. The published main host does not support the phone; use this branch's baseline mode for the same-clip numerical comparison.

## LG S95TR and HDMI inspection without the phone

Pause playback. On **Settings & help**, enter the S95TR's private network address and click **Inspect LG S95TR**. The probe sends only allowlisted status reads over TCP 9741 and never sends a settings, input, power or volume command. A device may nevertheless light its display or wake in response to status reads. This is an unofficial protocol; support on the user's firmware is unvalidated.

The report distinguishes the **added AV-delay setting** (community interpretation: 10 ms units) from **total processing delay**, which remains unknown. A zero added delay is not zero Atmos/DSP latency. The probe also records available input/mode IDs. It is an explicit snapshot, not a background receiver monitor; inspect again after changing receiver settings. No correction is applied from these readings.

**Inspect HDMI latency** reads active Windows display descriptors and reports any declared audio/video latency. It discards raw descriptors and identifying fields from its result. The declaration may be absent or describe an HDMI/repeater path different from the TV app's video path. It is not automatically combined with the S95TR setting, since doing so could double-count delay. No guessed soundbar latency or universal physical-sync claim is introduced.

Probe results and the mode appear in sanitized diagnostics. Network addresses, pairing/timing credentials, raw descriptors and device serials are excluded. Probe snapshots are held in memory for the host/service session. Automatic clock alignment works without a phone; accurate physical compensation for an unreported receiver delay still needs a usable latency declaration or another observation.

## Timing and failure behavior

The new modes correlate host/TV monotonic clocks with a bounded low-delay affine estimate. Timestamped mpv samples use the script's clock around the audio-position read, mapped to host time, so IPC arrival is not treated as sample time. The software budget retains RTT/asymmetry, sampling span, residual and aging uncertainty. Frequency bounds are assumptions under test, not certified hardware limits.

Audio anchors are sampled approximately every 40 ms without an application backlog. The timing writer is bounded and separate from transport commands. The TV accepts fresh, sequenced, current-epoch anchors, slews monotonically within the video bounds and exposes acquisition/lock/slew/holdover/failure state. Its renderer clock carries media/renderer offsets through enable, start, stop, seek and stream replacement. The host verifies fresh advancing audio/video after scheduled start and pauses on timing/clock failure. Ordinary buffering and sustained servo error use the existing coordinated recovery barrier with a retry limit. Audio stays at 1x and compressed TrueHD remains untouched.

Frame metadata is explicitly scheduled-release evidence. An optional codec observer correlates actual rendered events with submitted PTS and generations; late callbacks retain the event time, and missing feedback does not block playback. The experimental control path compares media timelines, avoiding automatic compensation for Media3's early codec release. Reports do not label codec rendering as panel light or WASAPI as receiver acoustic output.

## Build and validation limits

Build the TV/phone with the existing Gradle wrapper or `Build-TV.ps1` / `Build-Calibration.ps1`. On Windows, build the EXE with:

```powershell
python -m pip install -r requirements-build.txt
python tools_src/build_windows.py --dist dist/windows --work build/windows
```

The existing CI workflow can validate/package the branch through manual workflow dispatch; its publish job is restricted to `main`. No push, workflow dispatch, merge or publication is performed by this local implementation.

The Linux development environment can assemble/sign debug APKs and run Python/JVM tests. Windows CNG, CIM/HDMI inspection, real mpv/WASAPI and the frozen native GUI require Windows validation. Real TV, S95TR and phone testing remain necessary before claiming improved physical sync. See [research and candidate decisions](sync-research.md), [phone details](phone-calibration.md) and [hardware acceptance](hardware-test.md).
