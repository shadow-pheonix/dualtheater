# Windows and TV playback audit

Last verified: **2026-11-04 (Asia/Calcutta)** against source `099dfe0` (playback implementation unchanged since `3c4945c`).

**Branch resolution:** the twelve reproduced defect records are software-resolved on `fix/playback-reliability` in `1013584` / **2.0.2-beta.1**. The original reproductions below describe the pre-fix `099dfe0` source. Device validation remains pending. AUD-009 and AUD-012 are deferred to the experimental child branch. This is not proof of 14 independent bugs: AUD-007 extends AUD-002, and AUD-012 is a compatibility limitation rather than a newly discovered regression.

Evidence and scope are recorded in the [verification observations](audit-verification-2026-11-04.json). Tests used actual coordinator/transport code with fake media endpoints and temporary loopback services. TV controller code used explicitly stubbed Android/cache APIs; Activity serialization methods were extracted unchanged. No existing host, TV, phone, GUI or physical playback was accessed. The original delivery/scheduling cause behind the long-session anchor-expiry pause remains unproven.

## Findings

| ID | Client | Priority | Finding | Verification | Resolution |
| --- | --- | --- | --- | --- | --- |
| AUD-001 | Windows | P2 | Windows can overwrite phone calibration with a stale manual field | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-002 | Windows / coordinator | P2 | Invalid seek input interrupts valid playback | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-003 | TV | P2 | A cancelled TV connection can still open and leak its socket | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-004 | Windows / TV | P2 | The first endpoint reaching EOF truncates the other track | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-005 | Windows / TV | P2 | Baseline control traffic can hide indefinitely stale TV video status | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-006 | Windows | P2 | Simultaneous TV handshakes can both claim the single-TV slot | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-007 | Windows | P2 | Rejected load and offset requests can stop the current movie | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-008 | Windows | P2 | Failed audio-track selection leaves no rollback to the working track | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-009 | TV | P3 | Same-URI seek can temporarily prefetch the previous byte position | Partially verified: scheduling only | Performance impact unmeasured |
| AUD-010 | Windows | P2 | One sampler exception latches an error after successful observations recover | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-011 | Windows / TV | P2 | mpv IPC failure can prevent the independent TV pause | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-012 | Windows / TV | P2 | UDP negotiation has no automatic TCP fallback when UDP is unreachable | Verified documented limitation | Compatibility decision pending |
| AUD-013 | TV / Windows | P2 | Unbounded status metadata can exceed the host control-frame limit | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |
| AUD-014 | Windows | P3 | Diagnostic write failure can interrupt playback and escape the monitor | Reproduced offline | Software-resolved: 1013584 / 2.0.2-beta.1 |

Keep IDs stable and update this tracker whenever reproductions, fixes or validation change. Verification is separate from resolution. Candidates with only a reproduced mechanism stay here until their claimed impact is established. A confirmed documented limitation must not be presented as a newly proved defect. Record fix commit/build and targeted regression results before marking a defect resolved; retain device-validation limits.

### AUD-009 — P3 — Partially verified cache scheduling candidate

- **Locations:** `android/app/src/main/java/dev/dualtheater/tv/ReadAheadCache.java:212–245`, `271–312`, `477–494`; `ReadAheadWindow.java:8–16`.
- **Trigger:** Seek substantially within the same movie URL; native preparation becomes READY before foreground consumption crosses the read-head notification threshold.
- **Behavior:** A new `TrackingDataSource.open()` calls `opening(uri)`, but `opening` does not reinitialize the read head for an unchanged URI. The worker resumes after READY using the old byte position until foreground reads signal a new head (normally at 256 KiB consumed). This can spend temporary network/cache I/O around the obsolete location while the newly sought position needs data.
- **Verification (2026-11-04):** The actual cache controller, tracking source and buffered reader were compiled with inert cache/Android APIs. Opening the same URI at byte 209,715,200 retained the previous head 1,310,720. After READY, the real worker requested prefetch at 1,310,720; consuming the 256 KiB notification threshold updated the head to 209,977,344.
- **Scope and limits:** Only the scheduling mechanism is reproduced. The fixture supplies empty cache coverage; real Media3 cache locks, I/O contention, throughput and playback-stall impact are unmeasured. Retain as partially verified performance candidate.
- **Correction:** Assess whether the new `DataSpec.position` can safely establish the seek/reopen read head without breaking coalesced reads, caching, or bounded cancellation. Regressions should instrument a large seek, short prefetch/READY window, cache holes/eviction and end-of-file ranges; measure foreground stalls before changing scheduling.

## Verified findings

Twelve defect behaviors are reproduced below. AUD-012 is included as a verified **documented limitation**, not a new defect. AUD-009 remains partially verified under Findings because its real performance impact has not been measured.

### AUD-001 — P2 — Windows can overwrite phone calibration with a stale manual field

- **Locations:** `host/desktop.py:514–516` and `368–377`.
- **Trigger:** Windows has already received its initial offset, then the phone applies a different calibration. Later click **Save and resynchronize** in Windows without first correcting the manual field.
- **Behavior:** `_status()` populates the manual field only once per connection. Later phone-applied changes update the actual coordinator and calibration status text, but leave that field unchanged. The Save button writes the stale field back as a manual offset, replacing the phone result and resynchronizing to it.
- **Verification (2026-11-04):** The actual desktop status/save methods were rerun with inert widget holders and an isolated coordinator. Applying a generic 137.25 ms phone correction left the manual field at 0; Save replaced the correction with 0 and source manual.
- **Scope and limits:** No Tk window, phone or physical output was used; only the actual desktop methods and offset action were exercised.
- **Correction:** distinguish an edited/manual draft from the last observed active offset. Refresh an untouched draft when an external calibration changes, preserve full saved precision, and make deliberate overrides clear. Test external Apply, user typing during updates and mode/reconnection changes.

### AUD-002 — P2 — Invalid seek input interrupts valid playback

- **Locations:** `host/desktop.py:345–351`, `host/server.py:1015–1022` and `1069–1072`.
- **Trigger:** enter `nan`, a negative seek time, or a time beyond the movie duration in Windows' exact-seek field.
- **Behavior:** `float()` accepts these inputs as numbers, so Windows submits them. The coordinator rejects them inside the same exception handler used for playback failures; `fail()` then pauses both devices, advances the epoch and changes state to `error`. A validation error should leave the current movie playing.
- **Verification (2026-11-04):** The actual exact-seek method submitted nan, -1 and 999 for a 300-second fake movie. Each was rejected by the real coordinator and produced an error state plus audio/TV pauses.
- **Scope and limits:** The GUI parser and coordinator were exercised with value holders and fake endpoints; no live movie was queried.
- **Correction:** validate finite/range values before the operation takes ownership of playback. Keep server-side validation too, with input rejection separated from failures after a seek begins. Regressions should assert unchanged epoch, position and audio/video state for rejected requests.

### AUD-003 — P2 — A cancelled TV connection can still open and leak its socket

- **Location:** `android/app/src/main/java/dev/dualtheater/tv/ControlClient.java:24–68`.
- **Trigger:** the Activity closes a client immediately after scheduling its connection thread, before that thread assigns `socket`.
- **Behavior:** `close()` marks the client closed while no socket exists. The reader thread subsequently creates/connects a socket and sends hello despite cancellation. Its receive loop is skipped, and there is no `finally` block closing the local socket. Subsequent `disconnect()` calls cannot clean it up because the closed-state compare-and-set has already succeeded.
- **Verification (2026-11-04):** The current ControlClient was recompiled and exercised in 100 immediate connect/close races. All 100 produced a hello and left the accepted socket open in this run.
- **Scope and limits:** Real Java sockets/threads and current controller code; minimal Build/JSON stubs. This does not establish Android scheduling incidence or a full authenticated host handshake.
- **Correction:** make socket adoption cancellation-safe, check closure before connecting/sending hello, and close each attempt's local socket unconditionally on exit. Test cancellation before thread startup, during connect, normal EOF and Activity retirement; listener notification should remain once-only.

### AUD-004 — P2 — The first endpoint reaching EOF truncates the other track

- **Location:** `host/server.py:1327–1330`.
- **Trigger:** TV video ends before audio, or audio ends before the remaining TV video. Different track lengths and signed calibration lead can cause this at an otherwise normal file ending.
- **Behavior:** the monitor uses `TV ended OR mpv EOF`, then pauses both immediately. It has no bounded end-of-track drain phase, so remaining original content can be cut off.
- **Verification (2026-11-04):** The current monitor paused both endpoints for either video-first or audio-first EOF, while a neither-ended control kept playing. The permitted positive 1,000 ms lead fixture ended video at 300 seconds with audio still at 299 seconds and eof-reached false; audio was paused with one second remaining.
- **Scope and limits:** Actual monitor with fake endpoints and signed-lead state; panel and HDMI drain timing were not measured.
- **Correction:** explicitly handle the final tail, preserving 1x audio and the calibration schedule, with a bounded completion deadline. Merely changing `or` to `and` is insufficient because ordinary progress/clock watchdogs would still treat the already-ended track as stalled. Test both track-order endings, positive/negative lead and genuine mid-file stalls.

### AUD-005 — P2 — Baseline control traffic can hide indefinitely stale TV video status

- **Locations:** `host/server.py:405–410`, `1303–1338`, `1357–1394`, `1519–1546`; `android/app/src/main/java/dev/dualtheater/tv/ControlClient.java:46–67`.
- **Trigger:** baseline-mode TV status stops updating while its independent control reader continues answering host pings.
- **Behavior:** `tv()` checks the timestamp of **any** received control message, not the last status report. The monitor intentionally skips frame/timeline checks on status older than 500 ms, but has no independent maximum *status-age* deadline. Control pongs can thus keep the peer alive while Windows mpv audio continues with no fresh evidence of TV video progress. The receiver's separate source/timing checks may stop the session in some modes; this does not establish a video-status bound.
- **Verification (2026-11-04):** With real coordinator/control sockets and synthetic status suppression, baseline remained playing after 3.315 seconds of stale status while control pongs remained fresh (477 ms) and audio advanced 3.3 seconds. Servo and audio-clock negative controls stopped on TV telemetry is stale after about two seconds, because their ordinary control traffic also stopped.
- **Scope and limits:** Verified for baseline with live pongs. The broad claim is narrowed: ordinary status loss in the tested servo/audio-clock path is already bounded. A physically frozen TV/main thread was not induced.
- **Correction:** Preserve short status-delay tolerance, but set an explicit bounded stale-video-telemetry deadline separate from control socket liveness. Test brief delays, prolonged status silence with live pongs, and genuinely stale/dead connections in all three sync modes.

### AUD-006 — P2 — Simultaneous TV handshakes can both claim the single-TV slot

- **Location:** `host/server.py:1503–1524` (`ControlHandler.handle`).
- **Trigger:** Two authenticated TV control connections reach the availability check at nearly the same time.
- **Behavior:** `if app.peer and not app.peer.closed` and the subsequent `app.peer = peer` run in separate server threads without an atomic reservation. Both connections can pass the check, receive a welcome, and remain alive even though the coordinator points at only one of them. Status/ACKs, controls, and session-bound timing can then disagree about which TV owns playback.
- **Verification (2026-11-04):** Two real authenticated control handlers were scheduled together immediately after the unprotected availability check by a barrier in peer construction. Both received welcome and remained live, while only one peer was the coordinator owner.
- **Scope and limits:** This deterministically exposes a permitted thread interleaving; natural race frequency and device-level consequences were not measured.
- **Correction:** Reserve and release the sole TV slot under a short dedicated lock and reject the losing connection before sending welcome. Test racing handshakes, disconnect during takeover attempts, and reconnection after an abandoned session.

### AUD-007 — P2 — Rejected load and offset requests can stop the current movie

- **Locations:** `host/server.py:496–503`, `941–1073` (especially `997–1003`, `1014–1031`, `1069–1072`).
- **Trigger:** During valid playback, submit a non-existent/unsupported movie path through the local load command or a non-finite/out-of-range offset through the controller.
- **Behavior:** Input validation may reject the request **before** the new load/offset takes ownership of playback, but the shared `Coordinator.action` exception handler still invokes `fail()`, which pauses both devices and advances the epoch. This is a broader instance of the previously reproduced invalid-seek bug, not a new independent root cause.
- **Verification (2026-11-04):** Five real coordinator actions (missing path, unsupported existing file, NaN offset, offset above/below range) preserved the original media but moved playback to error, advanced the epoch and paused both endpoints. Rejecting an unknown audio track, which is validated before ownership, preserved playing state and epoch.
- **Scope and limits:** Extends AUD-002 rather than adding an independent root cause. Media and endpoint fixtures were synthetic.
- **Correction:** Validate requests before entering the playback-failure boundary. Keep coordinated failure handling for errors *after* an operation has begun mutating media/playback. Test that invalid load, seek and offset requests preserve active epoch, playing state, audio, video and current media.

### AUD-008 — P2 — Failed audio-track selection leaves no rollback to the working track

- **Locations:** `host/server.py:539–585`, `1021–1028`, `1043–1058`; `host/mpv.py:227–252`.
- **Trigger:** Choose an audio track whose codec is cataloged as supported, but whose selected track cannot be verified as compressed passthrough on the active WASAPI/HDMI endpoint.
- **Behavior:** The host pauses, changes mpv's `aid`, seeks/prepares, then runs `mpv.verify()`. Codec-level `supported` is not an endpoint-specific guarantee. On failure, the coordinator goes to `error` without restoring the prior `aid` and playback position. A formerly playable movie can remain stranded on the failed selection.
- **Verification (2026-11-04):** The real track action and preparation path selected a catalog-supported AC-3 fixture that the actual Mpv.verify method rejected as PCM output. The coordinator entered error and left aid=2 selected. Explicitly restoring aid=1 still verified TrueHD passthrough, proving that the prior choice was viable in the fixture.
- **Scope and limits:** The endpoint response was simulated; no real HDMI codec failure was induced. The test verifies rollback omission, not hardware codec support.
- **Correction:** Save old `aid`, play state and position; verify the new selection; if it cannot be used, restore and verify the previous track through the existing coordination barrier. Distinguish a recoverable track-choice rejection from a genuine device/output failure. Add successful/failed switch regressions.

### AUD-010 — P2 — One sampler exception latches an error after successful observations recover

- **Locations:** `host/server.py:857–898` (`sample_audio`), `766–777` (`start`), `1303–1314` (`monitor`).
- **Trigger:** A transient `mpv.timed_audio_sample()` IPC timeout/error occurs while a movie is playing; subsequent source samples may succeed normally.
- **Behavior:** The sampler assigns `self.timing_error = str(e)` on an exception but does not clear that field on subsequent successful samples. The monitor treats any nonempty `timing_error` as a fatal error and calls `fail()`, stopping coordinated playback. `start()` clears `timing_error` at a new playback start, but that does not prevent a live, recoverable sampler exception from latching an interruption. Some errors, such as a genuine timeline discontinuity or persistent IPC failure, must still stop playback.
- **Verification (2026-11-04):** The real source sampler accepted a good sample, received one injected timeout and then accepted a fresh later sample. Its state returned to fresh but timing_error stayed set; the real monitor still entered error. A healthy sequence kept playing; persistent timeouts and a genuine timeline discontinuity still failed.
- **Scope and limits:** The exception is injected within the freshness budget, not a measured physical IPC timeout. Source failure classification and actual driver behavior remain separate.
- **Correction/regression:** Separate transient sampler failure counters/last-good-sample age from persistent faults. Define a bounded freshness/grace policy that can recover on successful observations while still failing safely if the source clock becomes stale or discontinuous. Inject one failed `timed_audio_sample` followed by fresh samples and separately test sustained failure and a real timeline discontinuity.

### AUD-011 — P2 — mpv IPC failure can prevent the independent TV pause

- **Locations:** `host/server.py:412–452` (`pause_both` and `fail`), `host/mpv.py:150–178` (command/property errors).
- **Trigger:** mpv's IPC pipe disconnects or a property query/pause command raises while Windows attempts to stop both players during active playback.
- **Behavior:** `pause_both()` first samples mpv's `time-pos` and calls `mpv.pause()`. Only afterward does it send the TV `pause` request. If either mpv operation raises, the TV request is skipped. The `fail()` exception fallback attempts another mpv pause, but does not independently send the TV a pause. In baseline mode, TV video may continue until a separate watchdog or connection failure; audio-clock modes may later freeze on external-clock expiry, but not because the coordinated pause succeeded.
- **Verification (2026-11-04):** In baseline, servo and audio-clock modes, injecting an mpv time-pos error or pause-command error caused the real fail/pause path to omit the TV pause. In all three no-IPC-failure controls, TV pause was attempted.
- **Scope and limits:** The TV endpoint was independently healthy and synthetic. The result verifies exception short-circuiting, not any physical device failure.
- **Correction/regression:** Independently attempt both stop/pause commands and gather their errors without skipping either device, while preserving safe epoch and state transitions. Inject failures in both `get('time-pos')` and `pause()`, and verify that a TV pause is still attempted in each sync mode.

### AUD-012 — documented limitation — UDP negotiation has no automatic TCP fallback when UDP is unreachable

- **Locations:** `host/server.py:1510–1525` and `1903–1920`; `android/app/src/main/java/dev/dualtheater/tv/MainActivity.java:965–983`; `TimingClient.java:20–22`, `74–130`.
- **Trigger:** Host-side UDP timing socket setup succeeds and UDP is advertised, but the TV-to-host UDP path is filtered/unreachable while TCP control, timing and media could otherwise work.
- **Behavior:** The TV chooses `connectDatagrams()` exclusively when `timing_transport` is `udp`. Its handshake retry loop continues using UDP indefinitely if no `timing_ready` arrives; there is no switch to the already-implemented authenticated TCP timing path. In `servo` or `audio-clock` mode this can block timing readiness and therefore movie load/start.
- **Verification (2026-11-04):** The current TimingClient sent 34 UDP hellos to a loopback black-hole endpoint over nine seconds, reached no ready state and made zero TCP connection attempts. An explicit authenticated-token TCP timing connection to the same fixture became ready.
- **Scope and limits:** Behavior confirmed, but this is the existing documented fail-closed transport limitation in datagram-timing.md, not proof of a regression. Treat fallback as a compatibility/design enhancement; no authorization checks were weakened.
- **Correction/regression:** After a bounded UDP negotiation failure, transparently try the session-bound TCP timing connection without weakening token/session authorization, and define safe transport handover on recovery. Test blocked outbound/inbound UDP with TCP available, normal UDP operation, and reconnect/epoch changes.

### AUD-013 — P2 — Unbounded status metadata can exceed the host control-frame limit

- **Locations:** `android/app/src/main/java/dev/dualtheater/tv/MainActivity.java:734–752`, `1177–1224`, `1235–1250`; `ControlClient.java:41–65`; `host/server.py:1527–1530`.
- **Trigger:** The loaded media exposes an unusually large number of subtitle tracks or long subtitle metadata, or the TV reports a large codec-capability catalog.
- **Behavior:** The TV serializes all discovered subtitle entries and decoder capabilities into every recurring `status` JSON message (the telemetry callback runs roughly every 100 ms), without bounding the encoded byte count. The host reads at most 65,537 bytes and terminates the control session when an individual frame exceeds 65,536 bytes. Such a catalog can cause repeated disconnections rather than merely truncating UI metadata. As an illustration, 250 subtitle labels of 160 bytes contribute about 40 KiB *before* JSON keys, other subtitle fields, decoder catalog and normal status telemetry. Actual overflow depends on the source's metadata and the device.
- **Verification (2026-11-04):** The current TV status and subtitle-serialization method bodies were executed with inert device fields and a Gson-backed JSON API substitute. A 250-track fixture with 160-byte ASCII labels generated 70,940 JSON bytes; the actual host control handler closed it as oversized_frame. A 65,535-byte JSON payload plus newline was accepted; 65,536 payload bytes plus newline was rejected.
- **Scope and limits:** The Android Activity/player were not launched; the method bodies were extracted unchanged. Native JSON formatting and real catalogs can differ. The receiver limit is 65,536 wire bytes including newline, so its maximum JSON payload is 65,535 bytes.
- **Correction/regression:** Set a strict encoded size bound on TV status; send only bounded critical telemetry frequently and transfer track/codec catalogs in capped or paginated messages. Test 250+ tracks with long labels, large decoder reports and simultaneous playback status/ACK traffic. Confirm that playback and control liveness continue when optional metadata must be truncated.

### AUD-014 — P3 — Diagnostic write failure can interrupt playback and escape the monitor

- **Locations:** `host/server.py:242–248` (`log`), `430–452` (`fail`), `1303–1440` (`monitor`, especially `1427–1438`).
- **Trigger:** Timing CSV flush/write or event-log append raises due to full disk, revoked permissions, failed storage, or an analogous filesystem error while A/V playback is otherwise healthy.
- **Behavior:** The playback monitor writes and flushes diagnostic CSV data inside the same error boundary as sync enforcement. Any I/O exception invokes `fail()` and pauses the movie. `fail()` itself calls `log()` without an independent I/O safeguard, so another filesystem failure can escape the monitor's exception handler and terminate that thread, removing subsequent playback supervision.
- **Verification (2026-11-04):** Injected CSV write and flush errors made the real monitor pause healthy fake playback. Combining CSV failure with events.log append failure let OSError escape monitor(). A separate real monitor thread exited on that double failure while its stop event remained unset. A healthy diagnostic-I/O control remained playing.
- **Scope and limits:** Filesystem failure was injected; no disk was filled or permissions changed. Worker termination was verified on an isolated real thread, not inferred from physical-device logs.
- **Correction/regression:** Make telemetry/event logging best-effort and bounded independently of playback, with a diagnostic failure flag/counter rather than mandatory coordination failure. Inject CSV write/flush and event-log errors and verify healthy playback continues, while the monitor remains alive and still fails safely on genuine clock or video faults.

## Resolved

Software resolution commit **`1013584`**, branch **`fix/playback-reliability`**, build **2.0.2-beta.1**. Validation: 168 full host tests without skips plus two additional focused barrier/confidence controls; 46 TV JVM tests, Android assembly/lint and portable terminal-only core verification passed. No physical device/whole-movie acceptance is implied. The [branch guide](reliability-branches.md) describes behavior, bounds and comparison setup.

| ID | Passing regression coverage |
| --- | --- |
| AUD-001 | DesktopSafetyTests.test_phone_update_refreshes_clean_field_preserves_precision_and_manual_draft |
| AUD-002 | PlaybackSafetyTests.test_invalid_load_seek_offset_preserve_playing_epoch_and_media |
| AUD-003 | ControlClientTest (cancellation before adoption, during connect, and EOF) |
| AUD-004 | LiveBarrierSafetyTests.test_both_signed_leads_drain_with_real_clock_sender_and_receiver; EOF early-end/deadline/confidence controls |
| AUD-005 | PlaybackSafetyTests.test_stale_status_cannot_hide_behind_fresh_baseline_pongs; brief-delay control |
| AUD-006 | SlotOwnershipTests.test_concurrent_authenticated_handshakes_have_exactly_one_owner |
| AUD-007 | PlaybackSafetyTests.test_invalid_load_seek_offset_preserve_playing_epoch_and_media; diagnostic rejection/state regression |
| AUD-008 | RollbackTests; LiveBarrierSafetyTests.test_failed_audio_choice_restarts_previous_track_with_real_timing_barrier |
| AUD-010 | PlaybackSafetyTests timeout/discontinuity and sustained-source-expiry cases |
| AUD-011 | PlaybackSafetyTests.test_pause_attempts_both_endpoints_when_either_mpv_call_fails (all modes) |
| AUD-013 | StatusPayloadTest (bounded Unicode catalogs, selected track, critical timing/positions) |
| AUD-014 | OptionalLoggingTests (disk failure and bounded queue/backpressure) |

## Yet to be resolved









- [ ] **AUD-009 (partially verified mechanism):** Measure real foreground/cache contention and playback impact before changing the reproduced old-head prefetch scheduling.



- [ ] **AUD-012 (documented limitation):** Decide whether to retain the documented fail-closed UDP policy or add bounded authenticated TCP fallback; availability behavior is verified, not a new regression.



**Validation boundaries:** the fresh verification used isolated fault injection, permissive scheduling barriers for the handshake race, synthetic catalogs and API stubs. It did not validate physical HDR/Atmos, real HDMI driver behavior, panel latency, actual Android scheduling incidence or whole-movie reliability. The new hardware endurance run remained interrupted when the user turned the TV off. Earlier user-reported continuous audio/in-sync dialogue is historical evidence, not a fresh hardware result.

The three-second holdover candidate remains separate from these checks. Its previously recorded 41 TV JVM tests, Android assembly/lint, 11 focused host diagnostic tests and portable core verification were not rerun as part of this verification; do not count those old results as new runs. Active-playback timing/slew equations, audio rate and encoded media remain unchanged. The new bounded final-track phase applies only after a validated near-end EOF; see the branch guide.
