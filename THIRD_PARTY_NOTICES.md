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

mpv is selected from an existing user installation and is not redistributed in the EXE or source ZIP. The sample MKV was generated specifically for this project using FFmpeg and contains no third-party film material. FFmpeg itself is not included or required for playback.
