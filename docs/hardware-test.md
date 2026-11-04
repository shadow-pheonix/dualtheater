# Hardware acceptance test

Start with a known compatible HDR10 source and a known TrueHD Atmos track. Confirm that the same Windows PC, HDMI connection and receiver already work with standalone mpv. Keep the TV companion's audio disabled.

1. Pair the TV and load the original MKV. Inspect the selected hardware decoder and parsed format. Advertising an HDR capability does not prove that the current source is displayed in that mode.
2. Press Play. Independently check the TV's active HDR indication and the soundbar/receiver's Atmos indication. `spdif-truehd` is evidence of compressed output, not proof of correct reception or Atmos rendering.
3. Calibrate physical lip-sync using a clear flash/beep, clap, impact or mouth movement. Increase video lead when sound is heard early; decrease it when sound is heard late. Keep picture/audio processing modes consistent after calibration.
4. Test repeated pause/resume, forward/backward seek, held remote keys and seek while paused. After each operation, verify correct receiver relock and physical sync.
5. Run a high-bitrate remux for at least 30–60 minutes and recheck synchronization near the end. Frequent hard recovery indicates a throughput or timing problem.
6. Disconnect/reconnect the TV briefly. Both sides should pause on failure. Reconnect and reload the media before resuming.
7. Only after HDR10 succeeds, test HDR10+ and each Dolby Vision profile actually used. Wrong colors, an unexpected mode or unsupported-profile errors are failed HDR tests; do not infer success from the filename.

The included SDR/stereo TrueHD calibration clip has no Atmos objects or HDR metadata. A movie may require a different offset.

For bug reports, provide sanitized codec/profile information, software versions, selected decoder, observed receiver format and a concise description. Remove personal paths, network addresses, pairing data, device identifiers and movie filenames. Do not upload films or raw unredacted logs.

## FEL compatibility acceptance (when devices are available)

Use matching APK rollback copies and the unchanged known-working Windows/mpv/audio setup. With TV FEL compatibility enabled, compare a positively classified P7 MEL sample (native format/bytes) and P7 FEL sample (P8.1 compatibility). Confirm the TV's own Dolby Vision indicator and picture/color quality; a software classification does not prove display output. Exercise repeated shared seek, pause/resume, subtitles, track changes and a full movie. Compare with compatibility off by loading again from Windows. Check actual lip-sync after picture-mode changes; the SDR phone sample does not establish every DV-mode output latency. See [feature bounds](dolby-vision-compatibility.md). These device checks have not been performed for this candidate.
