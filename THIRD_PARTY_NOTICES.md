# Third-party components

The Android APK contains AndroidX Media3 1.9.0 and its runtime dependencies, including AndroidX support libraries, Guava and Kotlin standard libraries. These retain their upstream copyrights and license terms. Exact runtime dependencies are resolved by the pinned Gradle project; run `:app:dependencies --configuration debugRuntimeClasspath` to inspect them.

- [AndroidX Media3 source and Apache 2.0 license](https://github.com/androidx/media/tree/1.9.0)
- [AndroidX source and licenses](https://android.googlesource.com/platform/frameworks/support/)
- [Guava source and Apache 2.0 license](https://github.com/google/guava)
- [Kotlin source and Apache 2.0 license](https://github.com/JetBrains/kotlin)
- [Gradle wrapper source and Apache 2.0 license](https://github.com/gradle/gradle)
- [JetBrains Java annotations and Apache 2.0 license](https://github.com/JetBrains/java-annotations)

See `docs/licenses/` for bundled upstream license texts. The Windows EXE bundles CPython and its Tk GUI runtime. Their license texts are embedded in the EXE and can be opened from **Settings & help → Third-party licenses**. The source ZIP requires a separately installed Python interpreter. Packaging uses [PyInstaller's distribution exception](https://pyinstaller.org/en/stable/license.html). Pillow is a build-only tool used to render the project's original icon artwork; it is not a desktop playback dependency.

- [CPython source and license](https://github.com/python/cpython)
- [Tcl source and license](https://github.com/tcltk/tcl/tree/core-8-6-13)
- [Tk source and license](https://github.com/tcltk/tk)
- [Pillow source and license](https://github.com/python-pillow/Pillow)

mpv is **not redistributed** in the EXE or source ZIP. On explicit user request, **Download mpv** retrieves the unchanged, checksum-pinned Windows asset directly from the [official mpv v0.41.0 release](https://github.com/mpv-player/mpv/releases/tag/v0.41.0); the app can also use an existing user installation. The downloaded distribution and its dependencies retain their upstream license terms. [mpv source/license](https://github.com/mpv-player/mpv/tree/v0.41.0), [upstream installation information](https://mpv.io/installation/) and [package provenance/checksum](docs/player-download.md) are linked for reference. The DualTheater license does not relicense mpv or its dependencies. The original calibration MKVs were generated specifically for this project using FFmpeg and contain no third-party film material. The phone client uses Android platform camera/audio/network APIs; its JUnit dependency is test-only. FFmpeg itself is not included or required for playback.

## Optional LG soundbar protocol inspection

The read-only S95TR inspector uses the wire framing and public protocol constants documented by [google/python-temescal](https://github.com/google/python-temescal) (Copyright 2018 Google LLC, Apache License 2.0) and the model/AV-delay interpretation documented by [diogolccsilva/ha-lg-soundbar](https://github.com/diogolccsilva/ha-lg-soundbar) (MIT). These projects do not endorse DualTheater. The protocol client is an independent implementation using Windows CNG; it does not bundle those libraries or Home Assistant. A configured AV-delay setting is not a measurement of total soundbar processing latency.

## TV Dolby Vision metadata compatibility

The TV app bundles an original, source-available MIT JNI bridge built against **quietvoid's `dolby_vision` / libdovi 3.4.0 (MIT)**, with JNI/Rust dependencies locked in [Cargo.lock](android/native/dolbyvision/Cargo.lock). [Native provenance](android/native/dolbyvision/provenance.json) pins compiler/NDK versions, source/lock hashes and three ABI libraries. The full collected dependency, Rust runtime and NDK notices are included [in the APK assets and source](android/app/src/main/assets/licenses/dolby-vision-native.txt); the original bridge [license](android/native/dolbyvision/LICENSE) applies to that bridge. The notices also retain build/target-specific dependency texts for completeness.

[Kodi's compatibility-mode behavior](https://github.com/xbmc/xbmc/pull/24143) informed the design; no Kodi GPL implementation is copied or linked. The TV uses libdovi directly through its own bounded RPU-only bridge, with Media3 1.9.0 retained. ExoPlayer HDR Utils was reviewed as a research reference but is not a packaged dependency. See [scope, operation and rebuilding](docs/dolby-vision-compatibility.md).
