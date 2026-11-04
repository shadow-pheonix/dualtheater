"""Focused desired-behavior regressions for the reproduced audit defects."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import socket
import tempfile
import threading
import time
import unittest

from host.desktop import DesktopWindow
from host.desktop_support import runtime_args
from host.end_tail import EndTail
from host.mpv import Mpv
from host.server import Coordinator, HostRuntime, TrackSelectionRejected, ns
from host.session_log import SessionLog
from host.timing import ClockEstimate
from test_core import FakeMpv
from test_robust_protocol import TimedMpv, TimingTV


class Ticks:
    def __init__(self, n=1): self.n, self.calls = n, 0
    def wait(self, delay): self.calls += 1; return self.calls > self.n
    def set(self): self.n = 0
    def is_set(self): return self.calls > self.n


@contextmanager
def playing(mode='audio-clock'):
    with tempfile.TemporaryDirectory() as directory:
        args = runtime_args('unused', 'wasapi/test', directory, ephemeral=True, sync_mode=mode)
        app = Coordinator(args, FakeMpv)
        app.mpv = FakeMpv(); app.mpv.loaded = True; app.mpv.position = 45000; app.mpv.pause(False)
        app.media = Path(directory)/'original.mkv'; app.media.write_bytes(b'test fixture')
        app.epoch = 7; app.state = 'playing'; app.duration_ms = 300000
        app.started_ns = app.last_correction = ns(); app.audio_running.set()
        calls = []
        def request(op, **kw):
            calls.append((op, kw)); app.peer.status['epoch'] = kw.get('epoch', app.epoch)
            if op in ('seek', 'load'):
                app.peer.status.update(state='ready', seek_pending=False, position_ms=kw.get('position_ms', 0))
            return {'epoch': app.epoch}
        now = ns()
        app.peer = SimpleNamespace(closed=False, seen=now, status_seen=now, request=request, timing_lock=threading.Lock(),
            clock=SimpleNamespace(best=lambda when: ClockEstimate(0, 1_000_000, when, uncertainty_ns=500_000)),
            status={'epoch':7, 'state':'ready', 'error':'', 'position_ms':45000, 'playing':True,
                'seek_pending':False, 'speed':1, 'sample_ns':now,
                'frame':{'epoch':7,'valid':True,'sequence':1,'position_ms':45000,'release_ns':now},
                'remote_clock':{'state':'locked','reads_recent':True,'renderer_error_ms':0}}, close=lambda *args:None)
        app.latest_anchor = dict(epoch=7, sequence=1, host_ns=now, position_ms=45000, rate=1, uncertainty_ms=.5)
        app.delivered_anchor = dict(app.latest_anchor)
        try: yield app, calls
        finally:
            app.peer = app.mpv = None; app.close()


class Holder:
    def __init__(self): self.value = None
    def set(self, value): self.value = value
    def get(self): return self.value
    def configure(self, **values): pass
    def status(self, value): pass
    def delete(self, *args): pass
    def insert(self, *args): pass
    def current(self, *args): pass
    def __setitem__(self, key, value): pass


class DesktopSafetyTests(unittest.TestCase):
    def window(self):
        window = SimpleNamespace(library_pane=Holder(), loaded_generation=None, require_reload=False,
            was_connected=False, dragging=False, offset_loaded=False, track_key=None, subtitle_key=None)
        for name in ('connection_text','pairing_text','error_text','playback_text','timeline','time_text',
            'offset','timing','diagnostic_text','diagnostic_preview','phone_calibration_text','audio_text',
            'track_box','subtitle_box','details'):
            setattr(window,name,Holder())
        return window

    def test_phone_update_refreshes_clean_field_preserves_precision_and_manual_draft(self):
        with playing() as (app, calls):
            app.peer = None
            window = self.window()
            DesktopWindow._status(window, app.snapshot())
            app.offset_ms = 137.25
            DesktopWindow._status(window, app.snapshot())
            self.assertEqual(window.offset.get(), '137.25')
            window.offset.set('150.125')
            app.offset_ms = 140.75
            DesktopWindow._status(window, app.snapshot())
            self.assertEqual(window.offset.get(), '150.125')
            app.offset_ms = 150.125
            DesktopWindow._status(window, app.snapshot())
            self.assertEqual(window.offset_synced_text, '150.125')

    def test_invalid_exact_seek_stays_in_ui(self):
        for entry in ('nan','inf','-1','999'):
            sent=[];error=Holder()
            window=SimpleNamespace(seek_seconds=SimpleNamespace(get=lambda:entry),status={'duration_ms':300000},
                error_text=error, action=lambda *args,**kw:sent.append(kw))
            DesktopWindow.seek_exact(window)
            self.assertFalse(sent);self.assertTrue(error.get())


class PlaybackSafetyTests(unittest.TestCase):
    def test_invalid_load_seek_offset_preserve_playing_epoch_and_media(self):
        with playing() as (app, calls):
            original=app.media
            unsupported=original.with_suffix('.txt');unsupported.touch()
            for body in ({'action':'load','path':str(original.with_name('missing.mkv'))},
                         {'action':'load','path':str(unsupported)},
                         {'action':'seek','seconds':float('nan')}, {'action':'seek','seconds':-1},
                         {'action':'seek','seconds':999}, {'action':'offset','milliseconds':2001},
                         {'action':'offset','milliseconds':float('nan')}):
                with self.assertRaises((ValueError,FileNotFoundError)):
                    app.action(body)
                self.assertEqual((app.state,app.epoch,app.media),('playing',7,original))
                self.assertFalse(app.mpv.paused);self.assertFalse(calls)

    def test_pause_attempts_both_endpoints_when_either_mpv_call_fails(self):
        for mode in ('baseline','servo','audio-clock'):
            for fault in ('position','pause'):
                with playing(mode) as (app,calls):
                    if fault=='position':
                        original=app.mpv.get
                        def get(name,default=None):
                            if name=='time-pos':raise OSError('IPC unavailable')
                            return original(name,default)
                        app.mpv.get=get
                    else:
                        app.mpv.pause=lambda *args: (_ for _ in ()).throw(OSError('IPC unavailable'))
                    app.fail('test fault')
                    self.assertEqual(app.state,'error')
                    self.assertTrue(any(op=='pause' for op,_ in calls))
                    self.assertFalse(app.audio_running.is_set())

    def test_stale_status_cannot_hide_behind_fresh_baseline_pongs(self):
        with playing('baseline') as (app,calls):
            app.peer.status_seen=ns()-2_100_000_000;app.peer.seen=ns()
            app.stop=Ticks();app.monitor()
            self.assertEqual(app.state,'error');self.assertIn('video status',app.error)

    def test_brief_status_delay_remains_tolerated(self):
        with playing('baseline') as (app,calls):
            app.peer.status_seen=ns()-1_300_000_000
            app.stop=Ticks();app.monitor()
            self.assertEqual(app.state,'playing',app.error)

    def test_transient_sampler_timeout_does_not_latch_but_discontinuity_does(self):
        for bad in ('timeout','discontinuity'):
            with playing() as (app,calls):
                base=ns()-100_000_000
                rows=[dict(host_ns=base,position_ms=45000,uncertainty_ms=.1),
                      TimeoutError('one timeout') if bad=='timeout' else dict(host_ns=base+30_000_000,position_ms=50000,uncertainty_ms=.1),
                      dict(host_ns=base+60_000_000,position_ms=45060,uncertainty_ms=.1)]
                iterator=iter(rows)
                def sample():
                    value=next(iterator)
                    if isinstance(value,Exception):raise value
                    return value
                app.mpv.timed_audio_sample=sample;app.stop=Ticks(3);app.sample_audio()
                if bad=='timeout':
                    self.assertEqual(app.timing_error,'');self.assertEqual(app.source_timing['state'],'fresh')
                else:self.assertTrue(app.timing_error)

    def test_sustained_sampler_timeouts_still_expire_original_source_deadline(self):
        with playing() as (app,calls):
            app.mpv.timed_audio_sample=lambda:(_ for _ in ()).throw(TimeoutError('timeout'))
            app.stop=Ticks(3);app.sample_audio()
            app.latest_anchor['host_ns']=ns()-800_000_000
            app.stop=Ticks();app.monitor()
            self.assertEqual(app.state,'error');self.assertIn('Source audio',app.error)

    def test_eof_waits_for_other_endpoint_and_keeps_timeout_and_early_end_guards(self):
        for first in ('video','audio'):
            with playing() as (app,calls):
                app.mpv.position=299000 if first=='video' else 300000
                app.mpv.start_ns=ns()
                app.peer.status.update(position_ms=300000 if first=='video' else 299000,
                    state='ended' if first=='video' else 'ready')
                app.latest_anchor.update(position_ms=app.mpv.position,host_ns=ns())
                original=app.mpv.get
                eof=[first=='audio']
                app.mpv.get=lambda name,default=None:eof[0] if name=='eof-reached' else original(name,default)
                app.stop=Ticks();app.monitor()
                self.assertEqual(app.state,'playing',app.error);self.assertIsNotNone(app.end_drain)
                eof[0]=True;app.peer.status['state']='ended';app.stop=Ticks();app.monitor()
                self.assertEqual(app.state,'ended');self.assertIsNone(app.end_drain)
        with playing() as (app,calls):
            app.peer.status['state']='ended';app.stop=Ticks();app.monitor()
            self.assertEqual(app.state,'error');self.assertIn('before',app.error)
        with playing() as (app,calls):
            app.mpv.position=299000;app.mpv.start_ns=ns();app.peer.status.update(state='ended',position_ms=300000)
            app.stop=Ticks();app.monitor();self.assertEqual(app.state,'playing',app.error)
            app.end_drain.deadline_ns=ns()-1;app.stop=Ticks();app.monitor()
            self.assertEqual(app.state,'error');self.assertIn('tail',app.error)

    def test_audio_eof_projection_is_bounded_and_does_not_resume_or_seek_audio(self):
        with playing() as (app,calls):
            now=ns();tail=EndTail(7,app.peer,now,300000,300000,299000,-1000)
            anchor=dict(app.latest_anchor,host_ns=now,position_ms=300000)
            tail.audio_ended(anchor,now);app.end_drain=tail
            app.mpv.timed_audio_sample=lambda: self.fail('Ended audio must not be queried as live clock')
            before=list(app.mpv.commands)
            app.stop=Ticks(2);app.sample_audio()
            self.assertEqual(app.latest_anchor['source'],'end_of_audio_tail')
            self.assertEqual(before,app.mpv.commands)
            with self.assertRaises(RuntimeError):tail.project(tail.deadline_ns+1,3)


class AudioChoiceMpv(FakeMpv):
    diagnostic=False
    verify=Mpv.verify
    def get(self,name,default=None):
        bad=str(self.aid)=='2'
        values={'aid':str(self.aid),'current-ao':'wasapi','audio-codec-name':'ac3' if bad else 'truehd',
            'audio-out-params':{'format':'float' if bad else 'spdif-truehd'},
            'current-tracks/audio':{'decoder':'pcm' if bad else 'spdif_truehd'}}
        return values[name] if name in values else super().get(name,default)


class TimedAudioChoice(AudioChoiceMpv):
    def timed_audio_sample(self): return self.audio_sample() | {'source':'mpv_source_clock'}
    def get(self,name,default=None):
        if name=='track-list':
            return [{'type':'audio','codec':codec,'id':ident,'selected':str(self.aid)==str(ident)}
                    for ident,codec in ((1,'truehd'),(2,'ac3'))]
        return super().get(name,default)


class RollbackTests(unittest.TestCase):
    def test_bad_track_restores_viable_previous_selection_through_barrier(self):
        with playing() as (app,calls):
            app.mpv=AudioChoiceMpv();app.mpv.loaded=True;app.mpv.position=45000;app.mpv.pause(False)
            app.track_catalog=[{'id':'1','supported':True},{'id':'2','supported':True}]
            resumed=[]
            def start(prepared=False):
                self.assertTrue(prepared);self.assertEqual(str(app.mpv.aid),'1')
                resumed.append(True);app.state='playing';app.mpv.pause(False)
            app.start=start
            with self.assertRaises(TrackSelectionRejected):app.action({'action':'track','aid':'2'})
            self.assertEqual(str(app.mpv.aid),'1');self.assertEqual(app.state,'playing')
            self.assertTrue(app.mpv.verify()['valid']);self.assertTrue(resumed)
            self.assertTrue(any(op=='seek' for op,_ in calls));self.assertEqual(app.error,'')

    def test_failed_rollback_keeps_both_paused_and_reports_failure(self):
        with playing() as (app,calls):
            app.mpv=AudioChoiceMpv();app.mpv.loaded=True;app.mpv.pause(False)
            app.track_catalog=[{'id':'2','supported':True}]
            app.mpv.verify=lambda:(_ for _ in ()).throw(RuntimeError('output failed'))
            with self.assertRaises(RuntimeError):app.action({'action':'track','aid':'2'})
            self.assertEqual(app.state,'error');self.assertTrue(app.mpv.paused)

    def test_user_cancel_during_track_change_cannot_be_overridden_by_rollback(self):
        with playing() as (app,calls):
            app.mpv=AudioChoiceMpv();app.mpv.loaded=True;app.mpv.pause(False)
            app.track_catalog=[{'id':'2','supported':True}]
            def prepare(position):app.cancel.set();raise RuntimeError('cancelled')
            app.prepare=prepare
            app.start=lambda **kw:self.fail('Cancellation must not resume playback')
            with self.assertRaises(RuntimeError):app.action({'action':'track','aid':'2'})
            self.assertEqual(str(app.mpv.aid),'1');self.assertTrue(app.mpv.paused)


class EndedAudio(TimedMpv):
    def get(self,name,default=None):
        if name=='eof-reached':return self.loaded and self.current()>=300000
        if name=='time-pos':return min(300000,self.current())/1000
        return super().get(name,default)
    def timed_audio_sample(self):
        if self.get('eof-reached'):
            return {'host_ns':ns(),'position_ms':None,'uncertainty_ms':.1}
        return super().timed_audio_sample()


class EndingTV(TimingTV):
    def send(self,message):
        if message.get('op')=='status' and message.get('position_ms',0)>=300000:
            message=dict(message,state='ended',playing=False)
        super().send(message)


class LiveBarrierSafetyTests(unittest.TestCase):
    def wait(self,predicate,app,seconds=8):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if predicate():return
            time.sleep(.01)
        self.fail('Condition timed out: '+app.state+' '+app.error)

    def test_both_signed_leads_drain_with_real_clock_sender_and_receiver(self):
        for lead in (500,-500):
            with tempfile.TemporaryDirectory() as directory:
                runtime=HostRuntime(runtime_args('unused','wasapi/test',directory,ephemeral=True),EndedAudio)
                runtime.start();app=runtime.app;tv=None
                try:
                    tv=EndingTV(runtime.args.control_port,app.pair_token)
                    self.wait(lambda:app.peer and app.peer.clock.best(ns()) is not None,app)
                    movie=Path(directory)/'fixture.mkv';movie.write_bytes(b'simulated')
                    app.action({'action':'offset','milliseconds':lead})
                    app.action({'action':'load','path':str(movie)})
                    app.action({'action':'seek','seconds':298.5,'play_after':False})
                    app.action({'action':'play'})
                    self.wait(lambda:app.end_drain is not None or app.state=='error',app)
                    self.assertEqual(app.state,'playing',app.error)
                    if lead<0:
                        self.wait(lambda:app.source_timing.get('state')=='terminal_tail' or app.state=='error',app)
                        self.assertEqual(app.source_timing['state'],'terminal_tail')
                    self.wait(lambda:app.state in ('ended','error'),app)
                    self.assertEqual(app.state,'ended',app.error)
                    self.assertEqual(app.diagnostics.recoveries,{'buffering':0,'drift':0})
                    self.assertFalse(any(cmd[:2]==('set_property','speed') for cmd in app.mpv.commands))
                finally:
                    if tv:tv.close()
                    runtime.close()

    def test_failed_audio_choice_restarts_previous_track_with_real_timing_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=HostRuntime(runtime_args('unused','wasapi/test',directory,ephemeral=True),TimedAudioChoice)
            runtime.start();app=runtime.app;tv=None
            try:
                tv=TimingTV(runtime.args.control_port,app.pair_token)
                self.wait(lambda:app.peer and app.peer.clock.best(ns()) is not None,app)
                movie=Path(directory)/'fixture.mkv';movie.write_bytes(b'simulated')
                app.action({'action':'offset','milliseconds':137.25})
                app.action({'action':'load','path':str(movie)})
                app.action({'action':'seek','seconds':45,'play_after':False})
                app.action({'action':'play'})
                with self.assertRaises(TrackSelectionRejected):app.action({'action':'track','aid':'2'})
                self.assertEqual(app.state,'playing',app.error)
                self.assertEqual(str(app.mpv.aid),'1');self.assertEqual(app.playback_lead_ms,137.25)
                self.assertTrue(app.audio_info['valid']);self.assertEqual(app.error,'')
                self.assertTrue(app.latest_anchor and app.latest_anchor['epoch']==app.epoch)
                self.assertTrue(tv.playing)
            finally:
                if tv:tv.close()
                runtime.close()

    def test_terminal_projection_retains_confidence_and_source_age_limits(self):
        now=ns();tail=EndTail(1,None,now,300000,300000,299000,-1000)
        anchor=dict(epoch=1,host_ns=now,position_ms=300000,rate=1,uncertainty_ms=9.9)
        tail.audio_ended(anchor,now)
        with self.assertRaises(RuntimeError):tail.project(now+200_000_000,1)
        with self.assertRaises(RuntimeError):tail.audio_ended(dict(anchor,host_ns=now-800_000_000),now)


class OptionalLoggingTests(unittest.TestCase):
    def test_disk_failure_is_optional_and_queue_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log=SessionLog(directory,capacity=4)
            with patch.object(Path,'open',side_effect=OSError('disk unavailable')):
                log.event('fixture');log.writerow([0]*8)
                deadline=time.monotonic()+1
                while not log.errors and time.monotonic()<deadline:time.sleep(.01)
                self.assertGreater(log.errors,0)
                for i in range(1000):log.event(str(i))
                self.assertLessEqual(log.queue.qsize(),4)
            log.close();self.assertTrue(log.closed)

    def test_slow_log_sink_cannot_block_playback_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            entered,release=threading.Event(),threading.Event()
            original=Path.open
            def opening(path,*args,**kw):
                entered.set();release.wait(2);return original(path,*args,**kw)
            log=SessionLog(directory,capacity=4)
            with patch.object(Path,'open',opening):
                log.event('fixture');self.assertTrue(entered.wait(1))
                before=time.monotonic()
                for i in range(100):log.writerow([i]*8)
                self.assertLess(time.monotonic()-before,.2)
                release.set();log.close()


class SlotOwnershipTests(unittest.TestCase):
    def test_concurrent_authenticated_handshakes_have_exactly_one_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=HostRuntime(runtime_args('unused','wasapi/test',directory,ephemeral=True,sync_mode='baseline'),FakeMpv)
            runtime.start();sockets=[]
            import host.server as server
            original=server.Peer
            def slow_peer(*args):time.sleep(.1);return original(*args)
            try:
                with patch.object(server,'Peer',slow_peer):
                    for i in range(2):
                        s=socket.create_connection(('127.0.0.1',runtime.args.control_port),timeout=3);sockets.append(s)
                        s.sendall((json.dumps({'op':'hello','version':1,'token':runtime.app.pair_token})+'\n').encode())
                    replies=[json.loads(s.makefile('rb').readline()) for s in sockets]
                    self.assertEqual(sum(row.get('op')=='welcome' for row in replies),1)
                    self.assertEqual(sum('already connected' in row.get('error','') for row in replies),1)
            finally:
                for s in sockets:s.close()
                runtime.close()
