# Playback diagnostics

Diagnostics are included in published **2.0.0** and the development branches. The historical 0.4.1 EXE/APK do not include them. No TV is required to run the host tests or export an empty session report.

The 2.0.2-beta.1 reliability branch writes optional event/CSV logs through a bounded worker queue. `logging.errors`, `logging.dropped` and `logging.pending` expose numeric write/backpressure observations without paths. A logging failure can omit records but does not stop playback supervision. Rejected seek/load/offset input counts as an operation failure while leaving the playback-error counter and current epoch unchanged. During a validated final audio-first tail, the source sampler reports `terminal_tail`; this explicitly denotes a bounded final-clock projection after audio playback ended, not another live HDMI timing observation.

## Native Windows app

The stable desktop is labeled **DualTheater** and uses `%LOCALAPPDATA%\DualTheater-RobustSync`. It does not automatically import or modify the base desktop's setup, pairing, calibration, logs or managed player cache. Choose mpv/HDMI and pair once in this profile. Only run one host at a time because the branch and base use the same default ports. The TV companion is **DualTheater TV**, with a separate application ID (`dev.dualtheater.tv.robustsync`), so it can coexist with the base TV app and its saved pairing settings. Use the matching 2.0 desktop and TV app. Source CLI users can select a separate private profile with `--data-dir`.

Start the TV connection, then open **Diagnostics**. This additional page shows:

- Whether TV telemetry is fresh, stale, waiting or disconnected.
- Buffered video time ahead of the current position.
- Last measured media-transfer rate and the age of that measurement.
- Reported dropped video frames for the current media load.
- Absolute drift at the 95th percentile, age of the last timing sample, buffer/drift recovery counts, coordinator errors and TV disconnects.

Missing measurements display a dash, including fields unavailable from an older TV companion. Stale, disconnected or wrong-epoch telemetry is excluded from current buffer/transfer/frame measurements. The transfer figure describes the last observed download interval, not a network speed test or a guarantee that remux peaks can be sustained. Frame-drop reporting can arrive in batches.

Click **Export sanitized report…**, choose a JSON destination and save. Export is available while the host is running, including when no TV has connected or after a TV disconnect. A failed save preserves an existing report at the chosen destination. The report preview shows the exported fields; export captures the latest session measurements.

## Optional browser controller

Open **Settings & help → Advanced browser controller**, or the source host's local controller at `http://localhost:8764`. The **Shareable diagnostics** section offers **Export sanitized report** and a preview. The authenticated `/api/diagnostics` endpoint uses the existing local Host/Origin and control-token restrictions. No additional public service or remote diagnostic upload is introduced.

## Report meaning and privacy

Schema version 1 reports the application version, known playback state, elapsed session time, numerical TV metrics, the last software TrueHD-verification result, timing summaries and fixed operation/recovery/error/disconnect counters. It builds from an explicit field allowlist; it does not export a redacted copy of the raw snapshot.

Reports exclude movie names, paths, network addresses, device identifiers, host/TV names, track titles, pairing codes, credentials, free-form errors and raw logs. Decoder/HDR capability lists and free-form format strings are not copied. Source video MIME is restricted to known values; unsupported values become `unknown`. No information is uploaded automatically. Existing private session logs remain local and must not be attached to public reports.

Counters cover the current Windows host lifetime and reset when **Disconnect** stops it or when the app restarts. Drift percentiles cover at most the latest 600 accepted samples, typically about one minute at the normal monitor rate. The sample age stays visible after pause/disconnect, so historical timing cannot be confused with a live measurement. The signed median uses the middle sorted sample; absolute p95 uses the nearest-rank percentile. Operation durations include preparation and scheduled-start waiting; recovery operations have separate counters. A TrueHD verification records mpv's software report and can describe a previous verification after a failure or disconnect.

API clock/frame measurements do not measure acoustic or panel latency. Reports do not prove physical lip-sync, active HDR mode or Atmos reception. Use the [hardware acceptance guide](hardware-test.md) when power and devices are available.

## Reconnecting after a host restart

The TV now resets playback epochs after each accepted connection welcome, clears old media and invalidates previous scheduled starts, seek completions and frame callbacks. This allows a restarted host to begin from epoch zero while stale commands remain rejected inside one connection. The host also pauses on an unexpected TV playback generation, including a fast reconnect that replaces the socket between monitor checks. Reconnect, reload the movie on Windows and then press Play. Automatic position restoration is not part of this feature.

## Software verification

Host tests cover bounded statistics, malformed/non-finite values, private-field exclusion, stale/old-epoch telemetry, atomic save failure, endpoint authentication, real coordinator instrumentation with a simulated TV, desktop-worker export and buffering-recovery counters. Android JVM tests cover lower epochs after restart, stale commands within a connection and callback invalidation when epoch numbers repeat. Software checks do not replace Windows packaged-app or TV/HDMI acceptance.

## Sync comparison fields

Robust Sync reports identify the selected algorithm, saved/active lead, offset provenance/context, software clock uncertainty/rate and remote-clock state. Audio-clock/servo drift uses media-timeline observations; baseline drift retains the original scheduled-release basis, so their numerical drift distributions have different semantics. Optional release-to-render samples describe codec/surface feedback, not panel light. Receiver fields expose only allowlisted settings and declared HDMI latencies; total S95TR processing latency remains unknown and no correction is inferred. See [comparison and receiver inspection](robust-sync.md).

Version 2.0 includes `sync.source_sampler`, containing the last source-sampling result, input/fitted uncertainty, observation age and consecutive rejected samples. These are allowlisted numbers and fixed state names; no raw source timestamps or free-form errors are exported. State meanings:

| State | Meaning |
| --- | --- |
| `fresh` | A source anchor passed confidence checks. |
| `sample_unavailable` | mpv did not supply a usable source position. |
| `input_uncertain` | The bracketed input sample could not enter the timing fit. |
| `fit_uncertain` | Fresh input arrived, but the current fitted timeline exceeded its confidence budget. |
| `failed` | Sampling or anchor transmission raised an error; check the private Windows log. |

Observation age distinguishes a recent result from one retained after playback stopped. A rejection does not refresh the last accepted anchor or disable its expiry guard. The current source model uses a recent phase window to avoid repeated rejections caused solely by old source-position settling; actual uncertain or discontinuous timing can still require a coordinated pause.

Version 2.0 separates local sampling from dedicated-stream transmission. `sync.anchor_delivery` reports a fixed state (`sending`, `fresh`, `stale`, `clock_uncertain` or `failed`), observation age and the last completed send duration. These fields do not assert receipt by the TV; compare its remote-clock state and anchor age too. `source_sampler.failed` now describes local sampling failures, while transmission failures appear under delivery. The source expiry remains 750 ms and delivery has a separate two-second deadline; neither polling nor delayed sends refresh an old source timestamp. Native loader/allocation/heap and [cache read-wait fields](read-ahead.md#diagnostics-and-verification) distinguish extraction starvation from empty disk coverage. None of these API observations detects every physical HDMI audio dropout.
