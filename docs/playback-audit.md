# Windows and TV playback audit

Last organized: **2026-11-04 (Asia/Calcutta)**. Original audit and follow-up reviews: 2026-11-03.

This tracker contains **14 records: four offline-reproduced findings and ten unverified code-review candidates; zero are resolved**. AUD-007 extends AUD-002's validation/failure-handling root cause, so the record count is not a count of independent bugs. No implementation, tests, binaries or device behavior changed while organizing this file.

Reviewed the 2.0.1-beta.1 playback code from `3c4945c`: Windows coordinator/monitor, mpv IPC and launch arguments, source and network clocks, UDP/TCP transport, HTTP/storage serving, desktop command queues, and TV renderer, controls, lifecycle, cache/extractor and track-selection paths. This was a solo terminal/offline audit. After the user turned the TV off and prohibited playback checks, no further device or existing-host queries were made. The phone application was outside this audit's scope.

## Findings

| ID | Client | Priority | Finding | Verification | Resolution |
| --- | --- | --- | --- | --- | --- |
| AUD-001 | Windows | P2 | Stale manual offset overwrites phone calibration | Verified offline | Yet to be resolved |
| AUD-002 | Windows / coordinator | P2 | Invalid seek input interrupts playback | Verified offline | Yet to be resolved |
| AUD-003 | TV | P2 | Cancelled connection opens and leaks a socket | Verified offline | Yet to be resolved |
| AUD-004 | Windows / TV | P2 | First endpoint EOF truncates the other track | Verified offline | Yet to be resolved |
| AUD-005 | Windows / TV | P2 | Control liveness hides stale TV video status | Code review only — unverified | Yet to be resolved |
| AUD-006 | Windows | P2 | Racing TV handshakes claim the single-TV slot | Code review only — unverified | Yet to be resolved |
| AUD-007 | Windows | P2 | Rejected load/offset interrupts playback; related to AUD-002 | Code review only — unverified | Yet to be resolved |
| AUD-008 | Windows | P2 | Failed audio-track selection lacks rollback | Code review only — unverified | Yet to be resolved |
| AUD-009 | TV | P3 | Same-URI seek temporarily prefetches the old position | Code review only — unverified | Yet to be resolved |
| AUD-010 | Windows | P2 | Transient sampler exception latches a fatal error | Code review only — unverified | Yet to be resolved |
| AUD-011 | Windows / TV | P2 | mpv IPC failure skips the independent TV pause | Code review only — unverified | Yet to be resolved |
| AUD-012 | Windows / TV | P2 | Unreachable UDP negotiation lacks TCP fallback | Code review only — unverified | Yet to be resolved |
| AUD-013 | TV / Windows | P2 | Oversized TV status exceeds the control-frame limit | Code review only — unverified | Yet to be resolved |
| AUD-014 | Windows | P3 | Diagnostic write failure interrupts playback/monitor | Code review only — unverified | Yet to be resolved |

Update this tracker whenever findings, reproductions, fixes or validation change. Keep IDs stable. Verification and resolution are separate: a verified issue can remain unresolved. Promote a candidate to **Verified findings** only after recording supporting reproduction evidence. Mark an issue **Resolved** only with its fix commit/build and targeted regression result; record remaining device-validation limits separately.

**Unverified follow-up candidates — first review:**

The follow-up reviewed Windows coordinator commands/monitoring, TV session ownership and receiver liveness, mpv audio-track verification, and TV cache seek/read-head handling on `main` at `4a6dc4c`. No playback implementation changed between the original audited commit `3c4945c` and this revision; the intervening changes were documentation only. The **four P2 issues above remain the prior audit's offline-reproduced findings**.

The five issues below are **additional code-review findings, not reproduced defects**. Severity expresses anticipated playback impact if the described condition is triggered. No new JVM/Python tests, device playback, ADB commands, host commands, or live network observations were performed for this follow-up.

### AUD-005 — P2 (code review) — Control liveness can hide indefinitely stale TV video status

- **Locations:** `host/server.py:405–410`, `1303–1338`, `1357–1394`, `1519–1546`; `android/app/src/main/java/dev/dualtheater/tv/ControlClient.java:46–67`.
- **Trigger:** The TV's status-producing main thread stops updating while its separate control reader can still process pings and send pongs (particularly relevant to baseline mode).
- **Behavior:** `tv()` checks the timestamp of **any** received control message, not the last status report. The monitor intentionally skips frame/timeline checks on status older than 500 ms, but has no independent maximum *status-age* deadline. Control pongs can thus keep the peer alive while Windows mpv audio continues with no fresh evidence of TV video progress. The receiver's separate source/timing checks may stop the session in some modes; this does not establish a video-status bound.
- **Evidence/uncertainty:** This is a control-flow inference, not a reproduced frozen-TV-main-thread incident. The existing `test_delayed_status_does_not_masquerade_as_a_frozen_video_frame` verifies that a 1.3-second status delay should **not** cause a false pause; it does not exercise a sustained status outage with fresh control pongs.
- **Correction:** Preserve short status-delay tolerance, but set an explicit bounded stale-video-telemetry deadline separate from control socket liveness. Test brief delays, prolonged status silence with live pongs, and genuinely stale/dead connections in all three sync modes.

### AUD-006 — P2 (code review) — Simultaneous TV handshakes can both claim the single-TV slot

- **Location:** `host/server.py:1503–1524` (`ControlHandler.handle`).
- **Trigger:** Two authenticated TV control connections reach the availability check at nearly the same time.
- **Behavior:** `if app.peer and not app.peer.closed` and the subsequent `app.peer = peer` run in separate server threads without an atomic reservation. Both connections can pass the check, receive a welcome, and remain alive even though the coordinator points at only one of them. Status/ACKs, controls, and session-bound timing can then disagree about which TV owns playback.
- **Evidence/uncertainty:** The unprotected check/assignment is visible in code; no concurrent-handshake regression or hardware reproduction was run.
- **Correction:** Reserve and release the sole TV slot under a short dedicated lock and reject the losing connection before sending welcome. Test racing handshakes, disconnect during takeover attempts, and reconnection after an abandoned session.

### AUD-007 — P2 (code review) — Rejected load and offset requests can stop the currently playing movie

- **Locations:** `host/server.py:496–503`, `941–1073` (especially `997–1003`, `1014–1031`, `1069–1072`).
- **Trigger:** During valid playback, submit a non-existent/unsupported movie path through the local load command or a non-finite/out-of-range offset through the controller.
- **Behavior:** Input validation may reject the request **before** the new load/offset takes ownership of playback, but the shared `Coordinator.action` exception handler still invokes `fail()`, which pauses both devices and advances the epoch. This is a broader instance of the previously reproduced invalid-seek bug, not a new independent root cause.
- **Evidence/uncertainty:** The paths are visible in code; these particular invalid-load/offset scenarios were not rerun in this review.
- **Correction:** Validate requests before entering the playback-failure boundary. Keep coordinated failure handling for errors *after* an operation has begun mutating media/playback. Test that invalid load, seek and offset requests preserve active epoch, playing state, audio, video and current media.

**Relationship:** extends AUD-002; these load/offset cases remain unverified and do not inherit the seek reproduction.

### AUD-008 — P2 (code review) — Failed audio-track change leaves no rollback to the previous working selection

- **Locations:** `host/server.py:539–585`, `1021–1028`, `1043–1058`; `host/mpv.py:227–252`.
- **Trigger:** Choose an audio track whose codec is cataloged as supported, but whose selected track cannot be verified as compressed passthrough on the active WASAPI/HDMI endpoint.
- **Behavior:** The host pauses, changes mpv's `aid`, seeks/prepares, then runs `mpv.verify()`. Codec-level `supported` is not an endpoint-specific guarantee. On failure, the coordinator goes to `error` without restoring the prior `aid` and playback position. A formerly playable movie can remain stranded on the failed selection.
- **Evidence/uncertainty:** This follows from command ordering and lack of rollback. No failing HDMI endpoint/codec combination was exercised in this follow-up.
- **Correction:** Save old `aid`, play state and position; verify the new selection; if it cannot be used, restore and verify the previous track through the existing coordination barrier. Distinguish a recoverable track-choice rejection from a genuine device/output failure. Add successful/failed switch regressions.

### AUD-009 — P3 (code review) — Reusing the same media URI can temporarily prefetch from the previous seek position

- **Locations:** `android/app/src/main/java/dev/dualtheater/tv/ReadAheadCache.java:212–245`, `271–312`, `477–494`; `ReadAheadWindow.java:8–16`.
- **Trigger:** Seek substantially within the same movie URL; native preparation becomes READY before foreground consumption crosses the read-head notification threshold.
- **Behavior:** A new `TrackingDataSource.open()` calls `opening(uri)`, but `opening` does not reinitialize the read head for an unchanged URI. The worker resumes after READY using the old byte position until foreground reads signal a new head (normally at 256 KiB consumed). This can spend temporary network/cache I/O around the obsolete location while the newly sought position needs data.
- **Evidence/uncertainty:** A plausible performance hazard from code inspection, **not** evidence that this caused a real TV underrun. Existing cache design intentionally suppresses overly frequent read-head updates and prioritizes preparation.
- **Correction:** Assess whether the new `DataSpec.position` can safely establish the seek/reopen read head without breaking coalesced reads, caching, or bounded cancellation. Regressions should instrument a large seek, short prefetch/READY window, cache holes/eviction and end-of-file ranges; measure foreground stalls before changing scheduling.

**Unverified follow-up candidates — second review:**

This independent read-only pass audited playback failure paths on `main` at commit `e6852d4`, after the first findings were documented. It traced the Windows mpv IPC and audio sampler, fail-safe dual-player pause behavior, negotiated TV timing transport, the TV status serialization/control framing, and playback-monitor diagnostics I/O. It adds **four P2 and one P3 candidate findings**, beyond the four earlier offline-reproduced P2 defects and five earlier static-review findings. All five items below are **static code-path findings, not separately reproduced on a running application or physical device**. The earlier invalid-seek/load issue, control-session race, end-of-file truncation, stale status watchdog, failed audio-track rollback, and read-ahead seek risks are intentionally not re-counted here.

### AUD-010 — P2 (code review) — One mpv audio sampler exception latches an error after source observations recover

- **Locations:** `host/server.py:857–898` (`sample_audio`), `766–777` (`start`), `1303–1314` (`monitor`).
- **Trigger:** A transient `mpv.timed_audio_sample()` IPC timeout/error occurs while a movie is playing; subsequent source samples may succeed normally.
- **Behavior:** The sampler assigns `self.timing_error = str(e)` on an exception but does not clear that field on subsequent successful samples. The monitor treats any nonempty `timing_error` as a fatal error and calls `fail()`, stopping coordinated playback. `start()` clears `timing_error` at a new playback start, but that does not prevent a live, recoverable sampler exception from latching an interruption. Some errors, such as a genuine timeline discontinuity or persistent IPC failure, must still stop playback.
- **Evidence/uncertainty:** Error assignment, successful-sample path, and fatal monitor check are directly visible in code. No induced single-shot IPC-timeout regression or hardware reproduction was run.
- **Correction/regression:** Separate transient sampler failure counters/last-good-sample age from persistent faults. Define a bounded freshness/grace policy that can recover on successful observations while still failing safely if the source clock becomes stale or discontinuous. Inject one failed `timed_audio_sample` followed by fresh samples and separately test sustained failure and a real timeline discontinuity.

### AUD-011 — P2 (code review) — mpv IPC failure can prevent the independent TV pause command

- **Locations:** `host/server.py:412–452` (`pause_both` and `fail`), `host/mpv.py:150–178` (command/property errors).
- **Trigger:** mpv's IPC pipe disconnects or a property query/pause command raises while Windows attempts to stop both players during active playback.
- **Behavior:** `pause_both()` first samples mpv's `time-pos` and calls `mpv.pause()`. Only afterward does it send the TV `pause` request. If either mpv operation raises, the TV request is skipped. The `fail()` exception fallback attempts another mpv pause, but does not independently send the TV a pause. In baseline mode, TV video may continue until a separate watchdog or connection failure; audio-clock modes may later freeze on external-clock expiry, but not because the coordinated pause succeeded.
- **Evidence/uncertainty:** The exception short-circuit is an explicit consequence of the command ordering. A fault-injected mpv disconnection was not performed.
- **Correction/regression:** Independently attempt both stop/pause commands and gather their errors without skipping either device, while preserving safe epoch and state transitions. Inject failures in both `get('time-pos')` and `pause()`, and verify that a TV pause is still attempted in each sync mode.

### AUD-012 — P2 (code review) — UDP timing is preferred without a TCP fallback when UDP cannot be reached

- **Locations:** `host/server.py:1510–1525` and `1903–1920`; `android/app/src/main/java/dev/dualtheater/tv/MainActivity.java:965–983`; `TimingClient.java:20–22`, `74–130`.
- **Trigger:** Host-side UDP timing socket setup succeeds and UDP is advertised, but the TV-to-host UDP path is filtered/unreachable while TCP control, timing and media could otherwise work.
- **Behavior:** The TV chooses `connectDatagrams()` exclusively when `timing_transport` is `udp`. Its handshake retry loop continues using UDP indefinitely if no `timing_ready` arrives; there is no switch to the already-implemented authenticated TCP timing path. In `servo` or `audio-clock` mode this can block timing readiness and therefore movie load/start.
- **Evidence/uncertainty:** Selection and retry branches are directly visible. The code has UDP packet-loss coverage but no demonstrated UDP-unreachable/TCP-fallback regression; no firewall or hardware failure was induced.
- **Correction/regression:** After a bounded UDP negotiation failure, transparently try the session-bound TCP timing connection without weakening token/session authorization, and define safe transport handover on recovery. Test blocked outbound/inbound UDP with TCP available, normal UDP operation, and reconnect/epoch changes.

### AUD-013 — P2 (code review) — Unbounded per-status TV metadata can exceed the host's control-frame limit

- **Locations:** `android/app/src/main/java/dev/dualtheater/tv/MainActivity.java:734–752`, `1177–1224`, `1235–1250`; `ControlClient.java:41–65`; `host/server.py:1527–1530`.
- **Trigger:** The loaded media exposes an unusually large number of subtitle tracks or long subtitle metadata, or the TV reports a large codec-capability catalog.
- **Behavior:** The TV serializes all discovered subtitle entries and decoder capabilities into every recurring `status` JSON message (the telemetry callback runs roughly every 100 ms), without bounding the encoded byte count. The host reads at most 65,537 bytes and terminates the control session when an individual frame exceeds 65,536 bytes. Such a catalog can cause repeated disconnections rather than merely truncating UI metadata. As an illustration, 250 subtitle labels of 160 bytes contribute about 40 KiB *before* JSON keys, other subtitle fields, decoder catalog and normal status telemetry. Actual overflow depends on the source's metadata and the device.
- **Evidence/uncertainty:** The unbounded serialization and fixed host frame limit are visible in code. No large-catalog device/fixture reproduction was run, and ordinary movie metadata is likely much smaller.
- **Correction/regression:** Set a strict encoded size bound on TV status; send only bounded critical telemetry frequently and transfer track/codec catalogs in capped or paginated messages. Test 250+ tracks with long labels, large decoder reports and simultaneous playback status/ACK traffic. Confirm that playback and control liveness continue when optional metadata must be truncated.

### AUD-014 — P3 (code review) — Diagnostic write failures can interrupt playback and terminate the monitor

- **Locations:** `host/server.py:242–248` (`log`), `430–452` (`fail`), `1303–1440` (`monitor`, especially `1427–1438`).
- **Trigger:** Timing CSV flush/write or event-log append raises due to full disk, revoked permissions, failed storage, or an analogous filesystem error while A/V playback is otherwise healthy.
- **Behavior:** The playback monitor writes and flushes diagnostic CSV data inside the same error boundary as sync enforcement. Any I/O exception invokes `fail()` and pauses the movie. `fail()` itself calls `log()` without an independent I/O safeguard, so another filesystem failure can escape the monitor's exception handler and terminate that thread, removing subsequent playback supervision.
- **Evidence/uncertainty:** The unguarded diagnostic I/O and exception escalation follow from the code. No injected disk-full/permission failure or monitor-death reproduction was run. Slow writes may also delay monitoring, but the latency impact is not measured.
- **Correction/regression:** Make telemetry/event logging best-effort and bounded independently of playback, with a diagnostic failure flag/counter rather than mandatory coordination failure. Inject CSV write/flush and event-log errors and verify healthy playback continues, while the monitor remains alive and still fails safely on genuine clock or video faults.

## Verified findings

Only AUD-001–AUD-004 have recorded offline reproductions. The ten review candidates above have not been promoted or independently retested during this organization. These findings do not establish the cause of the earlier unsolicited timing-expiry pause.

### AUD-001 — P2 — Windows can overwrite a newly applied phone calibration with a stale value

- **Locations:** `host/desktop.py:514–516` and `368–377`.
- **Trigger:** Windows has already received its initial offset, then the phone applies a different calibration. Later click **Save and resynchronize** in Windows without first correcting the manual field.
- **Behavior:** `_status()` populates the manual field only once per connection. Later phone-applied changes update the actual coordinator and calibration status text, but leave that field unchanged. The Save button writes the stale field back as a manual offset, replacing the phone result and resynchronizing to it.
- **Evidence:** called the actual desktop `_status` and `save_offset` methods with inert widget/value holders and a real isolated coordinator. After a generic fixture changed the active phone lead from 0 to 137.25 ms, the field remained `0`; Save replaced the phone correction with 0 ms and changed its source to manual. No GUI, phone or playback device was used.
- **Correction:** distinguish an edited/manual draft from the last observed active offset. Refresh an untouched draft when an external calibration changes, preserve full saved precision, and make deliberate overrides clear. Test external Apply, user typing during updates and mode/reconnection changes.

### AUD-002 — P2 — Invalid seek input interrupts valid playback

- **Locations:** `host/desktop.py:345–351`, `host/server.py:1015–1022` and `1069–1072`.
- **Trigger:** enter `nan`, a negative seek time, or a time beyond the movie duration in Windows' exact-seek field.
- **Behavior:** `float()` accepts these inputs as numbers, so Windows submits them. The coordinator rejects them inside the same exception handler used for playback failures; `fail()` then pauses both devices, advances the epoch and changes state to `error`. A validation error should leave the current movie playing.
- **Evidence:** invoked the real `DesktopWindow.seek_exact` method with minimal value holders, without constructing a GUI. Each of the three inputs reached the real `Coordinator.action` with fake media/TV endpoints; each produced an audio pause, TV pause command and error state.
- **Correction:** validate finite/range values before the operation takes ownership of playback. Keep server-side validation too, with input rejection separated from failures after a seek begins. Regressions should assert unchanged epoch, position and audio/video state for rejected requests.

### AUD-003 — P2 — A cancelled TV connection can still open and leak its socket

- **Location:** `android/app/src/main/java/dev/dualtheater/tv/ControlClient.java:24–68`.
- **Trigger:** the Activity closes a client immediately after scheduling its connection thread, before that thread assigns `socket`.
- **Behavior:** `close()` marks the client closed while no socket exists. The reader thread subsequently creates/connects a socket and sends hello despite cancellation. Its receive loop is skipped, and there is no `finally` block closing the local socket. Subsequent `disconnect()` calls cannot clean it up because the closed-state compare-and-set has already succeeded.
- **Evidence:** compiled the actual `ControlClient` socket/thread implementation in a local JVM harness with minimal Android `Build` and JSON stubs. In 100 immediate connect/close attempts, all 100 emitted a hello and left the accepted connection open. This proves the lifecycle race on that scheduler; it does not establish its incidence on a TV or reproduce the complete Android/host handshake. With a valid handshake, the host's single-TV slot can remain occupied until its read timeout, delaying reconnection.
- **Correction:** make socket adoption cancellation-safe, check closure before connecting/sending hello, and close each attempt's local socket unconditionally on exit. Test cancellation before thread startup, during connect, normal EOF and Activity retirement; listener notification should remain once-only.

### AUD-004 — P2 — The first track reaching EOF truncates the other track

- **Location:** `host/server.py:1327–1330`.
- **Trigger:** TV video ends before audio, or audio ends before the remaining TV video. Different track lengths and signed calibration lead can cause this at an otherwise normal file ending.
- **Behavior:** the monitor uses `TV ended OR mpv EOF`, then pauses both immediately. It has no bounded end-of-track drain phase, so remaining original content can be cut off.
- **Evidence:** one iteration of the real coordinator monitor used a 300-second fixture with a permitted positive 1,000 ms video lead: TV reached 300 seconds while audio was at 299 seconds and `eof-reached=false`. The monitor immediately paused audio with one second remaining and marked the session ended. The symmetric condition can cut the final video frames. The pinned [Media3 1.9.0 end-state logic](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/ExoPlayerImplInternal.java#L1396) confirms that TV completion is based on its own renderers and timeline position; it does not wait for the external HDMI device.
- **Correction:** explicitly handle the final tail, preserving 1x audio and the calibration schedule, with a bounded completion deadline. Merely changing `or` to `and` is insufficient because ordinary progress/clock watchdogs would still treat the already-ended track as stalled. Test both track-order endings, positive/negative lead and genuine mid-file stalls.

## Resolved

**None.** AUD-001–AUD-014 remain open. No playback-code correction or new regression result was supplied by the follow-up reviews. Add the ID, fix commit/build, passing regression evidence and any hardware-validation limits here when resolution is established.

## Yet to be resolved

- [ ] **AUD-001 (verified defect):** Refresh an untouched manual-offset field after external calibration; test edited drafts, precision and mode changes.

- [ ] **AUD-002 (verified defect):** Reject invalid seek input before playback mutation; assert unchanged epoch, position and audio/video state.

- [ ] **AUD-003 (verified defect):** Make socket adoption and cleanup cancellation-safe; cover cancellation, EOF and once-only notification.

- [ ] **AUD-004 (verified defect):** Add bounded final-track draining; cover both EOF orders, signed lead and genuine stalls.

- [ ] **AUD-005 (unverified candidate):** Reproduce sustained missing video status with live control pongs; define a separate bounded status-age deadline.

- [ ] **AUD-006 (unverified candidate):** Reproduce racing authenticated handshakes; reserve/release the TV slot atomically.

- [ ] **AUD-007 (unverified candidate):** Extend AUD-002 validation coverage to rejected load/offset requests; preserve the current movie.

- [ ] **AUD-008 (unverified candidate):** Inject a failed passthrough track selection; verify restoration of the previous track and coordinated position.

- [ ] **AUD-009 (unverified candidate):** Instrument same-URI seeks and foreground/cache I/O before changing read-head scheduling.

- [ ] **AUD-010 (unverified candidate):** Inject transient and sustained sampler faults; distinguish recoverable observations from stale/discontinuous clocks.

- [ ] **AUD-011 (unverified candidate):** Inject mpv property/pause failures; ensure the independent TV pause is still attempted in every mode.

- [ ] **AUD-012 (unverified candidate):** Test UDP-unreachable/TCP-available negotiation; review a bounded fallback against session authorization and fail-safe behavior.

- [ ] **AUD-013 (unverified candidate):** Test oversized subtitle/codec catalogs; bound status frames while preserving critical telemetry and ACK traffic.

- [ ] **AUD-014 (unverified candidate):** Inject CSV/event-log errors; keep playback supervision alive while diagnosing logging failures.

**First-review priorities and proposed validation:**

The highest-value corrections are: (1) separate invalid input rejection from playback failure (including the original seek case), (2) drain the remaining track at EOF, (3) make TV connection ownership/cancellation safe, (4) enforce bounded TV video-status staleness, (5) recover from unsuccessful audio selection and keep calibration fields consistent. Investigate the cache seek prefetch concern with measured I/O before considering a change.

Suggested isolated regression cases: invalid seek/load/offset preserve ongoing playback; both audio-first and video-first EOF; immediate close-before-connect and racing authenticated TV handshakes; prolonged missing TV status while pongs continue; failure to establish passthrough after selecting another listed audio codec; long-distance seek with cache/foreground I/O instrumentation. These tests are **proposed, not run**.

The original long-session `audio_anchor_expired` interruption is still not explained by a proven underlying delivery/scheduling cause. The three-second TV holdover candidate does not establish whole-film reliability, HDR/Atmos compatibility across devices, or physical A/V accuracy. This follow-up did not request, start, or observe hardware playback.

**Second-review priorities and proposed validation:**

In safety order: (1) make pausing the TV independent of mpv IPC success; (2) avoid permanently latching recoverable audio sampler exceptions while still enforcing source-clock freshness; (3) add bounded UDP negotiation with TCP fallback; (4) bound status frames and separate bulky optional metadata; (5) isolate diagnostic I/O from playback supervision.

Proposed tests only: single and sustained sampler errors; failing mpv property/command during pause; UDP blocked with working TCP; pathological subtitle/decoder catalogs and status-frame sizes; diagnostic disk errors with the playback monitor still alive. **None of those tests was run as part of this review.** No playback implementation, binaries, test files, TV state, or hardware playback was changed or exercised. Published 2.0.0 and the unverified whole-movie/physical A/V accuracy limits remain unchanged.

**Previously recorded validation and remaining uncertainty:**

The correction preceding this audit passed 41 TV JVM tests, Android assembly/lint, 11 focused host diagnostic tests and terminal-only portable core verification. Those checks do not cover the four reproduced scenarios above. The new 900-second hardware observation was interrupted when the user turned off/disconnected the TV; it is not recorded as a pass. Before that shutdown the user reported continuous audio and in-sync dialogue.

The original long-session pause was a receiver anchor-expiry fault with healthy video buffering and fresh source audio. The candidate aligns maximum TV holdover with the existing three-second timing-link deadline while preserving the uncertainty ceiling. The underlying delivery/processing gap remains unidentified, and whole-movie reliability remains unverified. No additional timeout widening, audio-speed change or new drift controller was introduced during this audit.

The previously observed difference between the managed mpv build and the user's working external build remains a setup-dependent compatibility issue: software/null-output verification cannot establish physical WASAPI/HDMI continuity. Native renderer lifecycle, real cache/network scheduling, repeated remote operations and full-film behavior still need device validation when the user makes the hardware available again.
