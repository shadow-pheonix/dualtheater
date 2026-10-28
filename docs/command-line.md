# Advanced source/command-line guide

The downloads and published-build instructions below describe `0.4.1-beta.1`. Current feature-branch source `0.5.0-beta.2` additionally supports the separate [phone calibration client](phone-calibration.md), using the same host launch commands. Use a fresh source folder or `--data-dir` for its private state; keep the public/base build intact.

The portable Windows EXE is the recommended interface; see the [main README](../README.md#how-to-use). This optional guide is for running the Python source host. The source ZIP still requires Python and mpv. Do not run it alongside the desktop EXE because both use the same default service ports. ADB is only an optional TV installation method.

## How to use

### 1. Prepare the Windows laptop or desktop PC

Install [Python for Windows](https://www.python.org/downloads/windows/) 3.10 or later and a suitable [Windows mpv build](https://mpv.io/installation/). The host uses only Python's standard library; there is no `pip install` step. The beta was tested with Python 3.11. Extract the mpv distribution and keep its supporting files together. The examples use `C:\Tools\mpv\mpv.exe`; replace that with your own path.

Connect the computer's HDMI output, or a compatible HDMI adapter on a display-capable USB-C port, to the soundbar/receiver's **HDMI IN** and select that input. The TV will run its own DualTheater app for video. Put the TV and computer on the same trusted home network. Keep the computer awake during playback.

Download the files using the links above, or run this in PowerShell:

```powershell
$downloadDir = Join-Path $env:USERPROFILE 'Downloads\DualTheater'
New-Item -ItemType Directory -Path $downloadDir -Force | Out-Null
Set-Location -LiteralPath $downloadDir
$releaseUrl = 'https://github.com/shadow-pheonix/dualtheater/releases/download/v0.4.1-beta.1'
$files = @('DualTheater-v0.4.1-beta.1.zip', 'DualTheater-TV-v0.4.1-beta.1-debug.apk', 'SHA256SUMS.txt')
foreach ($file in $files) {
    Invoke-WebRequest -Uri "$releaseUrl/$file" -OutFile $file
}
Get-FileHash .\DualTheater-v0.4.1-beta.1.zip, .\DualTheater-TV-v0.4.1-beta.1-debug.apk -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Compare each file's hash with its matching line in `SHA256SUMS.txt`. Then extract into a fresh folder and enter the directory containing `Start.cmd`:

```powershell
Expand-Archive -LiteralPath .\DualTheater-v0.4.1-beta.1.zip -DestinationPath .\extracted
Set-Location .\extracted\dualtheater
```

If you downloaded/extracted manually, open PowerShell in the extracted `dualtheater` folder instead. All host commands below run from that folder. Check that Python is available with `python --version` or `py -3 --version`.

### 2. Install the TV app

Transfer the APK to the TV and open it with a file manager/package installer, allowing that installer to install apps when the TV asks. Open **DualTheater TV Beta** after installation. TV menu names and available transfer methods vary by device.

Alternatively, use [Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools) and [ADB](https://developer.android.com/tools/adb) from Windows. The commands below assume `adb` is on PATH. If your TV offers wireless debugging with pairing, enable it in Developer options and use its **pairing address** first:

```powershell
$pairingAddress = Read-Host 'Pairing address shown by the TV (IP:port)'
adb pair $pairingAddress
```

Enter the pairing code when ADB asks. Then use the TV's **debugging connection address**, which may have a different port. If your TV uses an already-authorized network ADB connection, start here instead:

```powershell
$tvAddress = Read-Host 'TV debugging connection address (IP:port)'
adb connect $tvAddress
adb devices
$apkPath = Read-Host 'Full path to the downloaded APK, without surrounding quotes'
adb -s $tvAddress install -r $apkPath
```

Accept the debugging prompt on the TV if one appears, and rerun the connection/install command after authorization. Wireless ADB availability depends on the TV and Android version; use a supported sideloading method if it is unavailable. **ADB is only needed for installation/debugging, not normal playback or app pairing.**

Debug APKs are development-signed. If installation reports a different signing certificate, uninstall the previous TV app before installing this APK; that removes its remembered pairing settings. CI debug signing keys are not retained or published.

### 3. Select HDMI audio and start the Windows host

The simplest launch is to double-click `Start.cmd`, or run:

```powershell
.\Start.cmd
```

If mpv is not on PATH or in `tools\mpv.exe`, the launcher asks for its executable path. It lists audio devices and asks for the exact `wasapi/...` name of your HDMI soundbar/receiver. Copy the device name without surrounding quotes; do not select laptop speakers or a Bluetooth endpoint.

To list devices separately and supply the choice explicitly:

```powershell
.\Start.cmd -MpvPath "C:\Tools\mpv\mpv.exe" -ListDevices
.\Start.cmd -MpvPath "C:\Tools\mpv\mpv.exe" -Device "wasapi/REPLACE_WITH_EXACT_HDMI_DEVICE_ID"
```

Replace the example path and device ID with your own values. If Python cannot be found, add `-PythonPath "C:\path\to\python.exe"` to the launch command. `Start.cmd` runs the bundled PowerShell launcher without requiring a permanent execution-policy change.

For users who prefer launching Python directly, these are equivalent device-listing and host-start commands; run only one host instance:

```powershell
python -m host.server --mpv "C:\Tools\mpv\mpv.exe" --list-devices
python -m host.server --mpv "C:\Tools\mpv\mpv.exe" --device "wasapi/REPLACE_WITH_EXACT_HDMI_DEVICE_ID"
```

You can substitute `py -3` for `python` if that is your Python launcher. To confirm standalone HDMI passthrough before using DualTheater, stop the host and run this audio-only test with a known TrueHD Atmos source:

```powershell
& "C:\Tools\mpv\mpv.exe" --vid=no --ao=wasapi --audio-exclusive=yes --audio-spdif=truehd --audio-device="wasapi/REPLACE_WITH_EXACT_HDMI_DEVICE_ID" "D:\Movies\movie.mkv"
```

Close that test player before starting DualTheater. Independently confirm normal audio and the soundbar/receiver's format indication. The TV app cannot fix a standalone HDMI passthrough failure.

### 4. Pair the TV and load a movie

1. Leave the Windows host running. Open **http://localhost:8764** on that same Windows laptop or desktop PC.
2. Open the TV app and select your computer's name. Enter the six-digit code shown in the Windows terminal or browser controller. This app pairing is separate from ADB pairing; remembered app credentials are reused on later connections.
3. In the Windows browser controller's **Prepare the original media** section, paste the full local movie path, for example `D:\Movies\movie.mkv`, **without surrounding quotes**. This is a text field, not a file-upload button; the file stays on the computer.
4. Leave **Initial audio track** at `auto` to select TrueHD, or enter an mpv audio-track ID when needed. Press **Load** and wait for preparation, then **Play / resume**.
5. Confirm the TV's active HDR mode and the soundbar/receiver's Atmos indication independently. Software status alone does not prove correct physical output.

Allow Python on the private home network if prompted. Discovery uses UDP 8767, control TCP 8766 and media TCP 8765. The browser controller binds to localhost on TCP 8764; it is not a browser remote for the phone or TV. Guest-network isolation, VPN routing or firewall rules may block discovery. Use the remembered-computer shortcut or **Advanced connection** if needed; see [connection setup](easy-connection.md).

## Operating the player

| Task | How to do it |
| --- | --- |
| Play or pause | Press the TV remote's middle/OK button, or **Play / resume** / **Pause** in the Windows browser. |
| Seek with the TV remote | Press left/right for a 10-second preview; hold for a larger jump and release to commit. A seek while paused stays paused. |
| Seek to an exact time | Enter seconds in **Seek to seconds** in the Windows browser, then press **Seek**. For example, `600` seeks to 10:00. |
| Change audio language/track | Select a track under **Audio track** and press **Switch track**. Normal mode requires TrueHD output; other codecs are not a supported fallback in this beta. |
| Load another movie | Replace the full media path in the browser, press **Load**, wait for preparation, then **Play / resume**. |
| Recover after a disturbance | If picture/audio are out of step, try **Resynchronize**. If the connection was lost, reconnect the TV, reload the media and then resume. |
| Stop the session | Pause playback, then press **Ctrl+C** in the Windows host terminal. Closing just the browser page does not stop the host. |

The original MKV remains on Windows throughout playback. Keep the host running and the selected HDMI audio device connected. Brief receiver relock can occur after a pause or seek.

### Adjust physical lip-sync

Use **Calibrate physical latency** in the Windows browser controller while watching a clear sound/picture event. Increase **Video lead** if sound arrives before the picture; decrease it if sound arrives late. Use the 10 ms buttons or enter a value, press **Save**, then **Resynchronize** to apply a large adjustment immediately. The offset is saved across launches. These controls do not re-encode or change the speed of the TrueHD audio.

You can load the included `calibration-SDR-TrueHD-no-Atmos.mkv` using its full extracted path for a flash/beep test. It is **SDR with stereo TrueHD, not an HDR/Atmos sample**; confirm the result again with the actual movie and processing modes. Automatic camera/microphone calibration is absent from the published beta; the development branch has a separate [phone client](phone-calibration.md). A dedicated TV calibration screen is not included. Physical sync after start, seek and pause/resume still needs hardware validation.

### Common setup problems

- **No computers appear on the TV:** check that the host is running, both devices share a trusted LAN, and discovery is not blocked. Try the remembered connection or advanced fields.
- **No sound, noise or rejected audio:** verify the selected HDMI endpoint/input and cable, close competing exclusive-audio apps and test standalone mpv. Choose an actual TrueHD track; do not use PCM diagnostic mode as evidence of Atmos.
- **Buffering or repeated resynchronization:** check network throughput and the host's error/status messages. A 100 Mbps TV Ethernet port may be slower than remux peaks. See the [hardware test guide](hardware-test.md).
- **Installing a later beta:** use a matching host/APK pair, preserve the Windows `pairings.json` and `calibration.json` locally, and follow that release's instructions. A TV signing-certificate change may require uninstall/re-pairing.
