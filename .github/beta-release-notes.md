## Experimental beta — still in testing

DualTheater separates local playback across an Android TV/Google TV and a Windows HDMI audio path: native TV hardware video decoding, original TrueHD Atmos packets through mpv, and coordinated controls/timing over the home network.

This prerelease includes discovery, one-time pairing, TV remote seeking/play-pause, a timeline, calibration and video-side drift correction. It is designed to be brand-independent; actual codecs, HDR profiles, HDMI formats and firmware behavior remain device-dependent.

**Not a stable release.** Physical lip-sync, long-session reliability, broader device coverage and newer connection/remote features still need real-device testing. API timing values and null-output tests do not prove acoustic sync or correct HDR/Atmos reception.

Download the matching source/Windows host ZIP and Android debug APK. Install Python and a compatible mpv build separately, and prove standalone HDMI TrueHD passthrough before testing dual-device playback. See the repository README for setup, limitations and test steps.

Debug APKs are development-signed. A differently signed existing installation may need to be uninstalled before this APK can be installed. CI-generated debug keys are not kept or published.

Use only on a trusted home network. No media films, pairing credentials, personal network details, private logs or signing keys are included.
