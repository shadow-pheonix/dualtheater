## Experimental beta — still in testing

DualTheater separates local playback across an Android TV/Google TV and a Windows HDMI audio path: native TV hardware video decoding, original TrueHD Atmos packets through mpv, and coordinated controls/timing over the home network.

This prerelease adds **Download mpv** on Connect: download directly from the official upstream release, verify its pinned checksum, extract the runtime/DLLs and select it automatically. Later launches reuse it offline; Browse remains available for your own build. It retains the **portable Windows x64 EXE** with Connect, Player and Settings/help pages, friendly audio-device selection, a native movie picker, timeline/seek controls and saved setup. Python/Tk are included; no installer or terminal is required. Matching original Windows/Android icons and a branded TV launcher banner are included. The existing discovery, one-time pairing, TV remote controls and audio-led synchronization remain shared with the command-line host.

**Not a stable release.** Physical lip-sync, long-session reliability, broader device coverage and newer connection/remote features still need real-device testing. API timing values and null-output tests do not prove acoustic sync or correct HDR/Atmos reception.

Download the **Windows EXE** and matching **Android debug APK**. Click **Download mpv** on Connect (first setup needs Internet), or Browse to your existing compatible `mpv.exe`, choose the HDMI soundbar/receiver and start the TV connection. Python is needed only for the optional source ZIP/command-line host. Prove standalone HDMI TrueHD passthrough before testing dual-device playback. See the repository README for setup, operation, limitations and checksums.

The EXE is an unsigned experimental build. Settings, pairing and calibration are stored privately under `%LOCALAPPDATA%\DualTheater` and survive EXE replacement. First-time migration from the older source launcher may require re-pairing; older source-folder state is left intact. mpv is not bundled in our assets; its download starts only when you click **Download mpv**. Its private cache survives EXE replacement. [Download provenance/recovery](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/player-download.md).

Debug APKs are development-signed. A differently signed existing installation may need to be uninstalled before this APK can be installed. CI-generated debug keys are not kept or published.

Use only on a trusted home network. No media films, pairing credentials, personal network details, private logs or signing keys are included.
