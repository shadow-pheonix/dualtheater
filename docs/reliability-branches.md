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

The user requested `experiment/cache-timing-fallback` only after the reliability branch is complete and checked. That child branch will add cache reopen/read-head scheduling and bounded session-authorized UDP-to-dedicated-TCP fallback. These changes are not part of the reliability build above. Its guide and results will be updated when implementation is complete; it must remain a descendant comparison build, not a replacement of main or published stable assets.

## Source operation

Use the existing [source CLI setup and commands](command-line.md) from the selected branch. Use the same private `--data-dir` to retain calibration; a separate CLI profile is not automatically imported into the portable desktop profile. Do not copy settings/logs into shared build folders. Update Windows and TV together when comparing the experimental transport capability. Keep a rollback copy of the prior EXE/APK and confirm the active lead and HDMI endpoint before future hardware tests.
