<img src="assets/dualtheater.png" width="72" alt="DualTheater icon" />

# DualTheater

**Stable release: 2.0.0.** Native TV video and untouched HDMI audio, with authenticated UDP timing, shared track controls and movie browsing. The tested setup completed 15 uninterrupted minutes with zero reported errors or dropped video frames; the user confirmed continuous audio and in-sync dialogue. Whole-movie, broader hardware and instrumented accuracy testing continue.

A later long-session test encountered a timing-confidence pause. An **unreleased 2.0.1-beta.1 candidate** is being tested for brief timing-delivery gaps; the downloads below remain 2.0.0. See [current findings and validation](docs/context.md#current-release-instruction--2026-11-03). If playback stops with a timing-confidence error, let the connection stabilize and use the normal **Play** control to resume both devices together; persistent faults need diagnosis.

DualTheater plays the **video on an Android TV or Google TV** using its native hardware decoder, while a **Windows laptop or desktop PC sends the original Dolby TrueHD Atmos audio over HDMI** to a soundbar or AV receiver. The two devices are coordinated over the home network.

Version 2 adds embedded subtitles and audio choices across Windows, TV and phone, shared-folder/Android browsing, TV audio badges and guided navigation. It retains the **v1.0 video correction math**, with explicit clock-input, renderer-lifecycle and delivery fixes. Matching clients use [dedicated UDP timing](docs/datagram-timing.md), while movie bytes and playback commands use TCP. See the [complete operating guide](docs/next-version.md).

Coordinated TV remote controls, recommended phone flash/beep calibration, diagnostics, camera-preview correction and timing reconnection remain included. Original video bytes and compressed audio are preserved. Audio stays at 1.0x.

## Download

Use the **Windows, TV and recommended phone apps from v2.0.0**. Run one Windows host at a time. Existing compatible phone companions can continue working; update Windows and TV together to use UDP timing.

| Download | What to do with it |
| --- | --- |
| [Windows x64 portable EXE](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/DualTheater-Windows-v2.0.0-x64.exe) | Download and double-click. No installer, administrator privileges or Python installation needed. Click **Download mpv**, or Browse to your known-working `mpv.exe`. |
| [Android TV / Google TV APK](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/DualTheater-TV-v2.0.0-debug.apk) | Sideload onto your TV and open **DualTheater TV**. |
| [Recommended Android phone calibration APK](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/DualTheater-Calibration-v2.0.0-debug.apk) | Sideload onto a supported Android phone; [measure and apply a correction](docs/phone-calibration.md). Recommended to improve physical lip-sync through measurement and verification; manual adjustment is also available. |
| [Source ZIP / command-line host](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/DualTheater-v2.0.0.zip) | Extract into a fresh folder; requires Python and mpv. See [commands and setup](docs/command-line.md). |
| [SHA-256 checksums](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/SHA256SUMS.txt) | Compare with `Get-FileHash` to verify downloaded files. |
| [Build provenance](https://github.com/shadow-pheonix/dualtheater/releases/download/v2.0.0/BUILD-INFO.json) | Source commit, CI run and payload hashes for this release. |

[Release notes](https://github.com/shadow-pheonix/dualtheater/releases/tag/v2.0.0) · [All releases / older comparison builds](https://github.com/shadow-pheonix/dualtheater/releases) · [How to use](#how-to-use)

The EXE includes Python and its GUI runtime. **Download mpv** fetches the pinned upstream player, verifies it and selects it automatically. This first setup needs Internet access (about 37 MiB); later launches use the cached player offline. **Browse…** accepts your known-working build. mpv is not embedded or redistributed in our EXE. See [download details and recovery](docs/player-download.md).

The Windows EXE is unsigned; Android APKs are development-signed (hence `-debug.apk`). Stable describes the release channel, not a signing certificate or universal compatibility guarantee. If Android reports a signing-certificate mismatch, preserve your settings privately, uninstall that app, install the new APK and pair again. CI keys are not retained between runs.

## Updating from earlier builds

Version 2 keeps the tested Robust Sync identities: Windows state remains under `%LOCALAPPDATA%\DualTheater-RobustSync`, TV package `dev.dualtheater.tv.robustsync`, phone package `dev.dualtheater.calibration.preview`. Matching-signature updates retain pairing and calibration. Older base/preview TV apps and profiles remain separate; open **DualTheater TV** for 2.0. All old releases and locked artifacts are preserved.

When using the source CLI, keep the same private `--data-dir` to retain its offsets and credentials. A hardware-test profile is not automatically imported into the desktop profile. Never distribute your settings or logs with a build.

## Why this project exists

DualTheater aims to make high-quality 4K remux playback with lossless audio possible using a Windows laptop or desktop PC you already own, together with your compatible TV and HDMI sound system. By putting that existing hardware to work, it can help avoid the cost of a separate dedicated media player, such as an NVIDIA Shield. Check compatibility and calibration on each setup.

A TV's internal player may handle HDR video well while being unable to pass through a local file's lossless TrueHD Atmos track. A Windows laptop or desktop PC may bitstream that audio correctly while local Dolby Vision video output is difficult or unsupported for the source. DualTheater separates those jobs so an existing TV, Windows laptop or desktop PC, and compatible HDMI audio device can each do the part they support.

The goal is **native TV HDR video + untouched TrueHD Atmos packets + stable A/V synchronization**, without transcoding or requiring another playback box. It does not add codecs or HDR profiles that the TV lacks, and it cannot make an incompatible HDMI receiver accept TrueHD.

```mermaid
flowchart LR
    File[Original MKV on Windows] -->|Original bytes over HTTP| TV[Android TV / Google TV\nNative hardware video decoder]
    File --> MPV[mpv\nTrueHD passthrough]
    MPV -->|HDMI / WASAPI exclusive| AVR[Soundbar or AV receiver]
    Host[Windows coordinator] <-->|Control, clocks and frame timing| TV
    Host -->|Local IPC| MPV
```

## Compatibility

This project is **brand-independent** and designed for Android TV and Google TV devices running Android 8 or later. It is not proven to work on every device.

- The TV must support the particular codec, resolution, HDR format and profile through Android's hardware decoding APIs.
- HDR10, HDR10+ and Dolby Vision depend on the media, container metadata, TV hardware and firmware. Dolby Vision Profile 7/FEL reconstruction is not promised. Profile 5 must not be treated as having an HDR10-compatible base layer.
- The Windows laptop or desktop PC needs an **HDMI output**, or a **USB-C (Type-C) port that supports display/audio output through a compatible USB-C-to-HDMI adapter** (for example, [DisplayPort Alt Mode](https://www.displayport.org/displayport-over-usb-c/)). A USB-C connector alone does not guarantee this capability; a charging/data-only port is insufficient. The adapter and driver must also support the required TrueHD passthrough; adapter-based operation has not yet been verified for this project.
- The Windows laptop or desktop PC must already be able to bitstream the source's TrueHD track to the chosen HDMI endpoint using mpv/WASAPI exclusive mode.
- The soundbar or receiver needs a compatible HDMI input. The design does not rely on the TV forwarding TrueHD audio.
- The network must have headroom above the remux's peak bitrate. A nominal 100 Mbps TV Ethernet port may be a bottleneck.

There is no platform-specific TV brand integration, video re-encode, HDR conversion, audio resampling or adaptive transcoding fallback.

## Current features

- Portable native Windows app with saved audio setup, friendly device names, movie picker and transport controls.
- Original-file HTTP range streaming; the TV renders native video and selected embedded subtitles, with no audio renderer.
- Hardware-only Media3 decoding to a SurfaceView, with aspect ratio preservation and a heap-aware sample-buffer budget.
- TrueHD passthrough using the user's existing mpv installation and an explicit WASAPI HDMI endpoint. Normal mode rejects PCM fallback.
- Laptop discovery, one-time six-digit pairing and remembered reconnection.
- TV remote controls: left/right seek, hold to preview larger jumps, middle/OK play-pause, and a bottom elapsed/total timeline with buffered progress.
- Coordinated pause, seek and scheduled resume; saved latency calibration; video-side drift correction and error/buffering watchdogs.
- Authenticated latest-value UDP clock/anchor timing, independent audio sampling and bounded TV disk read-ahead.
- Audio/subtitle selection on Windows, TV and phone; automatic audio selection prefers English TrueHD Atmos when positively identified.
- TV-driven browsing of granted Windows folders and available phone/TV storage, plus metadata-qualified audio badges.

## How to use

### 1. Download, connect HDMI and install the TV app

Use a Windows 10/11 **x64 laptop or desktop PC**. Connect its HDMI output, or a compatible HDMI adapter on a display-capable USB-C port, to your soundbar/receiver's **HDMI IN**. Select that HDMI input. Put the computer and TV on the same trusted home network and keep the computer awake during playback.

Download the Windows EXE and matching APK from [Download](#download). Transfer the APK to the TV and open it using a file manager/package installer. Allow that installer to install apps when the TV asks. Then open **DualTheater TV**. Device menus vary. For optional ADB commands, see the [advanced installation guide](docs/command-line.md#2-install-the-tv-app).

No Android Studio, Java, Gradle, FFmpeg or Python installation is needed for normal use of the EXE and APK. If you already have a source-host terminal open, stop it before opening the EXE.

### 2. Connect in the Windows app

1. Double-click **DualTheater-Windows-v2.0.0-x64.exe**. The application stays in one window with **Connect**, **Library**, **Player**, **Diagnostics** and **Settings & help** pages.
2. On **Connect**, click **Download mpv** and wait for verification, extraction and automatic player selection. The app refreshes the audio list when ready. If you prefer your existing build, click **Browse…** and select its `mpv.exe`; keep its DLLs beside it. A saved, downloaded, adjacent or PATH player can already fill in the path. Click **Refresh** if necessary.
3. Under **HDMI audio**, select the soundbar/receiver's friendly Windows name. Speakers and other WASAPI outputs can also appear; selecting one does not guarantee TrueHD capability. There is no long device ID to copy.
4. Click **Start TV connection**. The app displays the computer name and a six-digit code. Allow the app on your private network if Windows asks.
5. On the TV, select that computer and enter the code once. Remembered TVs can reconnect automatically. The Windows app switches to **Player** when the TV connects.

The mpv path and exact audio endpoint are saved privately. On later launches, the app refreshes available devices and starts the connection if the saved setup is still available. If your HDMI output disappears, reconnect it and refresh; the app does not silently substitute another device.

**Go to Player →** opens playback controls. You can also open the **3 Player** tab; connecting the TV switches there automatically.

### 3. Choose a movie and play

On **Player**, click **Choose movie…**, select the original local MKV and click **Load movie**. Wait for both players to prepare, then click **Play**. Automatic audio selection prefers English TrueHD Atmos, other TrueHD Atmos, then English/other TrueHD before supported compressed fallbacks; Atmos requires positive metadata. The original file stays on Windows and is streamed directly to the TV; there is no separate upload or conversion step.

To select movies from the TV, first use Windows **Library → Share Windows folder…**, then TV **Browse movies → Windows folders**. Subfolders are accessible within the grant. Phone/TV storage must be shared through that device's folder picker and kept available. See [browsing and Android storage](docs/next-version.md#sharing-android-storage).

Keep the Windows app open throughout playback. Check the TV's active HDR indication and the soundbar/receiver's Atmos indication independently. The app's TrueHD message is software evidence, not proof of correct physical HDR/Atmos output.

## Operating the player

These instructions describe **v2.0.0**. Keep **Audio clock (recommended)** selected on Connect for the tested synchronization path. Disconnect before changing modes. Each mode has a separate saved offset. **Diagnostics** shows clock/buffer information and offers **Export sanitized report…**. See [timing and recovery](docs/robust-sync.md), [diagnostics](docs/diagnostics.md) and [recommended phone calibration](docs/phone-calibration.md).

| Task | In the Windows app |
| --- | --- |
| Play or pause | On **Player**, press **Play** or **Pause**. The TV remote's middle/OK button also controls both players. |
| Seek | Drag and release the timeline, use **−10 seconds** / **+10 seconds**, or enter seconds next to **Seek to (seconds)** and press **Seek**. `600` means 10:00. Seeking while paused stays paused. |
| Change audio language/track | Choose under **Audio track**, then press **Switch track**. Supported compressed output still depends on mpv, the HDMI driver and receiver; PCM fallback is rejected. |
| Select subtitles | Choose under **Subtitles**, then **Apply subtitles**. Select **Off** to disable them. Embedded formats depend on Media3; external sidecar picking is not included. |
| Browse shared movies | Use **Library** on Windows, **Browse movies** on TV or **Library** on the phone. Share/grant the source folder first. |
| Play another movie | Choose it with **Choose movie…**, click **Load movie**, wait, then **Play**. |
| Adjust physical lip-sync | In **Settings & help**, change **Video lead (ms)** and press **Save and resynchronize**. Increase it if sound arrives early; decrease it if sound arrives late. |
| Recover a timing disturbance | On **Player**, click **Resynchronize**. It preserves the paused/playing state while coordinating both players again. |
| Recover a lost TV control connection | Reconnect on the TV, then **Load movie** again. Playback controls stay disabled until reloading succeeds. Resume after preparation. |
| Change mpv or HDMI output | On **Connect**, click **Disconnect** first. Use **Download mpv** or **Browse…**, choose the HDMI output, then **Start TV connection**. Reconnect the TV and reload the movie. |
| Stop playback and exit | Close the Windows app. It stops its host/audio process and closes the TV connection. Closing the optional browser controller does not exit the app. |

If only the timing connection drops, playback pauses and timing reconnects automatically. Once the clock is fresh, explicitly press **Play** or retry calibration; reconnection alone does not resume playback. If the full TV control connection drops, reconnect and reload the movie.

All transport controls use the existing shared Windows/TV synchronization barrier. Audio speed stays at 1.0x; small drift corrections affect video only. Receiver relock can briefly interrupt sound after a seek or pause/resume.

### Settings, calibration and updates

Desktop settings, remembered TV credentials, calibration and logs are stored under **`%LOCALAPPDATA%\DualTheater-RobustSync`**, not inside the EXE or its temporary extraction folder. Use **Settings & help → Open local settings folder** to find them. Preserve these files privately when updating; do not publish them. Moving/replacing the EXE does not reset them. Downloaded mpv and its supporting DLLs are stored in the `players` subfolder and reused offline. **Settings & help → mpv download / source** opens the exact upstream release; use **Browse…** if you want another build. There is no silent player update. The current source launcher defaults to the same profile, while a custom `--data-dir` remains separate. Preserve any older profiles privately; they are not imported automatically.

The optional source ZIP includes `calibration-SDR-TrueHD-no-Atmos.mkv`, an original flash/beep clip. Extract the ZIP and choose that file in **Player** for a basic timing check. It is **SDR with stereo TrueHD, not HDR/Atmos**. Verify the offset again with your movie and processing modes. For automatic measurement, install the recommended [phone calibration client](docs/phone-calibration.md), connect it to Windows, **increase the receiver volume so all six beeps are clearly audible at the phone**, and press **Start calibration / verify again**. Review the result before **Apply suggested Video lead**. This replaces the movie with the reference; reload your movie afterward. A dedicated TV calibration screen is not included.

The APK is development-signed. If Android reports a signing-certificate mismatch, uninstall the previous TV app before installing the new APK and pair again. CI debug signing keys are not retained or published. Use a matching host/APK release; do not run multiple hosts against the default ports.

### Troubleshooting and optional commands

- **mpv download fails:** check Internet/proxy/firewall access to GitHub, then retry **Download mpv**. A failed/cancelled download does not replace your previous player. Close the app to cancel (an in-progress network read can take up to 20 seconds). For manual downloads, extract the entire upstream ZIP, including the nested ZIP, keep DLLs with `mpv.exe` and use **Browse…**. See [recovery details](docs/player-download.md).
- **No HDMI sound or noise:** confirm the selected output, receiver input and cable. Close any competing exclusive-audio player. Test your mpv/HDMI setup independently; the TV companion cannot fix a standalone passthrough failure. See [command-line audio test](docs/command-line.md#3-select-hdmi-audio-and-start-the-windows-host).
- **Repeated brief audio gaps during otherwise continuous playback:** check Diagnostics for a recovery or timing error. If neither occurs, compare with your previously working mpv build: **Connect → Disconnect → Browse…**, select its `mpv.exe`, keep its supporting DLLs, then reconnect and reload. The selected player is saved privately. A newer user-supplied build removed recurring gaps in one development test; the exact codec/driver cause remains unconfirmed. Do not treat a healthy software clock as proof of uninterrupted HDMI output.
- **TV cannot find the computer:** keep both devices on the same trusted LAN. Check private-network firewall permission, guest-client isolation and VPN routing. Discovery uses UDP 8767, control TCP 8766, timing UDP 8766 and media TCP 8765. See [connection setup](docs/easy-connection.md).
- **Connection cannot start:** another EXE or source-host instance may already be using the ports. Close that instance and try again. A second desktop instance asks you to use the existing window.
- **Repeated buffering or resynchronization:** the network must sustain remux peak bitrate; some TV Ethernet ports are limited to 100 Mbps. Check local session details and the [hardware test guide](docs/hardware-test.md).
- **Advanced controls:** **Settings & help → Advanced browser controller** opens the existing Windows-local controller on **http://localhost:8764**. Normal operation does not require a browser.

To launch the portable EXE from PowerShell rather than double-clicking:

```powershell
.\DualTheater-Windows-v2.0.0-x64.exe
```

For Python launch commands, downloading/extracting the source ZIP, optional ADB installation and standalone mpv checks, use the [advanced command-line guide](docs/command-line.md). These steps are optional for EXE users.

## TV remote

| Button | Action |
| --- | --- |
| Middle / OK | Toggle coordinated play/pause |
| Left / right | Preview backward/forward by 10 seconds |
| Hold a direction | Accumulate a larger seek; commit after release |
| Up / Menu | Open audio, subtitle and browsing options |
| Down | Show the timeline |
| Back during preview | Cancel the preview |
| Dedicated transport buttons | Equivalent play, pause, rewind and fast-forward controls |

The timeline auto-hides after five seconds while playing. It stays visible while paused, buffering or synchronizing. Seeking while paused remains paused. Pressing OK during a preview commits that position and toggles the final play state. Input is held while a synchronization operation is pending.

All committed transport operations go through the Windows coordinator. The TV does not independently seek or resume its video clock in response to remote buttons.

## Synchronization and validation limits

The audio clock is the master. In the default audio-clock mode, source-timestamped Windows audio anchors drive the TV renderer's media clock using synchronized monotonic clocks. Video-servo mode applies bounded video-speed corrections; original timing retains the older scheduled-frame comparison. TrueHD audio stays at **1.0x**. Sustained drift or a buffer underrun triggers a shared pause/prepare/restart barrier.

These are estimated API timings, not measurements of sound pressure or photons. Panel processing, receiver buffering, refresh cadence, Windows scheduling and firmware behavior can introduce fixed latency or variable error. A small drift value does not prove acoustic lip-sync. Calibration and longer real-device tests are required, particularly after seeking and pause/resume.

Simultaneous native TV video and receiver-indicated Atmos have been observed. The user reported excellent physical sync on the calibrated build promoted to 1.0. This is a single-setup observation; broader TV coverage, long-term reliability and sync after repeated seek/resume cycles still need testing. See [testing status](docs/testing.md) and the [hardware test guide](docs/hardware-test.md).

The current target is an ordinary single-timeline MKV. Embedded subtitle rendering remains subject to Media3 format/styling limits. Playlists, video-track switching, app background playback, automatic playback resume after reconnect, unusual timestamp origins and exotic containers are not validated. After reconnecting, reload the media on Windows. TrueHD may briefly relock after pause or seek.

## Build and test

For ongoing development or a new Codex session, start with [project context](docs/context.md) and follow [AGENTS.md](AGENTS.md). Updating the shared context after meaningful changes and before handoffs is mandatory. Whenever a project change makes installation or operating instructions outdated, update the affected README instructions in that same change before publishing.

`main` builds **2.0.0** for Windows, TV and the recommended phone companion. Use the [complete operating instructions](docs/next-version.md) for Library, Player and phone pages. Automatic audio selection prefers English TrueHD Atmos when identified; manual selection overrides it. [Temporary disk read-ahead](docs/read-ahead.md) retains the RAM limit and direct-streaming fallback. App/package identities and the private profile are retained for upgrade continuity.

Update Windows and TV together. Matching clients negotiate [dedicated UDP timing](docs/datagram-timing.md) on **UDP 8766** (or your custom control port), alongside TCP control/media and UDP discovery. Allow it on the trusted private LAN. Older peers retain TCP timing. The v1.0 video correction math, original compressed audio and saved lead are preserved. Actual starvation or unavailable timing can still pause playback. Refresh and reselect the HDMI output if Windows changes its endpoint identity.

The accepted 15-minute hardware run used a newer external mpv build selected through Browse. The pinned downloader remains a convenience option; it produced repeated sound gaps on that setup, while the user's existing runtime restored continuous audio. Use a known-working runtime for HDMI acceptance and retain its supporting files. The exact codec/driver cause is not established.

To build the Windows EXE from source on Windows with Python 3.11 x64:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools_src/build_windows.py
```

The result is `dist/DualTheater.exe`. Packaging includes Python/Tk, app resources, license notices and the original icon; it excludes user state and mpv. `tools_src/generate_icons.py` regenerates original artwork using the build-only Pillow dependency. Release CI verifies the real upstream download, runs host/TrueHD tests with null audio output, and checks the EXE's frozen resources, library, diagnostics, local host lifecycle and external player startup without GUI or HDMI. Physical output remains a hardware test.

The Python host uses the standard library. The Android project pins Media3 1.9.0, Android Gradle Plugin 8.13.2 and Gradle 8.13. Install JDK 17 or 21, Android SDK Platform 36 and Build Tools 36.1.0, then run:

```powershell
.\Build-TV.ps1
python -m unittest discover -s tests -v
.\android\gradlew.bat --project-dir android testDebugUnitTest lintDebug
```

Set `DUALTHEATER_MPV` to the full mpv executable path to include the optional Windows IPC/TrueHD tests. Those tests use **null output**, so they do not open HDMI. Tests without that variable skip those checks.

The generated `calibration-SDR-TrueHD-no-Atmos.mkv` contains an original flash/beep pattern with **SDR H.264 video and stereo TrueHD, without Atmos**. It is for basic timing checks, not HDR/Atmos validation. Its generator is included; no film footage is distributed.

## Privacy and network scope

Pairing and playback use cleartext on a trusted home LAN. Do not expose these ports to the Internet. Keep `pairings.json`, local settings, calibration, logs, private device identifiers and signing keys out of Git. Preserve `pairings.json` locally when updating to retain remembered TVs. Discovery does not advertise pairing codes or credentials.

Public reports should contain redacted, minimal evidence rather than raw logs or media files. See [SECURITY.md](SECURITY.md), [architecture](docs/architecture.md), [connection setup](docs/easy-connection.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
