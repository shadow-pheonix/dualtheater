# Windows and TV playback audit — 2026-11-03

Reviewed the 2.0.1-beta.1 playback code from `3c4945c`: Windows coordinator/monitor, mpv IPC and launch arguments, source and network clocks, UDP/TCP transport, HTTP/storage serving, desktop command queues, and TV renderer, controls, lifecycle, cache/extractor and track-selection paths. This was a solo terminal/offline audit. After the user turned the TV off and prohibited playback checks, no further device or existing-host queries were made. The phone application was outside this audit's scope.

Four actionable issues were reproduced offline. They are **unfixed in the current build**; the audit did not change playback code. P2 means a normal-priority functional defect requiring a particular trigger. These findings do not establish the cause of the previously captured unsolicited timing-expiry pause.

## P2 — Windows can overwrite a newly applied phone calibration with a stale value

- **Locations:** `host/desktop.py:514–516` and `368–377`.
- **Trigger:** Windows has already received its initial offset, then the phone applies a different calibration. Later click **Save and resynchronize** in Windows without first correcting the manual field.
- **Behavior:** `_status()` populates the manual field only once per connection. Later phone-applied changes update the actual coordinator and calibration status text, but leave that field unchanged. The Save button writes the stale field back as a manual offset, replacing the phone result and resynchronizing to it.
- **Evidence:** called the actual desktop `_status` and `save_offset` methods with inert widget/value holders and a real isolated coordinator. After a generic fixture changed the active phone lead from 0 to 137.25 ms, the field remained `0`; Save replaced the phone correction with 0 ms and changed its source to manual. No GUI, phone or playback device was used.
- **Correction:** distinguish an edited/manual draft from the last observed active offset. Refresh an untouched draft when an external calibration changes, preserve full saved precision, and make deliberate overrides clear. Test external Apply, user typing during updates and mode/reconnection changes.

## P2 — Invalid seek input interrupts valid playback

- **Locations:** `host/desktop.py:345–351`, `host/server.py:1015–1022` and `1069–1072`.
- **Trigger:** enter `nan`, a negative seek time, or a time beyond the movie duration in Windows' exact-seek field.
- **Behavior:** `float()` accepts these inputs as numbers, so Windows submits them. The coordinator rejects them inside the same exception handler used for playback failures; `fail()` then pauses both devices, advances the epoch and changes state to `error`. A validation error should leave the current movie playing.
- **Evidence:** invoked the real `DesktopWindow.seek_exact` method with minimal value holders, without constructing a GUI. Each of the three inputs reached the real `Coordinator.action` with fake media/TV endpoints; each produced an audio pause, TV pause command and error state.
- **Correction:** validate finite/range values before the operation takes ownership of playback. Keep server-side validation too, with input rejection separated from failures after a seek begins. Regressions should assert unchanged epoch, position and audio/video state for rejected requests.

## P2 — A cancelled TV connection can still open and leak its socket

- **Location:** `android/app/src/main/java/dev/dualtheater/tv/ControlClient.java:24–68`.
- **Trigger:** the Activity closes a client immediately after scheduling its connection thread, before that thread assigns `socket`.
- **Behavior:** `close()` marks the client closed while no socket exists. The reader thread subsequently creates/connects a socket and sends hello despite cancellation. Its receive loop is skipped, and there is no `finally` block closing the local socket. Subsequent `disconnect()` calls cannot clean it up because the closed-state compare-and-set has already succeeded.
- **Evidence:** compiled the actual `ControlClient` socket/thread implementation in a local JVM harness with minimal Android `Build` and JSON stubs. In 100 immediate connect/close attempts, all 100 emitted a hello and left the accepted connection open. This proves the lifecycle race on that scheduler; it does not establish its incidence on a TV or reproduce the complete Android/host handshake. With a valid handshake, the host's single-TV slot can remain occupied until its read timeout, delaying reconnection.
- **Correction:** make socket adoption cancellation-safe, check closure before connecting/sending hello, and close each attempt's local socket unconditionally on exit. Test cancellation before thread startup, during connect, normal EOF and Activity retirement; listener notification should remain once-only.

## P2 — The first track reaching EOF truncates the other track

- **Location:** `host/server.py:1327–1330`.
- **Trigger:** TV video ends before audio, or audio ends before the remaining TV video. Different track lengths and signed calibration lead can cause this at an otherwise normal file ending.
- **Behavior:** the monitor uses `TV ended OR mpv EOF`, then pauses both immediately. It has no bounded end-of-track drain phase, so remaining original content can be cut off.
- **Evidence:** one iteration of the real coordinator monitor used a 300-second fixture with a permitted positive 1,000 ms video lead: TV reached 300 seconds while audio was at 299 seconds and `eof-reached=false`. The monitor immediately paused audio with one second remaining and marked the session ended. The symmetric condition can cut the final video frames. The pinned [Media3 1.9.0 end-state logic](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/ExoPlayerImplInternal.java#L1396) confirms that TV completion is based on its own renderers and timeline position; it does not wait for the external HDMI device.
- **Correction:** explicitly handle the final tail, preserving 1x audio and the calibration schedule, with a bounded completion deadline. Merely changing `or` to `and` is insufficient because ordinary progress/clock watchdogs would still treat the already-ended track as stalled. Test both track-order endings, positive/negative lead and genuine mid-file stalls.

## Validation and remaining uncertainty

The correction preceding this audit passed 41 TV JVM tests, Android assembly/lint, 11 focused host diagnostic tests and terminal-only portable core verification. Those checks do not cover the four reproduced scenarios above. The new 900-second hardware observation was interrupted when the user turned off/disconnected the TV; it is not recorded as a pass. Before that shutdown the user reported continuous audio and in-sync dialogue.

The original long-session pause was a receiver anchor-expiry fault with healthy video buffering and fresh source audio. The candidate aligns maximum TV holdover with the existing three-second timing-link deadline while preserving the uncertainty ceiling. The underlying delivery/processing gap remains unidentified, and whole-movie reliability remains unverified. No additional timeout widening, audio-speed change or new drift controller was introduced during this audit.

The previously observed difference between the managed mpv build and the user's working external build remains a setup-dependent compatibility issue: software/null-output verification cannot establish physical WASAPI/HDMI continuity. Native renderer lifecycle, real cache/network scheduling, repeated remote operations and full-film behavior still need device validation when the user makes the hardware available again.
