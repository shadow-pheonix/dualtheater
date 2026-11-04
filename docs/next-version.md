# Version 2.0 operating guide

Main now adds **TV 2.0.4-beta.1** automatic [P7 FEL compatibility](dolby-vision-compatibility.md); Windows remains 2.0.1-beta.1 and phone 2.0.0. The default enabled TV setting converts only positively identified FEL. P7 MEL stays native. Use **Video compatibility** on TV; changes take effect at the next Windows **Load movie**. Existing Windows/phone clients remain compatible. No new stable release is implied.

`main` builds **2.0.0**, promoted from the finalized local beta.4 candidate at the user's request. Existing package identities, private profiles and locked releases are preserved. Update Windows and TV together. Existing phone clients remain protocol-compatible.

At the user's request, only the **post-1.0 drift changes** have been reverted. Shared transport and the TV renderer-clock algorithm use the v1.0 baseline, with explicit availability/lifecycle/start-verification exceptions described in [timing baseline](drift-control.md). V1.0 already includes synchronized clocks and bounded video-side correction; those original mechanisms remain. The saved calibration and untouched 1x audio passthrough are retained. The independent 64-bit transport-position conversion fix is retained as well.

Subtitles, audio selection, English TrueHD Atmos preference, folder/Android browsing, TV audio badges, improved navigation and temporary disk read-ahead remain. Independent client-state workers keep these newer clients serviced. Local audio sampling is isolated from dedicated timing writes. Matching clients negotiate [UDP timing on the control port number](datagram-timing.md); allow that UDP port on the private LAN. Older clients retain TCP timing. The experimental control-channel fallback and retained-buffer recovery protocol remain removed.

The accepted setup completed 15 uninterrupted minutes with user-reported continuous audio and in-sync dialogue. Whole-movie and broader hardware testing remain pending. Genuine exhausted buffers and v1.0 timing safety checks can still pause playback. Software and device observations are recorded in [context](context.md). See [timing baseline](drift-control.md) and [read-ahead limits](read-ahead.md).

## What changed

| Area | Version 2 behavior |
| --- | --- |
| Synchronization baseline | Restores the v1.0 source/remote clocks and shared start/pause/seek/recovery behavior. Post-1.0 continuous-drift changes are removed. Saved calibration remains. |
| Subtitles | Embedded subtitle selection and Off on Windows, TV and phone. The TV includes Media3's text renderer and SubtitleView alongside the existing hardware video renderer, with no audio renderer. |
| Audio | Shared track choices with language/format/layout labels. Compressed TrueHD, AC3, EAC3, DTS and DTS-HD paths are checked; PCM fallback is rejected. Receiver/driver support is still required. |
| Library | Browse user-shared Windows folders, including subfolders, and available phone/TV document-tree storage. Select a movie on TV to prepare and play through Windows. |
| Audio popup | A short top-right TV badge on first playback and audio changes shows available language, codec and channel/layout information. Atmos/DTS:X appear only when positively stated in track metadata, qualified as such. |
| Calibration | Recommended phone measurement, with a pre-start reminder to raise receiver volume so the microphone can detect the beeps. |
| Navigation | Consistent dark/teal colors, guided setup, Library and Player pages, focusable TV menus and scrollable Windows pages. The phone gains Connect, Library, Player, Calibrate and Help. |

## Windows setup and library

1. Close any other DualTheater host. Open the matching portable EXE or source `Start-Desktop.cmd`.
2. On **Connect**, use your tested mpv or **Download mpv**, select the HDMI receiver endpoint and retain **Audio clock (recommended)**. Click **Start TV connection**, then pair the TV.
3. Open **Library → Share Windows folder…** and choose a movie folder. Only that folder and its descendants become remotely browseable; no whole-drive access is assumed. **Stop sharing selected folder** removes that grant without deleting files. Temporarily missing removable folders remain remembered.
4. Choose a source in Library and open folders. Double-click a movie or use **Open folder / play movie** to prepare both players and start. The existing local **Choose movie… / Load movie** flow remains on **Player**.
5. On **Player**, select **Audio track → Switch track** or **Subtitles → Apply subtitles**. **Off** disables subtitles. Audio changes use the shared pause/prepare/start barrier and can briefly relock the receiver; subtitle selection does not independently seek or resume the TV.

Read-only browsing runs separately from remote transport. Windows Pause has a priority background path so it is not queued behind a slow library read. Changes to playback remain coordinated and stale menus for a replacement movie are rejected.

## TV operation

Select the computer and pair as before. **Browse movies** offers **Windows folders**, **Phone storage** and **TV storage** when available. Open subfolders, use the parent/page controls, and choose a movie to start it. A folder must first be shared from Windows or granted on the Android source.

Connecting refreshes the library silently; it does not open a browser over playback. A movie loaded from Windows or the phone closes an existing TV library dialog. Press **Browse movies** or open playback options when you want to browse.

During playback, **Up** or **Menu** opens options for audio, subtitles and browsing. **Back** closes the menu before leaving playback. With menus closed, **left/right** preview seeking, **middle/OK** plays/pauses and **Down** displays the bottom timeline. All transport actions go through Windows. Menus close when their playback generation becomes stale.

The TV popup describes source metadata and software-selected audio, not a receiver handshake. For example, a title saying Atmos can be displayed as **Atmos (track title)**; TrueHD alone does not establish Atmos. Original readable text badges are used instead of proprietary logos.

## Phone operation and recommended calibration

The app is now labeled **DualTheater Companion**, retaining the existing calibration package ID for updates. In **Connect**, find the computer and pair once. The address/port fields are under **Advanced connection** for discovery troubleshooting.

**Player** offers play/pause, seeking and the same audio/subtitle choices. These controls do not use the camera or microphone. Phone absence does not disable Windows or TV controls. Finish or cancel an active calibration before using phone movie controls.

In **Calibrate**, increase the soundbar/receiver volume until the beeps are clearly audible at the phone, keep it steady at the listening seat, center the flash area and quiet the room. A reminder appears before capture starts. The test replaces the movie temporarily; measure, review the estimate, explicitly Apply, verify again and reload the movie afterward. The reference remains SDR/stereo TrueHD without Atmos; verify your movie modes separately. See [measurement limits](phone-calibration.md#timing-and-accuracy).

## Sharing Android storage

On the phone choose **Library → Choose phone folder to share**. On TV choose **Choose TV folder**. Use the system folder picker and grant read access. The phone reconnects with remembered pairing after the picker when appropriate; reconnect manually if needed. Some TVs do not supply a document-tree picker; use Windows or a supported phone source in that case.

Only the chosen tree is shared. The sharing app must remain open, connected and awake; backgrounding/disconnection closes its server. Playback of a file from that device cannot continue when the source disappears. Phone **Stop sharing phone folder** revokes its source without disconnecting its player controls. Folder permissions and source sessions are checked again on use.

Movie files need a known positive size and random-access reads. Local device/USB document providers are the intended sources; cloud/virtual providers that cannot seek are unavailable. Original byte ranges pass through Windows to the TV and mpv, with no transcode or full-file staging. High-bitrate playback can require substantial network headroom: Android source traffic goes to Windows, then video bytes return to TV, while Windows also reads the audio stream. A nominal link speed is not a throughput guarantee.

Provider cancellation is best effort. A provider that ignores cancellation/descriptor close may hold a bounded worker until its I/O returns. File size/mtime checks detect many changes but cannot prove immutable content if a provider reports unchanged or no modification time. Do not replace a shared file during playback.

## Subtitle and audio limits

The TV uses the pinned Media3 parser/renderer support advertised for each track. This includes embedded SubRip, WebVTT, SSA/ASS and PGS when exposed as supported tracks. Advanced ASS drawings, animation and styling are best effort. External sidecar-file picking is not implemented in this build. Subtitle selection follows video media time and persists through ordinary seeking; replacement media starts with subtitles Off. Actual rendered formats and remote interaction still need device acceptance.

Source DTS-HD profile metadata requires an HD bitstream output; a known HD-to-core downgrade is rejected. Generic DTS can use a DTS or DTS-HD carrier. Hardware verification so far remains the earlier TrueHD setup; original generated AC3/EAC3/DTS fixtures were checked with **null output only**, not HDMI. AAC/PCM decoding is not a silent fallback. Read format indications on the receiver independently.

## Build and verify without GUI automation

Use the existing [Windows and Android prerequisites](../README.md#build-and-test). Both Android clients depend on the new `:shared` library, and the TV additionally uses `media3-ui:1.9.0`.

```powershell
python -m unittest discover -s tests -v
.\android\gradlew.bat --project-dir android assembleDebug testDebugUnitTest lintDebug
python -m pip install -r requirements-build.txt
python tools_src/build_windows.py --dist dist/windows --work build/windows
.\dist\windows\DualTheater.exe --verify-core .\core-check.json
```

`--verify-core` checks frozen resources, private temporary local host services, library grants, diagnostics and an external player when configured, without creating a GUI or opening HDMI. Set `DUALTHEATER_MPV` to a suitable executable to include real-mpv null-output tests. The separate existing `--smoke-test` still creates an invisible Tk window for CI; it is not needed for terminal-only core verification.

APK outputs remain `android/app/build/outputs/apk/debug/app-debug.apk` and `android/calibration/build/outputs/apk/debug/calibration-debug.apk`. The Windows EXE is unsigned and APKs are development-signed. A signing-certificate mismatch requires reinstall/re-pairing; preserve private profiles. No source/GUI test establishes whole-film physical lip-sync, broad HDR-profile support or reliable Android-provider/network performance. Validate those on each setup; the release channel does not establish universal compatibility.

Implementation details: [client protocol](next-client-protocol.md), [v1.0 timing baseline](drift-control.md), [Android track selection](https://developer.android.com/media/media3/exoplayer/track-selection), [Media3 subtitle parser formats](https://developer.android.com/reference/androidx/media3/extractor/text/DefaultSubtitleParserFactory), [document-tree access](https://developer.android.com/training/data-storage/shared/documents-files).
