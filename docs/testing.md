# Beta testing status

This release is **experimental and still in testing**. Limited successful operation does not establish broad Android TV/Google TV compatibility or stable physical A/V synchronization.

## Software verification

The development suite includes Python clock/servo tests, HTTP integrity and range tests, authenticated remote command/barrier tests, UDP discovery, remembered pairing and failure recovery. Optional Windows tests exercise real mpv with TrueHD packets and **null output**. Android JVM tests cover seek previews, request matching, time formatting, discovered-host validation and pairing-code handling.

Null-output tests do not open an HDMI receiver, decode HDR on a TV or prove acoustic lip-sync. Passing simulated clock/barrier tests is not a hardware accuracy guarantee. Android build/lint and APK signature checks provide packaging evidence, not device compatibility evidence.

## Limited hardware observations

Simultaneous native TV video decoding and receiver-reported TrueHD Atmos playback have been observed on one Android TV setup. A heap-aware buffer budget corrected an observed allocation failure. A physical HDMI connection issue was also encountered during testing.

These observations are intentionally anonymized. No raw device/network logs, private endpoint IDs, movie names, user paths or personal test reports are distributed.

## Still needs validation

- More Android TV/Google TV hardware and firmware combinations.
- Actual HDR mode and Dolby Vision profile behavior, including any enhancement-layer limitations.
- Discovery/pairing behavior across real home networks.
- TV remote actions, receiver relock and physical lip-sync after seek/resume.
- Long-session drift, high-bitrate peaks and network disruption recovery.

Use the [hardware test guide](hardware-test.md) before treating a setup as reliable.
