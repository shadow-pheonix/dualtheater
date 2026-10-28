# mpv setup and download provenance

On the desktop **Connect** page, click **Download mpv**. The app fetches the package directly from the official upstream GitHub release, verifies it, extracts mpv and its supporting DLLs, checks startup without playing audio, selects `mpv.exe` and refreshes the audio-device list. Choose your HDMI endpoint and click **Start TV connection**. No mpv website, archive utility or path entry is needed for this flow.

The first download needs Internet access and about 37 MiB of transfer; the extracted runtime uses about 101 MiB. Later launches reuse the verified local copy offline. The package stays separate from the portable EXE in `%LOCALAPPDATA%\DualTheater\players`. Moving/replacing the EXE preserves it. This is a user-initiated download, not a silent update; a future pinned version requires an app update. mpv is not included in DualTheater's EXE, source ZIP or GitHub release assets.

## Pinned upstream package

| Field | Value |
| --- | --- |
| Publisher/release | [mpv-player/mpv v0.41.0](https://github.com/mpv-player/mpv/releases/tag/v0.41.0) |
| Windows asset | [mpv-v0.41.0-x86_64-w64-mingw32.zip](https://github.com/mpv-player/mpv/releases/download/v0.41.0/mpv-v0.41.0-x86_64-w64-mingw32.zip) |
| Archive bytes | `39002683` |
| SHA-256 | `a49811c0752c108b8260636f9c6f6fcb97406641c98b30f1e7b500dfb20177de` |
| Nested runtime archive | `mpv-git-2025-12-21-41f6a64-x86_64.zip` |
| Architecture | Windows x64 baseline; not an x86-64-v3-only package |

The outer release asset contains a nested ZIP. The downloader preserves the complete inner distribution, including adjacent shared DLLs. It rejects unapproved HTTPS redirects, size/checksum mismatches, unsafe extraction paths and a non-x64 executable before starting the player. It stages installation and writes an integrity receipt containing the upstream URL, archive hash, probed version and runtime file hashes. Automatic reuse checks those hashes. This is integrity checking against a pinned package, not a publisher digital-signature claim.

See [mpv source/license](https://github.com/mpv-player/mpv/tree/v0.41.0), [upstream installation guidance](https://mpv.io/installation/) and [third-party notices](../THIRD_PARTY_NOTICES.md). Downloaded components keep their upstream license terms. The app does not modify their binaries.

## Manual setup and recovery

- **Use a working build:** choose **Browse…** and select its `mpv.exe`. Keep all of its DLLs/supporting files together. A manual choice takes priority over the managed cache when saved.
- **Download fails:** check Internet, proxy/firewall and GitHub availability, then retry. A checksum mismatch installs nothing. Your previous player remains selected on failure. You can manually download/extract a suitable package and Browse to it.
- **Cancel:** close the app. Cancellation is checked between network reads and extracted chunks; a stalled read can take up to its 20-second timeout before shutdown.
- **Damaged cache:** click **Download mpv** to verify/reinstall it. A previous damaged directory is retained with a `.previous-…` suffix instead of being deleted. Once the repaired player works, you may remove that old backup yourself while the app is closed.
- **Change setup during playback:** first click **Disconnect**, change/download the player and HDMI endpoint, then start, reconnect the TV and reload the movie.

Software tests cover the actual pinned download, offline reuse, failure/cancellation, archive validation, cache recovery and TrueHD packets with null output. **HDMI passthrough with this specific build still needs testing on your laptop/desktop and receiver.** Browse lets you revert to the build already known to work with your hardware. The download does not establish physical HDR output or A/V sync.
