# Changelog

## 0.4.1-beta.1 — automatic mpv setup

- Download mpv directly from its official Windows release inside the desktop app; checksum verification, nested ZIP extraction, DLL retention and automatic selection.
- Private offline cache with file-integrity checks, staged installation, cancellation and manual Browse fallback.
- Upstream-download and real-mpv null-output checks in release CI, plus external-player startup from the frozen EXE.

mpv is not redistributed in the EXE. HDMI passthrough with this downloaded build and physical A/V sync still need hardware testing.

## 0.4.0-beta.1 — portable Windows desktop beta

- Single-file Windows x64 EXE with included Python/Tk runtime; no installer or console required.
- Connect, Player and Settings/help pages, friendly audio-device selection, native movie picker, timeline, exact/relative seeking and track controls.
- Saved mpv/HDMI setup and private application-data storage; remembered setup starts the connection automatically when the saved endpoint is available.
- Shared host lifecycle for CLI and GUI, rollback on startup failure and coordinated shutdown/reload handling.
- Matching original dual-screen app icons for Windows/Android and a branded Android TV launcher banner.
- Windows packaging and packaged GUI/resource/start-stop smoke tests in release CI.

mpv remains a separate executable selected once. Physical A/V sync and HDR/Atmos behavior through the desktop build still need device testing.

## 0.3.0-beta.1 — experimental public beta

- Public Android TV/Google TV positioning with device-dependent HDR compatibility.
- Native TV hardware video plus Windows HDMI TrueHD passthrough.
- Coordinated transport, calibration and video-side drift correction.
- TV remote seeking/play-pause and a bottom timeline.
- Laptop discovery, one-time code entry and remembered pairing.
- Portable launch/build scripts and sanitized public documentation.

Still in testing: physical A/V sync, broader device support and long-session reliability. This prerelease is not a stable compatibility claim.
