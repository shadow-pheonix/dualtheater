# TV Dolby Vision FEL compatibility

This is **TV 2.0.4-beta.1 on main**, with software validation and physical-device testing still pending. Windows remains 2.0.1-beta.1, phone remains 2.0.0, and published stable 2.0.0 downloads are preserved. Existing compatible Windows/phone clients can be used; no new Windows audio engine or phone installation is required.

The user reports that their TV plays Profile 7 MEL natively but does not play Profile 7 FEL. Automatic compatibility is therefore **FEL-only**, enabled by default. The app does not infer FEL from a filename, a Profile 7 codec label or the presence of an enhancement-layer NAL. It parses the Dolby Vision RPU's enhancement metadata using libdovi.

| Input | TV behavior |
| --- | --- |
| Positively identified Profile 7 MEL | Original Profile 7 format and encoded samples remain native, including EL bytes. |
| Positively identified Profile 7 FEL | Convert RPU metadata to Profile 8.1, signal the new profile before samples reach the decoder, and remove enhancement-layer NALs. Encoded base-layer picture NALs stay unchanged. |
| Profile 7 without a classifiable RPU | Bounded early probe, then native playback. It never claims FEL conversion based on uncertain metadata. |
| Profile 5, Profile 8, other DV codecs, SDR, HDR10/HDR10+ | Existing native path. HDR10+ SEI NALs are retained. |

This is a compatibility representation, **not full FEL reconstruction**. FEL residual picture information is discarded. The TV still needs a working Profile 8.1 hardware decoder; relabeling alone cannot provide that capability. Profile 5 is never treated as an HDR10-compatible base layer.

## Using it

1. Install the new TV APK as a matching-signature update when the TV is available. Keep the previous APK for rollback. Windows and phone can remain as installed.
2. Open **Video compatibility** on the TV home screen, or press **Up → Video compatibility** during a movie. It shows the detected/native/conversion status. That status describes sample processing, not a measurement of the panel's actual HDR output.
3. Automatic FEL-only mode is enabled by default. MEL stays native with that setting enabled. The setting is saved on the TV.
4. Changes take effect on the next movie load. On Windows use **Load movie** again, wait for preparation, then **Play**. Seeking alone keeps the existing source/mode. The TV does not independently seek, restart or resume to apply this setting.
5. If a detected FEL conversion fails, the normal coordinated error handling stops playback; the app does not send unconverted FEL samples under a Profile 8 claim. Turn compatibility off and load the movie again to compare the native path.

The source file, Windows HTTP/cache bytes and compressed HDMI audio remain unchanged. There is no video re-encoding. Sample PTS, sample flags, subtitle/audio outputs and existing synchronization kernels remain intact; preparation and transport still belong to the Windows coordinator. Recheck physical lip-sync if the TV changes its processing mode. The existing phone calibration clip is SDR/stereo TrueHD, so its result does not establish the latency of every DV picture mode.

## Implementation and bounds

- Media3 remains **1.9.0**. A forwarding extractor wraps video TrackOutput, intercepting both DataReader and ParsableByteArray sample-data families. Audio and subtitle outputs are delegated directly. The source factory preserves normal extractor ordering and subtitle-parser settings.
- Before the first downstream format is announced, the early clear Profile 7 samples are inspected for a positively classified RPU. MEL passes through unchanged. FEL is signaled as `dvhe.08` / `dvh1.08` with the original level and color information before transformed samples are emitted.
- The original RPU-only JNI bridge uses **libdovi / dolby_vision 3.4.0** mode 2 and validates the resulting Profile 8 RPU. Native calls receive one bounded RPU, not an entire movie or unbounded frame. Rust errors/panics become Java exceptions rather than a retry loop.
- RPUs are capped at 64 KiB; per-sample buffering is bounded between 2 and 16 MiB according to the Java heap. The early probe ends after eight samples or the heap-limited byte threshold (up to 8 MiB), with a bounded in-flight sample. An oversized or unclassified probe returns to native playback; an oversized already-classified FEL sample reports an error. Buffers reset on seeks; sample offsets and supplemental-data lengths are adjusted without changing PTS.
- Detection needs RPU metadata exposed in the selected HEVC elementary stream. Enhancement/RPU data stored only in a separate track or discarded BlockAdditional representation is not reconstructed by this feature. Encrypted inputs cannot be classified by this clear-stream filter and retain native playback. This is not a promise for every DV container/profile layout.
- The native libraries support **armeabi-v7a, arm64-v8a and x86_64**, API 26+, with 16 KiB ELF load alignment. Compiler paths are remapped. Source, Cargo.lock, notices and per-ABI library hashes are recorded in [provenance](../android/native/dolbyvision/provenance.json) and checked before every Android build.

## Source build and regression checks

Normal APK builds use the checked-in, verified ABI libraries; Rust and the NDK are only needed to rebuild native code. Use the existing `Build-TV.ps1` / Gradle instructions. To rebuild the bridge, install Rust 1.91.0, its Android standard-library targets and Android NDK **r27c / 27.2.12479018**:

```powershell
rustup toolchain install 1.91.0 --profile minimal
rustup target add --toolchain 1.91.0 aarch64-linux-android armv7-linux-androideabi x86_64-linux-android
$env:CARGO_TARGET_DIR = Join-Path $PWD 'build/dovi-native'
python tools_src/build_dovi.py --ndk '<path-to-android-ndk-r27c>'
python tools_src/generate_dovi_demux_fixtures.py
.\android\gradlew.bat --project-dir android :app:testDebugUnitTest :app:assembleDebug :app:lintDebug "-PdoviNativeDir=$env:CARGO_TARGET_DIR/release"
```

For host/JNI tests alone, `python tools_src/build_dovi.py --host-only` builds the bridge on the host without the NDK. CI runs this before TV tests and checks that generated fixtures match their committed bytes. The `doviNativeDir` property enables the actual JNI tests; without it those tests explicitly skip. Pure Java/filter/actual Matroska tests still run. Generated fixtures are original metadata and tiny container fixtures with placeholder picture NALs; they validate demux/conversion wiring, not visual decoding.

[Third-party notices](../THIRD_PARTY_NOTICES.md) include the bridge/libdovi/Rust/JNI/NDK texts packaged in APK assets. [Kodi's decoder-profile correction](https://github.com/xbmc/xbmc/pull/24143) and [libdovi's conversion implementation](https://github.com/quietvoid/dovi_tool/blob/main/dolby_vision/src/rpu/dovi_rpu.rs) informed the design. Kodi GPL code and ExoPlayer HDR Utils are not bundled.

Hardware acceptance must still verify the TV's own DV indication, native MEL versus converted FEL, HDR/color correctness, repeated seeks/pause-resume, lip-sync and a complete movie. No devices were contacted for this implementation.

## Completed candidate

Implementation/source snapshot **`b8ae62c`** has a separate TV-only APK/source/instructions/checksum bundle. The [validation record](dolby-vision-validation-2.0.4-beta.1.json) records 61 zero-skip TV JVM tests, five Rust tests, two existing Windows release-argument checks, assembly/lint and APK/native/source verification. These are local checks; source push skips automatic release publication. Physical TV HDR/color and full-movie synchronization acceptance remain pending. Windows and phone binaries were not rebuilt or replaced for this TV feature.
