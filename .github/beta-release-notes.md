# DualTheater 2.0.0

Play native video on an Android TV/Google TV while an existing Windows laptop or desktop PC sends untouched TrueHD Atmos over HDMI to a compatible sound system—without buying another dedicated playback box.

## What changed

- Authenticated UDP clock/anchor timing avoids ordered timing backlogs; movie bytes and coordinated playback controls stay on TCP. The v1.0 video correction math and saved calibration are retained.
- Corrected false clock/frame watchdog stops, long-movie position overflow, renderer rebuffer lifecycle and TV menu overlays. Added bounded disk read-ahead and efficient extractor reads.
- Embedded subtitle and compressed audio-track choices across Windows, TV and phone; automatic English TrueHD Atmos preference when identified in metadata.
- TV browsing of granted Windows folders/subfolders and available Android storage, metadata-qualified audio badges, guided Library/Player navigation and recommended phone calibration with a volume reminder.

## Install and use

Download the Windows x64 EXE and TV APK below; the recommended phone APK is also included. Run one Windows host. Keep your known-working mpv distribution and HDMI endpoint; Browse accepts it and saves the choice privately. mpv is not bundled. The pinned Download mpv option remains available, but the accepted hardware test used a newer external build after the downloaded runtime produced sound gaps on that setup.

Update Windows and TV together. Allow control TCP 8766, timing UDP 8766, media TCP 8765 and discovery UDP 8767 on the trusted home LAN (custom control ports apply to both protocols). Connect laptop/PC HDMI, or a compatible display-capable USB-C-to-HDMI adapter, to the receiver's HDMI IN. Pair the TV, load a movie, prepare and Play. Existing compatible phone companions remain usable; 2.0 provides matching downloads for all clients.

Application IDs and private profiles are retained. EXE is unsigned and APKs are development-signed; a signing-certificate mismatch requires reinstall/re-pairing. Preserve private settings/calibration before updating. Earlier releases remain unchanged.

## Verified and remaining testing

The source candidate passed 151 host tests, 39 TV JVM tests, assembly/lint and final portable core verification. A 15-minute movie test completed uninterrupted, with zero reported errors, automatic recoveries or dropped video frames. The user confirmed continuous audio and in-sync dialogue. Version 2.0 promotion changes release metadata/documentation and rebuilds the assets; see CI provenance/checksums for this release's packaging checks.

Whole-movie, additional hardware/HDR profiles, actual subtitle/track/provider coverage and instrumented physical accuracy remain under testing. Dolby Vision Profile 7/FEL reconstruction is not promised. Calibration's reference is SDR/stereo TrueHD without Atmos. Extra compressed codecs have null-output software coverage, not broad HDMI acceptance. UDP remote operations have real-socket software coverage; no additional hardware interruption was inserted after the requested endurance test. Object-audio badges describe metadata, not receiver confirmation. Android storage must remain foreground, seekable and available; external subtitle sidecar picking is not included.

[Download and operating instructions](https://github.com/shadow-pheonix/dualtheater/blob/main/README.md) · [Full client guide](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/next-version.md) · [Validation context](https://github.com/shadow-pheonix/dualtheater/blob/main/docs/context.md)
