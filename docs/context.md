# DualTheater project context

Last updated: 2026-10-30 (UTC).

This is the shared handoff for Codex sessions. Read it before starting work, then inspect the current repository and applicable `AGENTS.md` instructions. **Keeping this file current is mandatory:** update it after meaningful milestones, decisions, tests or blockers, and before a substantive handoff or publication. See [the full update rules](../AGENTS.md).

## Purpose and acceptance target

Use an existing Windows laptop or desktop PC, compatible Android TV/Google TV and HDMI sound system to play high-quality 4K remuxes without buying another dedicated media player, such as an NVIDIA Shield.

The primary target is native TV HDR video, untouched Dolby TrueHD Atmos over HDMI, and stable physical A/V sync. This is an **experimental beta, still in testing**. Simultaneous playback has been observed; accurate physical lip-sync has not yet been established. Avoid describing the project as a finished replacement for a dedicated player.

## Branch publication — completed 2026-10-30

The user explicitly authorized committing/pushing main and both feature branches and publishing their builds, superseding the earlier local-only restriction. The branches remain separate; no feature timing was merged into main. Main's original v0.4.1-beta.1 assets remain unchanged. Published feature builds: [preview v0.5.0-beta.2](https://github.com/shadow-pheonix/dualtheater/releases/tag/v0.5.0-beta.2) (phone 0.1.0-beta.1) and [Robust Sync v0.6.0-beta.1](https://github.com/shadow-pheonix/dualtheater/releases/tag/v0.6.0-beta.1) (phone 0.1.1-beta.1).

Windows CI passed on all three lines, including real mpv null-output tests, EXE builds and frozen GUI/resource/host-start-stop/downloader checks. Android assembly, JVM tests and lint passed. Robust Sync's real source-timestamp sampler and Windows CNG AES vector passed. CI does not test acoustic latency, real TV/phone/S95TR behavior, active HDMI routing or HDR/Atmos reception.

Feature EXEs, TV/phone APKs, source ZIPs and checksum manifests were downloaded from CI and checked before publication. Public downloads were independently checked against GitHub SHA-256 digests and manifests; APK signatures/package identities and ZIP integrity/privacy/provenance passed. Old release asset IDs/digests/sizes were unchanged. Release assets stay pinned to the validated build commits; later branch documentation commits do not rebuild or overwrite those assets.

- Main verification: https://github.com/shadow-pheonix/dualtheater/actions/runs/41021485992
- Preview verification: https://github.com/shadow-pheonix/dualtheater/actions/runs/41021504117
- Robust Sync verification: https://github.com/shadow-pheonix/dualtheater/actions/runs/41021507447

Build provenance (distinct from later branch documentation heads):

| Branch | Release build commit |
| --- | --- |
| `main` / v0.4.1-beta.1 | `eebf9a256fb50d54640022ad6a190d29f50926c2` |
| `feature/playback-reliability` / v0.5.0-beta.2 | `17a2057519c50da71a910dafb385d355a1df300f` |
| `feature/robust-sync` / v0.6.0-beta.1 | `d06248b5d66005e2121b3adc46ebabb22287d5b5` |

All Windows Python checks passed without skips: 46 main, 66 preview and 85 Robust Sync. Source ZIP contents match their pinned commits under Windows checkout line-ending conversion. BUILD-INFO.json in each feature release records the original CI payload hashes; its full public manifest also covers that build-info file. Main has no phone APK. Later documentation-only changes do not alter binaries or tags.

## Current public state

### Published desktop beta 0.4.1-beta.1

The portable Windows x64 EXE has Connect, Player and Settings/help pages. Python/Tk are bundled. **Download mpv** fetches the checksum-pinned official Windows x64 package directly from upstream, extracts its nested runtime ZIP with all DLLs, checks startup without audio and automatically selects it. Managed files are verified before offline reuse. Downloads are explicit; there is no silent player update or mpv redistribution in our EXE/assets. Browse preserves custom builds. [Package provenance and recovery](player-download.md).

Installation is staged under private app data, and failures/cancellation retain prior players. GUI setup, pairing, calibration and downloaded runtimes survive EXE replacement. Go to Player is now a stronger, right-aligned button beside Start/Disconnect, preventing its earlier clipping below the pairing text. Layout and click-through were visually verified in an isolated native preview. The user confirmed the new setup works; this feedback does not establish new HDMI/HDR or physical-sync results. The GUI continues to use the existing shared coordinator/barrier. Matching original Windows/Android icons and TV banner are retained. Android version code is 7; this release changes no TV playback behavior.

Local checks: all 46 Python tests passed with the actual upstream-downloaded runtime, including 11 downloader/worker tests and four real-mpv TrueHD/null-output tests. The 19 desktop/downloader tests and later 11 downloader tests also passed after their respective refinements. The rebuilt frozen EXE independently passed real download/verification/extraction/automatic selection, external-player device enumeration, GUI/resources and temporary host start/stop checks without HDMI playback. Android debug build, all 10 JVM tests, lint and APK signature verification passed. Final documentation checks covered 31 relative links/anchors and 11 PowerShell blocks; privacy/resource/code-path scans passed and locked v0.1.1 hashes remain unchanged.

[GitHub validation and publication](https://github.com/shadow-pheonix/dualtheater/actions/runs/40663740138) passed, including all 46 Python tests with real mpv/null output and the frozen EXE download/selection check. All four public assets were independently downloaded; GitHub SHA-256 digests, checksum manifest, source-archive integrity/privacy and APK signature were verified. The downloaded EXE independently passed the download/selection/GUI/resources/external-player/local-host smoke test. Physical HDMI passthrough using this specific downloaded mpv build, desktop HDR/Atmos reception and accurate lip-sync remain unverified.

- Repository: [shadow-pheonix/dualtheater](https://github.com/shadow-pheonix/dualtheater), public, default branch `main`.
- Published version: [v0.4.1-beta.1](https://github.com/shadow-pheonix/dualtheater/releases/tag/v0.4.1-beta.1), explicitly a prerelease. Earlier release assets and locked snapshots remain unchanged.
- Downloads: portable Windows x64 EXE, development-signed TV APK, optional source/CLI ZIP and SHA-256 checksums. No Windows installer or Python installation is required for the EXE. First mpv download requires Internet; cached playback does not. Source/CLI users still install Python and select mpv manually.
- The README documents current downloads, automatic setup, navigation, operations and recovery; optional source/ADB commands are in `docs/command-line.md`. `AGENTS.md` mandates same-change updates whenever instructions become outdated.
- `main` can include documentation changes after the release. Existing release assets are immutable under the workflow; application changes need a new beta version.
- Compatibility depends on actual TV, firmware, format and HDMI endpoint. The laptop/desktop needs HDMI output, or a display/audio-capable USB-C port with a compatible HDMI adapter. Data/charging-only USB-C is insufficient. Adapter TrueHD remains unverified.

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
- Native Windows control is the default; the optional browser controller is Windows-local. Default ports: browser TCP 8764, media TCP 8765, control TCP 8766 and discovery UDP 8767. Run only one host against these ports.
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
- v0.4.0-beta.1: native portable desktop, friendly saved setup, matching icons and shared host lifecycle published and independently verified. Its local baseline was 35 Python tests, 10 Android JVM tests and packaged GUI/resource/start-stop checks; mpv required manual selection.
- Public commit identity uses a GitHub noreply address. Initial publication metadata was cleaned up with user authorization; cached earlier GitHub objects may still exist. Future commits should use the repository's configured noreply identity and normal Git authentication.

## Code map and routine commands

| Path | Responsibility |
| --- | --- |
| `host/server.py` | HTTP/control services, shared playback operations, readiness and recovery |
| `host/mpv.py`, `host/select_audio.lua` | Local mpv IPC, compressed output and audio-track selection |
| `host/sync.py` | Clock estimates and video drift servo |
| `host/discovery.py`, `host/pairing.py` | Discovery, pairing and remembered credentials |
| `host/controller.html` | Local Windows browser controller |
| `host/player_download.py` | Explicit upstream download, integrity checks, safe staged extraction and private offline runtime |
| `host/desktop.py`, `host/desktop_support.py`, `desktop_main.py` | Native desktop pages, private preferences, device selection and background host operations |
| `tools_src/build_windows.py`, `requirements-build.txt` | Standalone Windows packaging with bundled resources, icon, version and runtime licenses |
| `assets/`, `tools_src/generate_icons.py` | Original matching vector/Windows artwork and Android TV banner generation |
| `android/app/src/main/java/dev/dualtheater/tv/` | TV UI, native video playback, remote controls, discovery and control client |
| `tests/`, Android `app/src/test/` | Host/protocol/integration and Android JVM tests |
| `.github/workflows/beta.yml` | Windows CI tests, Android build/lint, packaging and prerelease creation |

The source host uses Python 3.10+ and the standard library/Tkinter. Windows packaging uses Python 3.11 x64 and pinned build tools in `requirements-build.txt`; the published EXE requires no Python installation. Android currently pins Media3 1.9.0, AGP 8.13.2 and Gradle 8.13; use JDK 17/21, SDK Platform 36 and Build Tools 36.1.0. Recheck build files before changing dependencies.

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

- 2026-10-28: Published and independently verified beta 0.4.1 with the user-approved mpv download alternative and improved Go to Player placement. Local and CI software checks passed as recorded above; the initial CI test-only short-path assertion was corrected to compare resolved Windows paths. README/setup/provenance/operating instructions are current. Physical output and A/V sync still require hardware acceptance.

- 2026-10-27: Published the shared context and mandatory agent handoff rules. Clarified existing-hardware purpose and explicit Windows laptop/desktop HDMI or display-capable USB-C requirements; adapter TrueHD remains untested.
- 2026-10-27: Added prominent direct beta APK/Windows ZIP/checksum links and documented download/extraction, prerequisites, optional ADB sideloading, host commands, pairing, movie loading, remote/browser operation, track changes, manual sync, reconnection and shutdown. Distinguished released functionality from proposed automatic calibration; no Windows installer or automatic calibration is claimed.
- 2026-10-28: Finished the README guide and mandatory same-change instruction updates after an interrupted publishing attempt. Documentation verification checks all nine PowerShell blocks, 17 relative links/anchors, launcher/host flags, UI labels, release-runtime consistency, content/privacy and Git whitespace. No commands were executed against playback hardware and no new hardware tests were performed for these edits.
- 2026-10-28: Published and independently verified the portable desktop and matching Windows/Android icons for beta 0.4.0-beta.1. Added shared lifecycle/rollback, private desktop storage, friendly endpoint selection, native movie/seek/track controls, reconnect reload gating and coordinated close. Updated README operating instructions, optional CLI guide and CI. Local and GitHub software/packaging checks passed as recorded above. Real-device desktop HDR/Atmos/lip-sync validation is the remaining acceptance work.
