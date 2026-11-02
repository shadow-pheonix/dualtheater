# DualTheater project context

Last updated: 2026-11-02 (Asia/Calcutta).

This is the shared handoff for Codex sessions. Read it before starting work, then inspect the current repository and applicable `AGENTS.md` instructions. **Keeping this file current is mandatory:** update it after meaningful milestones, decisions, tests or blockers, and before a substantive handoff or publication. See [the full update rules](../AGENTS.md).

## Purpose and acceptance target

Use an existing Windows laptop or desktop PC, compatible Android TV/Google TV and HDMI sound system to play high-quality 4K remuxes without buying another dedicated media player, such as an NVIDIA Shield.

The primary target is native TV HDR video, untouched Dolby TrueHD Atmos over HDMI, and stable physical A/V sync. On 2026-11-02 the user reported that sync looks perfect in the tested calibrated build and explicitly requested making it the main build, committing/pushing and releasing stable 1.0. This supersedes earlier beta-only positioning, branch-separation and local-only publication restrictions. It is a user observation on one setup, not an instrumented absolute-accuracy or universal-compatibility claim.

## Stable 1.0 promotion — completed, 2026-11-02

Released: **Windows/TV/phone 1.0.0** on `main`, derived from tested local commit `9d8eead` (host/TV 0.6.3-beta.1 and phone 0.1.3-beta.1). Existing main history was merged normally, without force-pushing or replacing old tags/assets. Only version metadata, visible stable labels, release tooling/tests and documentation changed for promotion; synchronization/capture algorithms and existing offsets were preserved. The user requires terminal-only operation; no computer-use or GUI automation.

Retain TV `dev.dualtheater.tv.robustsync`, phone `dev.dualtheater.calibration.preview` and Windows `%LOCALAPPDATA%\DualTheater-RobustSync` for continuity with the tested apps. Old base/preview IDs/profiles remain separate. Signing-certificate mismatches between local and CI APKs require uninstall/reinstall and re-pairing; CI debug signing keys remain private and ephemeral. Preserve private profiles and all locked releases. Never publish hardware-test paths, addresses, endpoint IDs, screenshots or raw logs.

Promotion was committed as `d75110c5e9dc2656e7b77f7ae099e43b933bfda8` and pushed to `main` with a normal merge retaining both histories. The final build/tag is **`053c86c09a6fbab577c7dd6aa1302c94d277d2b6`**; its [release CI](https://github.com/shadow-pheonix/dualtheater/actions/runs/41391703967) passed validation and publication. [v1.0.0](https://github.com/shadow-pheonix/dualtheater/releases/tag/v1.0.0) is published as GitHub's latest **stable** release (`draft=false`, `prerelease=false`). A later documentation-only main commit records verification without rebuilding or moving the release tag. Keep the unfinished main review/subtitle stash intact; subtitles remain unimplemented.

Publication follow-up: the [first run](https://github.com/shadow-pheonix/dualtheater/actions/runs/41390954057) passed the full Windows tests/build/frozen smoke and Android assembly/JVM/lint checks, then failed only at release creation. A one-element PowerShell `if` result became a scalar string and splatted `--latest` into characters. A new native-argument regression reproduced the stable failure while beta arguments passed. The fix keeps the conditional output explicitly array-valued; both regression checks passed locally before the corrected commit was pushed. No stable tag/assets were created by the failed command; old releases remain untouched. No player synchronization/capture code changes are involved.

Final verification: CI passed **101 host tests**, the pinned upstream player download, portable EXE build/frozen resource/host lifecycle/downloader smoke, both Android assemblies/JVM tests and lint. The unchanged Android suite contains **40 JVM tests** (24 TV, 16 phone), all passed locally for 1.0 as well. All six public assets were independently downloaded and matched GitHub SHA-256 digests, SHA256SUMS.txt and BUILD-INFO.json. The source ZIP's **110 files** match the tagged commit (allowing Git's Windows text line-ending conversion); source privacy and ZIP/APK integrity checks passed. Downloaded APK signatures, retained package IDs, TV code 14 / phone code 5 and version 1.0.0 passed verification. The downloaded EXE reports file/product version 1.0.0 with no prerelease bit. The public tag resolves to the exact build commit. All **five earlier releases / 23 assets** retain their IDs, targets, sizes and hashes. No release binaries were installed over the user's working apps and no new hardware playback/measurement was performed for publication. Public README/setup instructions and the context are updated; private profiles, device evidence, locked artifacts and the stash are preserved.

Pre-push milestone: all **99 host tests passed without skips** on Windows, including configured real-mpv/null-output and socket checks. Both 1.0 APKs assembled, passed signature/package/version checks and all **40 JVM tests** (24 TV, 16 phone). Lint has zero errors, 21 TV / 15 phone warnings. The Windows portable EXE built successfully; its PE file/product version is 1.0.0 and the prerelease bit is clear. No GUI automation or new hardware playback was used for promotion. All 63 relative documentation links/anchors, 18 documented PowerShell blocks, five multiline CI PowerShell blocks, source syntax/privacy and Git whitespace checks passed. CI still must verify the final committed/frozen package before publication. Five existing public releases / 23 assets were snapshotted privately for preservation verification.

## Evidence inherited from the tested candidate

- **User observations:** native TV video and normal HDMI audio with receiver-indicated Atmos were confirmed; after calibration/timing fixes the user reported sync looks perfect. Main's earlier zero-offset video looked slightly late and Robust Sync looked better. This does not establish other hardware, HDR-profile/FEL support, receiver-inspection correctness or sustained whole-film reliability.
- **Software checks at candidate `9d8eead`:** all 99 host tests passed without skips, including real mpv/null-output and socket tests; all 24 TV JVM and 16 phone JVM tests passed. Android assembly/signature/version checks passed; lint had zero errors (21 TV / 15 phone warnings). These are historical candidate results until rerun for 1.0.
- **Calibration:** six camera flashes/beeps were matched and explicit phone Apply saved a mode-specific lead. Subsequent measurements showed small residuals, but phone capture uncertainty and unvalidated absolute bias limit claims. No frames or PCM are retained. Reference remains 22-second SDR/stereo TrueHD without Atmos; it does not establish HDR/Atmos-mode latency equivalence. The saved correction is private setup data, not a default distributed offset.
- **Timing failures fixed:** a reproduced 500 ms transport timeout now uses a bounded three-second deadline with stale-pong rejection and independent control; TV phase comparison uses the latest evaluation time to avoid a receipt/render lock race. Actual earlier phase-jump cause is not conclusively proven. Timing EOF now triggers cancellable reconnection in the same authenticated control session; every new timing stream gets a fresh clock model. Load/start waits up to eight seconds before changing media. Recovery does not resume playback or apply an offset.
- **Device fault tests:** intentional timing loss while paused and playing recovered fresh timing/clock in approximately 0.94 / 0.81 seconds with control retained. Active playback paused and stayed paused until explicit coordinated resume. Full reference playback advanced through its cues with TrueHD. A later ordinary host restart was left paused with a fresh clock. No fault-injection wrapper is part of the product or release.
- **Remaining limits:** one source-audio-timeline expiry was observed before the last fix and is not root-caused. The timestamp-ordering tests establish the race fix, not the exact cause of every historical device event. Multi-hour, repeated seek/resume, bitrate peaks and broader device behavior still need testing. Phone preview geometry is tested; live orientation confirmation was not separately recorded.

## Preserved publication history

Old releases remain unchanged: main v0.4.1-beta.1 at `eebf9a256fb50d54640022ad6a190d29f50926c2`; feature/playback-reliability v0.5.0-beta.2 at `17a2057519c50da71a910dafb385d355a1df300f`; feature/robust-sync v0.6.0-beta.1 at `d06248b5d66005e2121b3adc46ebabb22287d5b5`. Documentation commits can be newer than their build commits. Previous publication checks verified CI payload hashes, APK identities/signatures and source privacy/provenance. Historical CI: [main](https://github.com/shadow-pheonix/dualtheater/actions/runs/41021485992), [preview](https://github.com/shadow-pheonix/dualtheater/actions/runs/41021504117), [Robust Sync](https://github.com/shadow-pheonix/dualtheater/actions/runs/41021507447). Feature branches/releases are retained as historical comparisons while main is promoted.

Local pre-promotion commits are `42b3b0f` (EOF grace and capture diagnostics), `54d6f5f` (transport timeout/TV timestamp ordering), `52b1611` (phone preview geometry) and `9d8eead` (timing reconnection and preparation). Private test bundles, device backups and profile data remain outside this repository. A named stash preserves main review notes and an unfinished, unused subtitle draft; do not drop it or claim subtitle support.

## Architecture and invariants

1. The Windows standard-library Python host serves the selected original MKV byte-for-byte with HTTP range support. It currently sends the complete container, including audio bytes the TV does not render; it does not demux a video-only network stream or transcode.
2. The TV app uses Media3/ExoPlayer with hardware MediaCodec video decoding and a SurfaceView. It has no audio renderer. Preserve the heap-aware buffer budget, which fixed a real allocation failure.
3. A separate Windows mpv instance reads the same local file and bitstreams compressed TrueHD through WASAPI exclusive mode to an explicit HDMI endpoint. Normal playback rejects PCM fallback. The user's known-working baseline was `--vid=no --ao=wasapi --audio-exclusive=yes --audio-spdif=truehd`; the host also adds IPC and coordination controls.
4. The audio clock is master. Baseline compares driver-adjusted audio with scheduled frame releases. Audio-clock/servo modes use source timestamps and media timelines; audio-clock mode supplies the renderer clock, while servo mode controls video speed. Video correction stays within 0.995–1.005x; audio remains 1.0x. API observations exclude unreported panel/receiver processing delay.
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

- Instrumented absolute lip-sync and repeated remote seek/play-pause/relock behavior. User-reported excellent sync on one calibrated setup is recorded above.
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
| `host/sync.py`, `host/timing.py`, `host/audio_timing.lua` | Baseline servo, affine/source timing and experimental video control |
| `host/receiver.py` | Read-only S95TR status and Windows HDMI latency declarations |
| `host/discovery.py`, `host/pairing.py` | Discovery, pairing and remembered credentials |
| `host/controller.html` | Local Windows browser controller |
| `host/player_download.py` | Explicit upstream download, integrity checks, safe staged extraction and private offline runtime |
| `host/diagnostics.py`, `docs/diagnostics.md` | Bounded session metrics, shareable report allowlist and preview instructions |
| `host/calibration.py`, `android/calibration/`, `docs/phone-calibration.md` | Phone role, owned test runs, capture-clock measurement, explicit saved-offset Apply and setup |
| `host/desktop.py`, `host/desktop_support.py`, `desktop_main.py` | Native desktop pages, private preferences, device selection and background host operations |
| `tools_src/build_windows.py`, `requirements-build.txt` | Standalone Windows packaging with bundled resources, icon, version and runtime licenses |
| `assets/`, `tools_src/generate_icons.py` | Original matching vector/Windows artwork and Android TV banner generation |
| `android/app/src/main/java/dev/dualtheater/tv/` | TV UI, native video playback, remote controls, discovery and control client |
| `tests/`, Android `app/src/test/` | Host/protocol/integration and Android JVM tests |
| `.github/workflows/beta.yml` | Windows CI tests, Android build/lint, packaging and stable/prerelease creation |

The source host uses Python 3.10+ and the standard library/Tkinter. Windows packaging uses Python 3.11 x64 and pinned build tools in `requirements-build.txt`; the published EXE requires no Python installation. Android currently pins Media3 1.9.0, AGP 8.13.2 and Gradle 8.13; use JDK 17/21, SDK Platform 36 and Build Tools 36.1.0. Recheck build files before changing dependencies.

```powershell
python -m unittest discover -s tests -v
.\android\gradlew.bat --project-dir android assembleDebug testDebugUnitTest lintDebug
.\Start.ps1 -ListDevices
```

Set `DUALTHEATER_MPV` to a local executable path to enable optional real-mpv null-output tests. Do not put that personal path in tracked files. `Start-Desktop.cmd` launches the branch GUI; `Start.cmd` launches the CLI host; [README](../README.md) has user setup instructions.

The included calibration clip is original SDR H.264 video with stereo TrueHD and **no Atmos**. It is not an HDR/Atmos validation sample. Debug APK signing can differ between CI runs and local builds; a different certificate requires uninstall/reinstall and recreating TV pairing settings.

## Next work

1. Preserve the published 1.0 tag/assets and the working private calibration. Ship future behavior changes under a new version; do not overwrite this release.
2. Validate longer sessions, high-bitrate peaks, repeated remote seeking/play-pause and disruption recovery.
3. Broaden hardware/profile coverage and investigate source-timeline expiry only with fresh evidence. Keep physical observations separate from software drift/capture estimates. Subtitles remain pending in the preserved draft stash.
