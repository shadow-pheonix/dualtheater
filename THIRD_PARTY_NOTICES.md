# Third-party components

The Android APK contains AndroidX Media3 1.9.0 and its runtime dependencies, including AndroidX support libraries, Guava and Kotlin standard libraries. These retain their upstream copyrights and license terms. Exact runtime dependencies are resolved by the pinned Gradle project; run `:app:dependencies --configuration debugRuntimeClasspath` to inspect them.

- [AndroidX Media3 source and Apache 2.0 license](https://github.com/androidx/media/tree/1.9.0)
- [AndroidX source and licenses](https://android.googlesource.com/platform/frameworks/support/)
- [Guava source and Apache 2.0 license](https://github.com/google/guava)
- [Kotlin source and Apache 2.0 license](https://github.com/JetBrains/kotlin)
- [Gradle wrapper source and Apache 2.0 license](https://github.com/gradle/gradle)
- [JetBrains Java annotations and Apache 2.0 license](https://github.com/JetBrains/java-annotations)

See `docs/licenses/` for bundled upstream license texts. The Windows host uses the Python standard library and an existing user-installed mpv; neither runtime nor mpv is redistributed in this bundle. The sample MKV was generated specifically for this project using FFmpeg and contains no third-party film material. FFmpeg itself is not included or required for playback.
