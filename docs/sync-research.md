# Sync architecture research and implementation decision

Research date: 2026-10-28. Status: research decisions preserved; the selected experimental implementation is now described in [robust-sync.md](robust-sync.md). **No physical hardware accuracy result is established.**

The user requested a separate build based on `main`, followed by deeper research before implementing its sync changes. `feature/robust-sync` was created from `7debf90`. The existing diagnostics, reconnect protection and phone calibration support were cherry-picked as prerequisites. `main`, published assets and `feature/playback-reliability` remain unchanged. The implementation now uses its own Robust Sync version, desktop profile and TV application identity; see the build/comparison guide for current behavior.

## Decision

Use a **Windows-audio-referenced media clock inside the TV playback engine**, retaining Media3 hardware decoding, its frame-release scheduling and the SurfaceView path. Support that clock with accurately timestamped audio anchors, bounded clock estimation, explicit startup verification and coordinated recovery. Keep the original algorithm as an explicit comparison mode. Develop an improved video-speed servo as the compatibility alternative; do not run both controllers against one another.

This is a source-supported integration candidate, not an already proven Media3 configuration. Its promotion to the experimental build requires the renderer-clock and failure tests below. Clock or decoder incompatibility must be visible and lead to a coordinated pause/reconfiguration; never silently switch algorithms during a measurement run.

## Evidence and the most consequential findings

### The current main branch observes a scheduled release

`MainActivity.installFrameListener` records the frame PTS and Media3's release timestamp. Status is sent approximately every 100 ms. `Coordinator.monitor` maps the timestamp into host time, extrapolates the video position to the mpv query time, and drives a median-filtered speed servo. The deadband is 15 ms, video speed is bounded to 0.995–1.005, and sustained error above 180 ms can restart the shared barrier. This is already a closed loop, but the timestamps are not observations of panel light.

The important new detail is in the **exact Media3 1.9.0 source artifact**. `VideoFrameReleaseHelper.adjustReleaseTime` snaps to a target VSYNC and, when VSYNC data is available, subtracts 80% of a refresh period before returning the release timestamp. `MediaCodecVideoRenderer` passes that value to the metadata callback and the timed codec release. The lead is 13.33 ms at 60 Hz, 6.67 ms at 120 Hz, or 33.33 ms at 24 Hz. These are calculated scheduler leads, **not measurements of the user's TV delay**. Immediate releases and unavailable VSYNC data take other paths. The current extrapolation can therefore contain a refresh-dependent bias if it equates release with visible presentation. Simply adding a constant 13.33 ms everywhere would also be incorrect. [Pinned release helper](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/video/VideoFrameReleaseHelper.java), [pinned renderer](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/video/MediaCodecVideoRenderer.java).

Android documents SurfaceView presentation at the VSYNC at or after the codec timestamp, and warns that badly timed or excessively queued buffers affect presentation and responsiveness. This is why the design must retain refresh-aware scheduling and bounded output queues. [MediaCodec timed release](https://developer.android.com/reference/android/media/MediaCodec#releaseOutputBuffer(int,%20long)).

### Media3 has a suitable clock extension point

An enabled renderer can supply a `MediaClock`; Media3 uses it as the playback time source and allows at most one renderer clock. The pinned `ForwardingRenderer` can wrap the existing video renderer and intercept lifecycle/stream-offset operations while delegating decoding. This is less invasive than replacing extraction, hardware codec setup and HDR handling. [Renderer clock API](https://developer.android.com/reference/androidx/media3/exoplayer/Renderer#getMediaClock()), [pinned wrapper](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/ForwardingRenderer.java).

There are material integration requirements: `DefaultMediaClock` can use its standalone clock while the renderer is unready/ended, and prevents a backward clock transition. Renderer time includes stream/period offsets; it must not be confused with file-relative PTS. The implementation must handle enable, start, stop, reset, stream replacement, seek and EOS explicitly. A fake unselected audio renderer is unsuitable: it might never become an enabled clock source. [Pinned clock implementation](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/DefaultMediaClock.java), [renderer time offsets](https://github.com/androidx/media/blob/1.9.0/libraries/exoplayer/src/main/java/androidx/media3/exoplayer/BaseRenderer.java).

### mpv already consults the hardware audio clock

The pinned upstream runtime's `ao_wasapi.c` calls `IAudioClock::GetPosition`, converts the device counter using its frequency, and corrects for its correlated QPC timestamp. `playing_audio_pts` subtracts output delay from written audio PTS. Consequently, replacing mpv just to obtain an audio hardware clock is not justified. Microsoft also distinguishes a successful but less accurate `S_FALSE` clock reading. An endpoint timestamp does not expose downstream receiver DSP or acoustic propagation. [Runtime-commit WASAPI source](https://github.com/mpv-player/mpv/blob/41f6a64/audio/out/ao_wasapi.c), [runtime-commit audio position](https://github.com/mpv-player/mpv/blob/41f6a64/player/audio.c), [Microsoft correlated clock API](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock-getposition).

The application improvement is to attach a more precise measurement time to audio PTS, rather than using IPC arrival as playback time. A Lua sampler can bracket the PTS read with `mp.get_time()` and return both times in one response. That mpv clock has an arbitrary origin and must itself be correlated with host monotonic time. Bracketing is an estimate, not an atomic hardware snapshot. Queued IPC changes delivery age, not the recorded sample time; reject samples whose measurement span, age or continuity is unacceptable. Keep the current external mpv and strict TrueHD checks. [mpv scripting clock](https://mpv.io/manual/master/#lua-scripting), [pinned Lua clock implementation](https://github.com/mpv-player/mpv/blob/41f6a64/player/lua.c).

## Scrutinized candidates

| Candidate | Decision | Reason and remaining condition |
| --- | --- | --- |
| Remote audio `MediaClock` through the existing video renderer | **Primary experimental architecture** | Moves timing decisions to the TV playback thread and retains Media3 codec/HDR workarounds. Must prove lifecycle, renderer offsets, monotonicity and standalone-clock handoff. |
| Improved uncertainty-aware video-speed servo | **Compatibility alternative** | Smaller change with known integration. Use fresh unique samples, timestamp semantics, elapsed-time persistence and a frequency estimate. It still corrects an independent TV timeline through delayed commands. |
| Timestamped mpv audio samples plus separate clock/timeline models | **Required foundation** | Improves either architecture without replacing TrueHD output. Validate pinned runtime behavior and correlation overhead on Windows. |
| Mode-specific residual output-latency model, including receiver DSP | **Required physical-sync layer** | Keep it distinct from software clock lock. Use phone observations or explicitly identified device reports; leave unmeasured latency unknown. |
| MediaCodec rendered-frame feedback | **Selected as optional observation** | Stronger than intended release for detecting late presentation. Use the supplied event timestamp, not callback arrival. Never make the render path wait for callbacks. |
| Dedicated timing channel with latest-value delivery | **Selected protocol separation** | Keep transport barriers reliable; keep clock/anchor messages small, bounded and prioritized. UDP is a candidate for timing packets, not proof of greater accuracy by itself. |
| Full custom MediaCodec per-frame scheduler | **Defer** | Offers direct deadline control but duplicates renderer workarounds, frame pacing, EOS, seek and HDR integration. Revisit only if the MediaClock path fails specific tests. |
| Native WASAPI replacement or mpv fork | **Defer** | Existing backend already uses the device clock. A fork is justified only if measured PTS sampling limits remain after timestamped anchors. |
| Android MediaSync or tunneled A/V | **Reject for this implementation** | Their normal audio-clock integration is local to the TV. It does not directly use the Windows HDMI endpoint clock. |
| EGL display-present timestamps through a new GL pipeline | **Defer** | Useful graphics observability, but not a drop-in observer for MediaCodec's existing direct SurfaceView producer. Replacing the surface path adds HDR and device-compatibility risks. |
| Hardware PTP/network timestamps | **Future capability probe** | Can reduce network timestamp error with supporting OS/NICs; support and access on both actual endpoints are unknown. It cannot reveal panel or receiver delay. |
| HDMI automatic lip-sync/CEC latency querying | **Reject as a portable dependency** | Android CEC control is privileged and implementations vary. The project's two output paths also differ from a conventional common HDMI A/V source. |
| Audio stretching/resampling, silent TV audio as a fake master, or media transcoding | **Exclude** | Violates audio invariants or creates a clock unrelated to the real Windows audio endpoint. |

Rendered-frame callbacks can be delayed/batched; older Android releases can omit some callbacks. Install an observer through a supported codec/renderer integration without overwriting Media3's own listener. Correlate events with submitted-frame PTS, codec generation and epoch, retaining the stream offset valid when the frame was submitted. The observer must tolerate missing, duplicate, late and old-codec events. It remains surface-render evidence rather than a physical photon measurement. [Android callback contract](https://developer.android.com/reference/android/media/MediaCodec.OnFrameRenderedListener).

MediaSync exposes local audio/system/VSYNC source selection, but no public API for installing our remote audio clock; AOSP's native header also records external-clock support as unfinished. Tunneled on-demand video uses an AudioTrack clock/session on the TV. [MediaSync API](https://developer.android.com/reference/android/media/MediaSync), [AOSP MediaSync header](https://android.googlesource.com/platform/frameworks/av/+/refs/heads/main/media/libstagefright/include/media/stagefright/MediaSync.h), [tunneling architecture](https://source.android.com/docs/devices/tv/multimedia-tunneling).

EGL frame timestamps concern an EGL window surface. Android recommends SurfaceView for accurate video timing, HDR and full-resolution TV presentation. Retain that path. [EGL timestamp extension](https://registry.khronos.org/EGL/extensions/ANDROID/EGL_ANDROID_get_frame_timestamps.txt), [Media3 surface guidance](https://developer.android.com/media/media3/ui/surface). CEC APIs require system privileges. [Android CEC access](https://source.android.com/docs/devices/tv/hdmi-cec). Windows UDP socket timestamping and Linux hardware timestamps require capability/configuration checks. [Winsock timestamps](https://learn.microsoft.com/en-us/windows/win32/winsock/winsock-timestamping), [Linux timestamping](https://docs.kernel.org/networking/timestamping.html).

## Selected architecture in detail

### Separate the clock models

Maintain distinct mappings for host monotonic time, TV monotonic time, mpv's sample clock and audio media position. Never use wall-calendar time or Wi-Fi packet arrival as media position. A useful mathematical model is:

```text
host_time = alpha * tv_time + beta
audio_position(host_time) = audio_anchor + audio_rate * (host_time - host_anchor)
desired_video_position(tv_time) = audio_position(host_time(tv_time)) + saved_video_lead
```

Use relative integer timestamps around nearby anchors for numerical stability. Preserve authored track offsets and timestamp normalization; aligning the first audio packet with the first video packet would destroy intentional source timing. Period/renderer offsets are another explicit mapping, not a learned latency correction.

Use a robust affine estimator with low-delay sample selection, residual checks and conservative uncertainty growth. Start with offset-only acquisition until sufficient time span supports a rate estimate. Keep frequency bounds configurable and documented as assumptions until observed on hardware. Test robust weighted regression against an offset-only filter; use a more complex Kalman filter only if recorded noise and validation demonstrate a benefit.

DVB-CSS is particularly relevant: it separates reference-clock and media-timeline correlation and accounts for dispersion increasing as samples age. We should adopt those principles without adding an HbbTV dependency or claiming standards compliance. No estimator removes unknown path asymmetry; a narrow regression residual is not a tight absolute clock-error bound. [DVB-CSS specification, annex C](https://www.etsi.org/deliver/etsi_ts/103200_103299/10328602/01.03.01_60/ts_10328602v010301p.pdf), [NTP clock discipline](https://www.rfc-editor.org/rfc/rfc5905.html), [path asymmetry](https://www.rfc-editor.org/rfc/rfc8039.html).

### Feed audio anchors to a local TV clock

Publish bounded, sequenced audio anchors containing epoch, source-sample time, audio PTS, rate, uncertainty and play/pause validity. Acquire samples initially around 20–50 Hz, then select a measured cadence that meets the error budget without excessive IPC. These are prototype parameters, not a promised operating frequency.

The TV consumes immutable latest-value snapshots on its playback thread. Network readers never call player methods directly. Extrapolate only within a bounded age/uncertainty budget. Smooth phase and frequency separately; small updates must not move the clock backward. Larger changes, seeks and discontinuities use the coordinator's barrier. Preserve the existing video correction bounds until tests justify changing them. Report the active clock source and any handoff so a silent standalone-clock fallback cannot masquerade as successful remote locking.

Retain Media3's VSYNC and timed-codec scheduling. The host frame loop becomes an observer/watchdog in this mode rather than a competing speed controller. An improved-servo mode remains an explicit alternative, selected while stopped. Do not automatically change mode during a phone capture.

### Isolate timing traffic and verify actual progress

Reliable authenticated control continues to own pause/prepare/arm/commit/seek/recovery. Timing messages need their own bounded queue or channel, transmit-adjacent timestamps, sequence numbers, epoch checks and freshness limits. Start with a separate authenticated TCP timing connection on the existing control listener, with latest-value coalescing before writes and rejection of stale samples on receipt. Bound write stalls and sample age: TCP retransmission can still delay newer timing data, even when application queues are coalesced. A small paired UDP side channel is the shortlisted transport upgrade if loss tests show that TCP prevents the timing budget from being met. Losing one UDP anchor need not block newer anchors, but session authentication, replay rejection and capability negotiation are still required. Do not introduce a new default port before that comparison supports it.

Startup has separate prepared, armed, committed and progressing states. An arm acknowledgement only confirms scheduling. Confirm audio advancement and fresh progressing video frames under the same epoch after the deadline. Distinguish a paused preview frame from actual playback. Check decoder/buffer readiness and display-mode settling; do not suppress preparation frames in a way that deadlocks Media3's readiness checks. Keep all transport authority in the Windows coordinator.

Holdover uses the last valid frequency estimate only while its uncertainty remains acceptable. Expired confidence requests coordinated pause/reacquisition; it does not extrapolate forever. Network loss, endpoint changes, clock jumps, decoder reconfiguration, app backgrounding and changed epochs invalidate the relevant mappings. Recovery limits prevent repeated restart loops. Keep high-bitrate buffering failures distinct from clock error, preserving the heap-aware sample budget.

### Observe display timing honestly

Record scheduled codec release, optional codec-render event time, local callback receipt time, frame PTS, unique frame ID, display mode/refresh and codec generation separately. Classify immediate versus scheduled release. Never label any of these as measured panel light. Use actual refresh timing and renderer behavior to interpret release-to-render differences instead of hardcoding the 80% helper lead as physical compensation.

Request exact source frame rates where supported, retaining seamless behavior by default. A refresh-rate hint is not a guarantee that the display switched. Reacquire display-dependent estimates after actual mode changes; avoid permanently caching one SDR/HDR latency value. [Android frame-rate behavior](https://developer.android.com/media/optimize/performance/frame-rate).

### Account for soundbar/receiver processing explicitly

The user's additional requirement is accurate sync at the actual sound output, including soundbar/AV receiver processing. There are two different quantities to track: software clock alignment and the **remaining output-latency difference**. Neither can substitute for the other.

```text
audio path: file PTS -> mpv -> WASAPI/HDMI endpoint -> receiver decode/DSP -> speaker -> seat
video path: file PTS -> TV decoder/surface -> display processing/scanout -> light at seat

residual_audio_delay = delay after the audio timestamp's observation point, through sound at seat
residual_video_delay = delay after the video schedule's reference point, through light at seat
required_video_lead = residual_video_delay - residual_audio_delay
```

The correction includes the difference between both complete residual paths. With a hypothetical 100 ms residual audio delay and 30 ms residual video delay, the required video lead is **-70 ms**: schedule video later relative to the endpoint-referenced audio timeline. This is an arithmetic example, not a claimed receiver latency. TrueHD/Atmos data and audio rate remain unchanged; the coordinator and TV clock apply the signed video lead.

Do not double-count PC output buffering already reflected by mpv's driver-adjusted audio position. `IAudioClient::GetStreamLatency` is a stream-latency API, not a generic measurement of remote speaker output. A receiver's displayed manual delay is an additional setting, not proof of its total codec, DSP, speaker and automatic-lip-sync latency. [Windows stream-latency API](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-getstreamlatency). Receiver documentation explicitly distinguishes automatic lip-sync from manual adjustment and can store the latter per input. [Denon example](https://manuals.denon.com/avrx3800H/na/en/DRDZSYdwbwwnyp.php), [Yamaha example](https://manual.yamaha.com/av/18/rxa780/en-US/318230283.html).

The selected physical-sync layer therefore has these requirements:

- A profile records the measured residual lead and its provenance/uncertainty, associated with the sync algorithm, video output mode, audio format, receiver input/processing mode and measurement position. Unknown receiver fields remain unknown; HDMI endpoint enumeration does not certify Atmos reception or identify the active receiver DSP mode.
- Phone measurement at the seat observes the combined light/sound result, including receiver processing and sound travel. For a known synchronized reference, `new_lead = current_lead - measured_sound_minus_light`. It does not separately identify the receiver's absolute processing time; that separation is unnecessary for correcting the combined mismatch.
- Automatic clock lock operates without a phone. Accurate physical compensation requires a usable measurement or suitably validated device latency information. Never invent a receiver delay or label an unmeasured profile physically synchronized.
- Future receiver integrations may read processing mode or documented delay settings where an actual public API is available. Treat reports as contextual evidence unless their observation point and accuracy are established. No portable receiver latency API has been verified for the user's equipment, and no brand-specific dependency is selected for v1.
- Apply one net residual correction. Do not add a manual receiver delay on top of a phone result that already includes it. If a receiver setting is changed, remeasure; only use a known setting delta when its semantics and unchanged processing path have been established.
- Invalidate or flag a measured profile after an observed receiver input/format/DSP/lip-sync change, TV mode change or algorithm change. Prompt for the actual processing mode when it cannot be detected; do not silently carry stereo-reference compensation into an Atmos claim. For the initial comparison, keep receiver settings fixed and record them locally.
- Receiver lock/relock after start, seek or format change is a separate startup/recovery condition. Where device status is unavailable, a settling interval and stable audio clock provide only software readiness; they do not prove audible sound. Reject calibration runs with incomplete cues, inconsistent repeated gaps or mode changes.

No separate physical reference fixture is required. The existing phone test can measure the net delay in its SDR/stereo TrueHD mode. A valid multichannel/Atmos and HDR reference or other validated observation is still needed to establish compensation for those different processing modes. A clock-only implementation cannot make an unknown, changing receiver delay observable.

## Accuracy and acceptance

### LG S95TR investigation: phone-free receiver information

The user identified the soundbar as **LG S95TR** and explicitly requested accounting for its processing delay without the phone calibration app. Focus the first optional receiver adapter on this model while keeping the core timing architecture independent of receiver brand.

The model-specific investigation found an unofficial local TCP **9741** protocol implementation whose author reports testing on an S95TR. It reads product, input, EQ and processing settings, supports pushed state changes, and exposes `i_av_sync` in `SETTING_VIEW_INFO`. Its numeric control interprets that field as a **user-adjustable 0–300 ms audio delay in 10 ms steps**. This is evidence of a practical control/status integration, not an official LG API guarantee or a test on the user's firmware. Capability-detect fields and confirm units before using them. [Author's S95TR report](https://github.com/diogolccsilva/ha-lg-soundbar), [protocol source](https://github.com/diogolccsilva/ha-lg-soundbar/blob/main/custom_components/lg_soundbar_plus/protocol.py), [delay conversion](https://github.com/diogolccsilva/ha-lg-soundbar/blob/main/custom_components/lg_soundbar_plus/number.py).

No total decoder/DSP processing-latency measurement or speaker presentation timestamp was found in the reviewed interface. A 0 ms AV-sync setting must **not** become a 0 ms total processing-latency assumption. Knowing sound mode permits detecting changes, but supplies no verified numerical mode-to-latency mapping. The local protocol remains to be tested on the actual unit; no network connection to it was attempted.

LG's current India support manual (77 pages, downloaded from the product support page, dated April 2026 there) documents ThinQ control, sound effects and room calibration. It identifies built-in microphones for room calibration, but does not document exporting their sample timestamps or using them to measure this split Windows/TV playback path. Do not treat internal room calibration or WOW features as remote audio-output timestamp APIs. [LG support/manual download](https://www.lg.com/in/support/product-support/cs-S95TR.DMYSLLK/).

The second phone-free information source to investigate on Windows is **HDMI EDID latency metadata**, if present on the active HDMI chain. Windows provides a method to retrieve EDID blocks; the Linux HDMI helper demonstrates parsing separate audio/video latency fields. These references establish the mechanism, not S95TR field availability or accuracy. Missing/unknown data must stay unknown. Verify which device/route supplied the EDID, whether a repeater aggregated downstream latency, whether manual AV delay is already included, and whether the data represents the current TrueHD/Atmos processing mode. Its video latency may describe the HDMI video path, whereas DualTheater renders video through the TV app; do not apply an HDMI-chain A/V difference directly to that separate path. [Windows EDID retrieval](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmigetmonitorraweedidv1block-wmimonitordescriptormethods), [HDMI latency handling](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/drm_edid.c).

The selected S95TR implementation is a **read-only capability/status probe plus HDMI latency inspection**, not an invented automatic DSP compensation constant. Keep known added AV delay and any declared HDMI latency separate, with provenance and coverage. Only a verified usable latency value may contribute to an estimated signed video correction, and it must not be counted twice. If both sources fail to establish total processing latency, report that limitation plainly: status integration can detect configuration changes, but cannot establish accurate acoustic sync without another observation. User power/device access remains unavailable. The inspectors are now implemented in the experimental branch; actual S95TR/Windows HDMI validation is pending.

Aim to reduce software clock/timeline error to a few milliseconds before display quantization; **this is a design target, not a physical sync prediction or guaranteed device accuracy**. At 60 Hz one refresh period is 16.67 ms; at 24 Hz it is 41.67 ms. Independent display scanout, picture processing, receiver decoding/DSP and sound propagation remain outside the clock model. Report their combined residual as unknown until measured. Sum modeled uncertainty contributions conservatively unless independence has actually been established; never turn low jitter into a claim of low absolute error.

The required tests are:

1. Deterministic clock/timeline tests with known ground truth: independent oscillator drift, asymmetric delay, burst jitter, reorder/loss, queued messages, suspend/jumps, stale samples and arbitrary clock origins. Check coverage of reported uncertainty, not only average residual.
2. Media3 integration tests for renderer clock selection/fallback, period offsets, nonzero source PTS, B-frame ordering, reset/seek, paused preview, EOS, speed/clock updates and decoder replacement. Verify forward-only clock handoff and no stale-epoch frame use.
3. Windows tests with the actual pinned mpv: timestamped sample age/span, pause and start transitions, audio continuity, long-session slope and IPC contention. Null-output tests validate software only; WASAPI/TrueHD hardware tests remain required.
4. Fault injection through real host/TV protocol code: loss, late arm/commit, missing progress, underrun, reconnect and phone cancellation. Check that both devices pause/recover together and audio speed stays 1.0.
5. Hardware comparison with identical movie/track, TV processing, receiver mode, mpv build, network and seating position. Observe startup, seek/resume and a long high-bitrate passage. Compare timing distributions, recovery counts and visible cadence, not just a single drift number. Validate correction sign with an intentional known receiver delay change where supported, then restore the setting and repeat; verify the net correction is applied once and profiles do not cross modes silently.

Run the unchanged main build first. The experimental build should then provide explicit baseline and new-clock modes, independent zero-default offset storage and report fields identifying the mode. Baseline mode preserves the main timing algorithm, but shares branch diagnostics/reconnect/phone integration; it is not a byte-identical main build. Give this branch its own desktop data directory, TV application ID, label and version before packaging, preserving the prior preview installation as well.

Use the phone in **measure-only** mode before applying offsets: repeat the same clip in baseline and experimental modes, save the differences, and calibrate only afterwards. Repeat measurements can reveal changes larger than their uncertainty; they cannot automatically establish millisecond accuracy. Phone frame rate, exposure and timestamp bias limit interpretation. The current reference remains 720p SDR/stereo TrueHD without Atmos, so HDR/Atmos transfer and 4K peak load need separate validation. No separate physical reference fixture is required.

## Work completed for this research

Read the main/preview timing, transport, mpv, phone measurement and diagnostics code. Examined Media3 1.9.0 source and downloaded its official Maven source JAR; `DefaultMediaClock`, `MediaCodecVideoRenderer` and `VideoFrameReleaseHelper` matched the GitHub tag byte-for-byte. Also extracted the artifact's `ForwardingRenderer`. Inspected the actual mpv package's named runtime commit for WASAPI, audio PTS and Lua clock behavior. Reviewed the primary platform and standards references linked above.

At the research milestone no timing implementation was changed. The subsequent user-authorized implementation now includes the selected clock/servo modes, timing transport, rendered observer, comparison UI, independent offsets and receiver inspectors. See [current behavior and validation limits](robust-sync.md); historical research findings do not establish physical accuracy.
