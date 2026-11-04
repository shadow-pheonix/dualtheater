# Separate reliability development builds

Published 2.0.0 and the user's working artifacts are preserved. These are unreleased development branches with software checks; no new hardware or whole-movie acceptance is claimed. Use one Windows host at a time and retain the existing private profile/calibration. Matching-signature TV updates preserve app data. The unchanged phone 2.0.0 companion remains compatible and recommended for calibration.

## Reliability fixes

`fix/playback-reliability` builds Windows/TV **2.0.2-beta.1** (TV code 21). It implements the twelve reproduced audit defect records, retaining original media bytes, 1x compressed audio, existing active-playback clock/slew equations and calibrated start barriers.

- The Windows manual lead field follows external calibration changes while untouched, including saved decimal precision. Editing creates a manual draft; **Save and resynchronize** deliberately applies that draft. The active correction is also displayed in calibration status.
- Invalid seek, movie-path and offset requests report validation errors without pausing the current movie. They count as rejected operations, not playback errors.
- If a newly selected audio track cannot verify passthrough, the host attempts to restore and verify the previous selection at the saved position through the shared barrier. An explicit Pause/cancel prevents automatic resume. If restoration fails, both endpoints remain paused with an error.
- Socket cancellation closes each TV connection attempt, only one authenticated TV owns the host slot, and video-status freshness has a separate two-second bound even when baseline control pongs arrive. Short status delays remain tolerated.
- Optional disk logging uses a bounded worker queue. Disk failure or backpressure can lose diagnostic records but cannot pause playback or kill the supervisor. Sanitized diagnostics include logging error/drop/pending counts.
- A single source-sampler timeout can recover within the existing 750 ms last-good-source deadline. Persistent loss and genuine timeline discontinuity still fail safely; successful samples do not clear transport faults.
- TV status stays below a 48 KiB encoded budget. Optional codec/catalog descriptions may be truncated; critical timing and the selected subtitle remain. Other known client catalog limits still apply.

At normal media completion, the first endpoint reaching EOF no longer immediately stops the other. A bounded final-track phase validates that both positions are in the final ten seconds. Video-first completion lets the original audio finish. Audio-first completion uses an explicitly labelled, confidence-bounded projection of its last clock solely to finish video; it never restarts, resamples or changes the audio. The terminal deadline is three to ten seconds, including allowance for final status delivery. Early EOF, prolonged stalls, expired confidence/delivery, user pause/seek and connection errors retain their failure/epoch guards. Active movie synchronization is unchanged. [mpv's EOF property](https://github.com/mpv-player/mpv/blob/master/DOCS/man/input.rst) describes end of playback with `--keep-open`.

Fresh software validation: **168 host tests without skips**, including real mpv IPC/TrueHD tests forced to null output, plus two additional focused barrier/confidence controls; **46 TV JVM tests**, Android assembly/lint passed. Signed-lead EOF and failed-track rollback tests use real coordinator/timing sockets with simulated endpoints. The separate portable EXE passed terminal-only frozen-core verification. These checks do not establish panel/receiver latency, physical HDMI continuity or whole-film reliability; native GUI layout was not automated.

## Experimental child branch

`experiment/cache-timing-fallback` was derived directly from completed parent **8832ecf**. It builds Windows/TV **2.0.3-beta.1** (TV22) and includes the parent fixes plus:

- Cache scheduling rebases immediately on extractor opens, including same-URI forward/backward/small reopens. Far reopens retire the previous writer generation. The cache still stores original bytes with the existing budgets/throttling.
- Matching clients try UDP setup for up to **2.5 seconds**, then negotiate a **separate authenticated TCP timing connection** if no usable UDP reply arrived. A valid session ping can establish UDP if READY was lost. Wrong-token traffic cannot extend negotiation. Update Windows and TV together; older hosts retain their existing policy.
- No transport replacement while armed/playing or audio is running. Late UDP cannot replace TCP. Clock acquisition, source expiry, confidence, epochs, calibration and start/progress checks still apply. Established-link loss still faults; reconnecting cannot independently resume playback. No control-channel anchors were introduced.

**Final child software checks:** 176 host tests without skips, 52 TV JVM tests, Android assembly/lint, cache controller proof and portable terminal-only core verification passed. The old-parent cache negative control fails at the same-URI assertion. No hardware or GUI automation ran.

Cache scheduling and transport availability are software-testable; real cache contention, network reliability and physical lip-sync still require hardware acceptance. Compare this child separately against the reliability parent. Keep each EXE/APK pair in its own folder; the compatible phone 2.0.0 app is unchanged.

## Source operation

Use the existing [source CLI setup and commands](command-line.md) from the selected branch. Use the same private `--data-dir` to retain calibration; a separate CLI profile is not automatically imported into the portable desktop profile. Do not copy settings/logs into shared build folders. Update Windows and TV together when comparing the experimental transport capability. Keep a rollback copy of the prior EXE/APK and confirm the active lead and HDMI endpoint before future hardware tests.

## Completed comparison snapshots

Both branches are committed separately: [reliability parent](https://github.com/shadow-pheonix/dualtheater/tree/fix/playback-reliability) and its [experimental child](https://github.com/shadow-pheonix/dualtheater/tree/experiment/cache-timing-fallback). The parent's local bundle pins source `5585ad8` / code `1013584`; the child's pins source `70b9955` / code `a70c3d2`. Each contains its matching EXE, TV APK, sanitized source ZIP, operating instructions, provenance and checksums. They are local comparison artifacts, not GitHub release downloads. Published download links still point to stable 2.0.0. Parent/child APK certificates match; no phone update is needed. Preserve both complete folders and use the matching Windows/TV pair when hardware testing resumes.
