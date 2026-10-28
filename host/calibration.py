"""Paired phone calibration role. Playback always uses Coordinator.action."""
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import secrets
import statistics
import threading
import time

FIXTURE_ID = 'phone-v1'
CUE_FRAMES = (48, 115, 194, 252, 341, 422)
CUE_TIMES_MS = [frame * 1000 / 24 for frame in CUE_FRAMES]
FIXTURE_SHA256 = 'c0a3fa94e5c81611624b20499867e581c06cf9622cd625433c53d28b933bc214'
ACTIVE = ('preparing', 'playing', 'finishing')


def bounded(value, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError('Invalid calibration measurement')
    return float(value)


def summarize(pairs, base_lead):
    if not isinstance(pairs, list) or len(pairs) != len(CUE_FRAMES):
        raise ValueError('All six flash/beep pairs are required; retry the test')
    gaps, uncertainty = [], []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError('Invalid calibration pair')
        gaps.append(bounded(pair.get('gap_ms'), -2000, 2000))
        uncertainty.append(bounded(pair.get('uncertainty_ms'), 0, 100))
    gap = statistics.median(gaps)
    spread = max(abs(value - gap) for value in gaps)
    resolution = max(uncertainty)
    if spread > 40 or resolution > 40:
        raise ValueError('Capture variation is too large; steady the phone and retry')
    proposed = bounded(base_lead - gap, -2000, 2000)
    return {'pair_count': len(pairs), 'sound_minus_light_ms': round(gap, 2),
            'repeatability_ms': round(spread, 2), 'capture_uncertainty_ms': round(resolution, 2),
            'proposed_video_lead_ms': round(proposed, 2), 'absolute_accuracy': 'unvalidated'}


@dataclass
class Run:
    owner: object
    peer: object
    base_lead: float
    run_id: str = field(default_factory=lambda: secrets.token_hex(12))
    state: str = 'preparing'
    error: str = ''
    epoch: object = None
    result: object = None
    stop: threading.Event = field(default_factory=threading.Event)
    worker: object = None
    preparing_owned: bool = False


class CalibrationService:
    def __init__(self, app, fixture):
        self.app, self.fixture = app, Path(fixture)
        self.lock = threading.RLock()
        self.owner = None
        self.run = None

    def attach(self, owner):
        with self.lock:
            if self.owner is not None:
                raise ValueError('Another calibration phone is connected')
            self.owner = owner

    def detach(self, owner):
        with self.lock:
            if self.owner is owner:
                self.cancel(owner)
                self.owner = None

    def snapshot(self):
        with self.lock:
            run = self.run
            peer = self.app.peer
            return {'state': run.state if run else 'idle', 'run_id': run.run_id if run else None,
                    'error': run.error if run else '', 'result': run.result if run else None,
                    'video_lead_ms': self.app.offset_ms, 'tv_connected': bool(peer and not peer.closed),
                    'phone_connected': self.owner is not None, 'fixture_id': FIXTURE_ID,
                    'cue_times_ms': CUE_TIMES_MS, 'source': 'SDR / stereo TrueHD / no Atmos'}

    def _owned(self, owner, run_id=None):
        if self.owner is not owner:
            raise ValueError('Calibration connection changed')
        run = self.run
        if not run or run.owner is not owner or run.run_id != run_id:
            raise ValueError('Calibration run changed; start again')
        return run

    def start(self, owner):
        with self.lock:
            if self.owner is not owner:
                raise ValueError('Calibration connection changed')
            if self.run and (self.run.state in ACTIVE or self.run.worker.is_alive()):
                raise ValueError('Wait for the previous test to stop')
            peer = self.app.tv()
            run = Run(owner, peer, self.app.offset_ms)
            self.run = run
            run.worker = threading.Thread(target=self._measure, args=(run,), daemon=True,
                                          name='dualtheater-calibration')
            run.worker.start()
            return run.run_id

    def _owns_playback(self, run):
        return (self.app.peer is run.peer and not run.peer.closed and self.app.media == self.fixture
                and (run.epoch is None or self.app.epoch == run.epoch))

    def _same_playback(self, run):
        return self._owns_playback(run) and self.app.offset_ms == run.base_lead

    def _measure(self, run):
        try:
            # Validate the reference bytes before opening any media/audio device.
            if hashlib.sha256(self.fixture.read_bytes()).hexdigest() != FIXTURE_SHA256:
                raise ValueError('Calibration clip is missing or changed; use a complete preview build')
            with self.app.op_lock:
                if run.stop.is_set() or self.app.stop.is_set():
                    return
                run.preparing_owned = True
                run.base_lead = self.app.offset_ms
                if self.app.peer is not run.peer or run.peer.closed:
                    raise ValueError('TV connection changed; reconnect and retry')
                self.app.action({'action': 'load', 'path': str(self.fixture)})
                if run.stop.is_set():
                    return
                self.app.action({'action': 'play'})
                run.epoch = self.app.epoch
                run.preparing_owned = False
                with self.lock:
                    if not run.stop.is_set():
                        run.state = 'playing'
            deadline = time.monotonic() + 30
            while not run.stop.wait(.05):
                if self.app.stop.is_set():
                    return
                with self.app.op_lock:
                    if not self._same_playback(run) or self.app.state != 'playing':
                        raise ValueError('Playback changed during capture; retry once playback is stable')
                if time.monotonic() > deadline:
                    raise ValueError('No complete capture received; retry with the TV centered in the guide')
        except ValueError as error:
            with self.lock:
                run.error, run.state = str(error), 'error'
        except Exception:
            with self.lock:
                if not run.stop.is_set():
                    run.error, run.state = 'Playback preparation failed; check the Windows app', 'error'
        finally:
            run.preparing_owned = False
            with self.app.op_lock:
                if not self.app.stop.is_set() and self._owns_playback(run):
                    try:
                        self.app.action({'action': 'pause'})
                        run.epoch = self.app.epoch
                    except Exception:
                        run.error, run.state = 'Could not pause the test; check Windows', 'error'
            with self.lock:
                if run.state == 'finishing':
                    run.state = 'measured' if not run.error else 'error'
                elif run.state in ('preparing', 'playing'):
                    run.state = 'cancelled'

    def complete(self, owner, run_id, pairs):
        with self.app.op_lock:
            with self.lock:
                run = self._owned(owner, run_id)
                if run.state != 'playing' or not self._same_playback(run) or self.app.state != 'playing':
                    raise ValueError('Playback changed; start a new calibration test')
                run.result = summarize(pairs, run.base_lead)
                run.state = 'finishing'
                run.stop.set()

    def apply(self, owner, run_id):
        if not self.app.op_lock.acquire(blocking=False):
            raise ValueError('Windows is busy; try Apply again')
        try:
            with self.lock:
                run = self._owned(owner, run_id)
                if run.state != 'measured' or not self._same_playback(run) or self.app.state != 'paused':
                    raise ValueError('Playback or offset changed; start a new calibration test')
                self.app.action({'action': 'offset', 'milliseconds': run.result['proposed_video_lead_ms']})
                run.state = 'applied'
        finally:
            self.app.op_lock.release()

    def cancel(self, owner):
        with self.lock:
            run = self.run
            if run and run.owner is owner and run.state in ACTIVE:
                run.stop.set()
                # Only interrupt our own preparation; never another user's command.
                if run.state == 'preparing' and run.preparing_owned:
                    self.app.cancel.set()
                run.state = 'cancelled'

    def close(self):
        with self.lock:
            owner = self.owner
            if owner:
                self.cancel(owner)
                owner.close()
