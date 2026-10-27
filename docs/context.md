# DualTheater project context

Last updated: 2026-10-27 (Asia/Calcutta).

This is the shared handoff for Codex sessions. Read it before starting work, then inspect the current repository and applicable `AGENTS.md` instructions. **Keeping this file current is mandatory:** update it after meaningful milestones, decisions, tests or blockers, and before a substantive handoff or publication. See [the full update rules](../AGENTS.md).

## Purpose and acceptance target

Use an existing Windows laptop or desktop PC, compatible Android TV/Google TV and HDMI sound system to play high-quality 4K remuxes without buying another dedicated media player, such as an NVIDIA Shield.

The primary target is native TV HDR video, untouched Dolby TrueHD Atmos over HDMI, and stable physical A/V sync. This is an **experimental beta, still in testing**. Simultaneous playback has been observed; accurate physical lip-sync has not yet been established. Avoid describing the project as a finished replacement for a dedicated player.

## Current public state

- Repository: [shadow-pheonix/dualtheater](https://github.com/shadow-pheonix/dualtheater), public, default branch `main`.
- Published version: [v0.3.0-beta.1](https://github.com/shadow-pheonix/dualtheater/releases/tag/v0.3.0-beta.1), explicitly a prerelease. Android version code is 5.
- Downloads: development-signed TV APK, matching Windows host/source ZIP and SHA-256 checksums. Python and mpv are installed separately.
- `main` can include documentation changes after the release. Existing release assets are immutable under the current workflow; a new application release requires a new beta version.
- Public documentation and app positioning are brand-independent. Compatibility depends on the actual TV, firmware, format and HDMI endpoint.

## Architecture and invariants

1. The Windows standard-library Python host serves the selected original MKV byte-for-byte with HTTP range support. It currently sends the complete container, including audio bytes the TV does not render; it does not demux a video-only network stream or transcode.
2. The TV app uses Media3/ExoPlayer with hardware MediaCodec video decoding and a SurfaceView. It has no audio renderer. Preserve the heap-aware buffer budget, which fixed a real allocation failure.
3. A separate Windows mpv instance reads the same local file and bitstreams compressed TrueHD through WASAPI exclusive mode to an explicit HDMI endpoint. Normal playback rejects PCM fallback. The user's known-working baseline was `--vid=no --ao=wasapi --audio-exclusive=yes --audio-spdif=truehd`; the host also adds IPC and coordination controls.
4. The audio clock is master. Clock exchanges align host/TV monotonic time; the host compares driver-adjusted audio timing with scheduled video-frame timestamps. Small corrections change **video speed only**, bounded to 0.995–1.005x. Audio speed remains 1.0x.
5. Start, pause, seek, track changes and recovery use a shared pause/prepare/scheduled-start barrier. Epochs and request IDs reject stale operations. TV remote actions are processed by the host's operation worker, leaving the socket reader free to receive acknowledgements.
6. Calibration compensates for fixed output latency. API clocks do not measure actual panel light or acoustic output; a low reported drift does not prove lip-sync.

Do not change TrueHD packet timing through resampling or audio speed correction. Do not bypass the shared barrier with independent TV seeks or resumes. See [architecture and timing details](architecture.md).

## Implemented controls and connection

- TV left/right: seek preview in 10-second steps; held/repeated input accumulates a larger jump before commit.
- Middle/OK: coordinated play/pause. A seek while paused stays paused. OK during a preview commits the position and toggles the final play state.
- Bottom timeline: elapsed/total time and buffered progress; shows while paused, buffering or synchronizing, and hides after five seconds of playback. Up/down show it; Back cancels a seek preview.
- UDP laptop discovery, six-digit first-time pairing and saved per-TV credentials support reconnection without repeatedly entering network numbers. Advanced/manual connection remains available.
- Browser control is local to the Windows machine. Default ports: browser TCP 8764, media TCP 8765, control TCP 8766 and discovery UDP 8767.
- Pairing/control/media are cleartext for a trusted home LAN. Do not expose the ports publicly. Reconnecting currently requires reloading media on Windows; automatic playback restoration is not validated.

## Verification: distinguish evidence from expectations

### Software baseline already completed

At public-beta preparation on 2026-10-27:

- All 27 Python tests passed locally, including four optional real Windows mpv integration tests using **null output**. These did not open HDMI.
- All 10 Android JVM tests passed. Android debug build and lint passed.
- GitHub validation and publication passed. Its Python run discovered 27 tests and skipped the four optional real-mpv tests because mpv was not configured there.
- The downloaded public APK signature, release asset checksums and the 49-file source archive passed verification. The archive file count describes that release, not later `main` revisions.

These are historical results, not checks automatically rerun in every session. The tests exercise clocks, drift logic, original-byte HTTP ranges, pairing/discovery, remote commands, seek/pause barriers and failure recovery. They cannot prove HDR output or physical lip-sync.

### Limited hardware observations

- On one setup, native TV picture and simultaneous normal HDMI audio were observed; the user confirmed the sound system indicated Atmos.
- An initial audio-noise problem also occurred with the original standalone mpv executable. Adjusting the HDMI cable restored normal audio, suggesting a physical connection issue. Do not assume that symptom proves an application regression.
- A TV allocation failure was corrected with a heap-aware sample-buffer limit.
- The user later turned the TV off and removed HDMI during a power outage. Do not assume devices are currently available, connected or ready for ADB/playback.

### Still unverified on physical devices

- Accurate lip-sync at initial start and after remote seeking, play/pause and receiver relock.
- Newer TV remote/timeline and discovery/pairing behavior on the actual TV; these have software-test coverage, not completed hardware acceptance.
- Long-session drift, high-bitrate peaks, network disruption and reconnect behavior across devices.
- HDR10/HDR10+/Dolby Vision behavior for each source and TV. Dolby Vision Profile 7/FEL reconstruction is not promised; Profile 5 must not be assumed to have an HDR10-compatible base layer.

See [testing status](testing.md) and [hardware acceptance steps](hardware-test.md). Record future user observations with clear attribution and without private device details.

## History worth preserving

- v0.1.1: simultaneous native TV video and receiver-indicated Atmos were observed; a local known-working snapshot was locked at the user's request. If those historical artifacts are present in a working environment, preserve them unchanged. They are not bundled in this public source tree.
- v0.2.0: coordinated TV remote seeking/play-pause and bottom timeline added.
- v0.3.0: discovery, one-time pairing and remembered connection added.
- v0.3.0-beta.1: sanitized public experimental beta published with portable launch/build scripts and a CI release workflow.
- Public commit identity uses a GitHub noreply address. Initial publication metadata was cleaned up with user authorization; cached earlier GitHub objects may still exist. Future commits should use the repository's configured noreply identity and normal Git authentication.

## Code map and routine commands

| Path | Responsibility |
| --- | --- |
| `host/server.py` | HTTP/control services, shared playback operations, readiness and recovery |
| `host/mpv.py`, `host/select_audio.lua` | Local mpv IPC, compressed output and audio-track selection |
| `host/sync.py` | Clock estimates and video drift servo |
| `host/discovery.py`, `host/pairing.py` | Discovery, pairing and remembered credentials |
| `host/controller.html` | Local Windows browser controller |
| `android/app/src/main/java/dev/dualtheater/tv/` | TV UI, native video playback, remote controls, discovery and control client |
| `tests/`, Android `app/src/test/` | Host/protocol/integration and Android JVM tests |
| `.github/workflows/beta.yml` | Windows CI tests, Android build/lint, packaging and prerelease creation |

The host uses Python 3.10+ and the standard library. Android currently pins Media3 1.9.0, AGP 8.13.2 and Gradle 8.13; use JDK 17/21, SDK Platform 36 and Build Tools 36.1.0. Recheck build files before changing dependencies.

```powershell
python -m unittest discover -s tests -v
.\android\gradlew.bat --project-dir android assembleDebug testDebugUnitTest lintDebug
.\Start.ps1 -ListDevices
```

Set `DUALTHEATER_MPV` to a local executable path to enable optional real-mpv null-output tests. Do not put that personal path in tracked files. `Start.cmd` launches the host; [README](../README.md) has user setup instructions.

The included calibration clip is original SDR H.264 video with stereo TrueHD and **no Atmos**. It is not an HDR/Atmos validation sample. Debug APK signing can differ between CI runs and local builds; a different certificate requires uninstall/reinstall and recreating TV pairing settings.

## Next work

1. When the user has power and devices available, validate remote seek/play-pause, discovery and pairing on hardware.
2. Calibrate physical A/V offset and check repeated seek/resume operations before claiming stable sync. Log measured drift separately from the user's perceived/externally measured lip-sync.
3. Test longer sessions, high-bitrate passages and interruption recovery; refine only issues supported by evidence.
4. Expand TV/profile coverage without assuming universal HDR support. Keep the beta status until the acceptance criteria are demonstrated.

No current hardware validation results should be invented to close these items. Do not store private addresses, media filenames, personal paths, endpoint identifiers, credentials, raw logs or signing keys in this context.

## Recent progress

- 2026-10-27: Clarified the README's purpose: use existing Windows hardware to reduce the need for a separate dedicated media player. Published using the public noreply identity.
- 2026-10-27: Added this shared handoff, root agent instructions requiring frequent context updates, and a README link for future sessions. Documentation-only work; the content/privacy scan, all 14 relative links in the three edited documents and the Git whitespace check passed. No new player or hardware tests are claimed for this edit.
