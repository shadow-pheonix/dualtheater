"""Native Windows desktop navigation over the existing playback coordinator."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .desktop_support import (DesktopService, Settings, VERSION, default_data_dir,
                              find_mpv, format_time, list_devices, runtime_args)
from .server import HostRuntime
from .player_download import DOWNLOAD_PAGE
from .diagnostics import save_report


class DesktopWindow:
    def __init__(self, root, directory=None, auto_start=True):
        self.root = root
        self.directory = Path(directory) if directory else default_data_dir()
        self.settings = Settings(self.directory)
        self.service = DesktopService(self.directory)
        self.devices = []
        self.track_ids = []
        self.track_key = None
        self.status = {}
        self.running = self.busy = self.closing = self.dragging = False
        self.downloading = False
        self.auto_start = auto_start
        self.was_connected = False
        self.require_reload = True
        self.offset_loaded = False
        self.error_text = tk.StringVar(value=self.settings.warning)
        self.mpv_path = tk.StringVar(value=find_mpv(self.settings.values.get('mpv', ''),data_dir=self.directory))
        self.mode_labels = {'Audio clock (experimental)': 'audio-clock',
                            'Video servo (experimental)': 'servo', 'Original timing (baseline)': 'baseline'}
        saved_mode = self.settings.values.get('sync_mode', 'audio-clock')
        self.sync_mode = tk.StringVar(value=next((k for k,v in self.mode_labels.items() if v == saved_mode), 'Audio clock (experimental)'))
        self.receiver_address = tk.StringVar()
        self.receiver_text = tk.StringVar(value='Receiver processing delay: unmeasured. Inspection does not apply a correction.')
        self.movie_path = tk.StringVar()
        self.audio_device = tk.StringVar()
        self.connection_text = tk.StringVar(value='Choose your HDMI audio output to begin.')
        self.pairing_text = tk.StringVar(value='Not connected')
        self.playback_text = tk.StringVar(value='Connect your TV, then choose a movie.')
        self.time_text = tk.StringVar(value='0:00 / 0:00')
        self.offset = tk.StringVar(value='0')
        self.seek_seconds = tk.StringVar(value='0')
        self.audio_text = tk.StringVar(value='No movie loaded.')
        self.diagnostic_text = tk.StringVar(value='Start the TV connection to collect session diagnostics.')
        self.export_notice = tk.StringVar()
        self.root.title(f'DualTheater Robust Sync {VERSION} — Experimental beta')
        self.root.geometry('930x790')
        self.root.minsize(800, 610)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        assets = Path(__file__).resolve().parent.parent / 'assets'
        if (assets / 'dualtheater.ico').is_file():
            self.root.iconbitmap(str(assets / 'dualtheater.ico'))
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('TButton', padding=(12, 7))
        style.configure('Title.TLabel', font=('Segoe UI', 22, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 13, 'bold'))
        style.configure('Code.TLabel', font=('Consolas', 25, 'bold'))
        style.configure('Navigate.TButton', font=('Segoe UI', 9, 'bold'), padding=(16, 7))
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        heading = ttk.Frame(outer)
        heading.pack(fill='x')
        if (assets / 'dualtheater.png').is_file():
            self.brand_image = tk.PhotoImage(file=str(assets / 'dualtheater.png')).subsample(5, 5)
            ttk.Label(heading, image=self.brand_image).pack(side='left', padx=(0, 12))
        ttk.Label(heading, text='DualTheater', style='Title.TLabel').pack(side='left')
        ttk.Label(outer, text='Native TV picture + HDMI TrueHD audio · Experimental, still testing').pack(anchor='w', pady=(0, 14))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.connect = ttk.Frame(self.tabs, padding=18)
        self.player = ttk.Frame(self.tabs, padding=18)
        self.diagnostics_page = ttk.Frame(self.tabs, padding=18)
        self.options = ttk.Frame(self.tabs, padding=18)
        for frame, title in ((self.connect, '1  Connect'), (self.player, '2  Player'),
                             (self.diagnostics_page, 'Diagnostics'), (self.options, 'Settings & help')):
            self.tabs.add(frame, text=title)
        self._connect_page()
        self._player_page()
        self._diagnostics_page()
        self._settings_page()
        ttk.Label(outer, textvariable=self.error_text, foreground='#a82020', wraplength=850).pack(anchor='w', pady=(10, 0))
        self.activity = ttk.Progressbar(outer, mode='indeterminate')
        self.activity.pack(fill='x', pady=(7, 0))
        self._update_controls()
        self.root.after(120, self._events)
        if self.mpv_path.get():
            self.root.after(250, self.refresh_devices)

    @staticmethod
    def note(parent, text):
        label = ttk.Label(parent, text=text, wraplength=790, justify='left')
        label.pack(anchor='w', pady=(3, 10))
        return label

    def _connect_page(self):
        ttk.Label(self.connect, text='Audio setup — saved after the first connection', style='Heading.TLabel').pack(anchor='w')
        self.download_hint = self.note(self.connect, 'Connect HDMI to the receiver input. Click Download mpv for automatic setup, or Browse to use your own player.')
        path_row = ttk.Frame(self.connect)
        path_row.pack(fill='x', pady=4)
        ttk.Label(path_row, text='mpv.exe', width=12).pack(side='left')
        self.mpv_entry = ttk.Entry(path_row, textvariable=self.mpv_path)
        self.mpv_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.download_button = ttk.Button(path_row, text='Download mpv', command=self.download_mpv)
        self.download_button.pack(side='left', padx=(0, 8))
        self.mpv_button = ttk.Button(path_row, text='Browse…', command=self.choose_mpv)
        self.mpv_button.pack(side='left')
        audio_row = ttk.Frame(self.connect)
        audio_row.pack(fill='x', pady=6)
        ttk.Label(audio_row, text='HDMI audio', width=12).pack(side='left')
        self.device_box = ttk.Combobox(audio_row, textvariable=self.audio_device, state='readonly')
        self.device_box.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.refresh_button = ttk.Button(audio_row, text='Refresh', command=self.refresh_devices)
        self.refresh_button.pack(side='left')
        self.note(self.connect, 'Select the soundbar/receiver by name. Windows also lists speakers and other outputs; the app cannot certify TrueHD support from a device name.')
        mode_row = ttk.Frame(self.connect); mode_row.pack(fill='x', pady=4)
        ttk.Label(mode_row, text='Sync mode', width=12).pack(side='left')
        self.mode_box = ttk.Combobox(mode_row, textvariable=self.sync_mode, values=list(self.mode_labels), state='readonly')
        self.mode_box.pack(side='left', fill='x', expand=True)
        self.note(self.connect, 'Compare modes with Video lead at 0 first. Each mode saves its own adjustment. Disconnect before changing mode.')
        row = ttk.Frame(self.connect)
        row.pack(fill='x', pady=(3, 12))
        self.start_button = ttk.Button(row, text='Start TV connection', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(row, text='Disconnect', command=self.stop)
        self.stop_button.pack(side='left', padx=8)
        self.player_button = ttk.Button(row, text='Go to Player →', style='Navigate.TButton',
                                       command=lambda: self.tabs.select(self.player))
        self.player_button.pack(side='right')
        ttk.Separator(self.connect).pack(fill='x', pady=8)
        ttk.Label(self.connect, textvariable=self.connection_text, style='Heading.TLabel', wraplength=790).pack(anchor='w', pady=6)
        self.pair_label = ttk.Label(self.connect, textvariable=self.pairing_text, style='Code.TLabel', wraplength=790)
        self.pair_label.pack(anchor='w', pady=5)
        self.note(self.connect, 'On the TV, open DualTheater TV Robust Sync and choose this computer. Enter the code once. Remembered TVs can reconnect automatically.')

    def _player_page(self):
        ttk.Label(self.player, textvariable=self.playback_text, style='Heading.TLabel', wraplength=790).pack(anchor='w', pady=(0, 12))
        row = ttk.Frame(self.player)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=self.movie_path).pack(side='left', fill='x', expand=True, padx=(0, 8))
        ttk.Button(row, text='Choose movie…', command=self.choose_movie).pack(side='left')
        self.load_button = ttk.Button(row, text='Load movie', command=self.load_movie)
        self.load_button.pack(side='left', padx=(8, 0))
        self.note(self.player, 'Choose an original MKV with a TrueHD audio track. Loading prepares both devices; press Play when ready.')
        row = ttk.Frame(self.player)
        row.pack(fill='x', pady=8)
        self.play_button = ttk.Button(row, text='Play', command=lambda: self.action('play'))
        self.play_button.pack(side='left')
        self.pause_button = ttk.Button(row, text='Pause', command=lambda: self.action('pause'))
        self.pause_button.pack(side='left', padx=8)
        self.back_button = ttk.Button(row, text='−10 seconds', command=lambda: self.seek_relative(-10))
        self.back_button.pack(side='left')
        self.forward_button = ttk.Button(row, text='+10 seconds', command=lambda: self.seek_relative(10))
        self.forward_button.pack(side='left', padx=8)
        self.resync_button = ttk.Button(row, text='Resynchronize', command=lambda: self.action('resync'))
        self.resync_button.pack(side='left')
        self.timeline = ttk.Scale(self.player, from_=0, to=1)
        self.timeline.pack(fill='x', pady=(12, 0))
        self.timeline.bind('<ButtonPress-1>', lambda event: setattr(self, 'dragging', True))
        self.timeline.bind('<ButtonRelease-1>', self.seek_slider)
        for key in ('Left', 'Right', 'Home', 'End'):
            self.timeline.bind(f'<KeyRelease-{key}>', self.seek_slider)
        ttk.Label(self.player, textvariable=self.time_text).pack(anchor='w', pady=(0, 10))
        row = ttk.Frame(self.player)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='Seek to (seconds)').pack(side='left')
        ttk.Entry(row, textvariable=self.seek_seconds, width=10).pack(side='left', padx=8)
        self.seek_button = ttk.Button(row, text='Seek', command=self.seek_exact)
        self.seek_button.pack(side='left')
        row = ttk.Frame(self.player)
        row.pack(fill='x', pady=12)
        ttk.Label(row, text='Audio track').pack(side='left')
        self.track_box = ttk.Combobox(row, state='readonly')
        self.track_box.pack(side='left', fill='x', expand=True, padx=8)
        self.track_button = ttk.Button(row, text='Switch track', command=self.switch_track)
        self.track_button.pack(side='left')
        ttk.Label(self.player, textvariable=self.audio_text, wraplength=790).pack(anchor='w', pady=8)
        self.note(self.player, 'TV remote: OK plays/pauses; left/right seeks. All transport controls use the same Windows synchronization barrier.')

    def _diagnostics_page(self):
        page = self.diagnostics_page
        ttk.Label(page, text='Playback diagnostics', style='Heading.TLabel').pack(anchor='w')
        self.note(page, 'See timing quality, TV buffer health and recovery counts for this connection session. API estimates do not establish physical lip-sync, HDR or Atmos reception.')
        ttk.Label(page, textvariable=self.diagnostic_text, justify='left', wraplength=790).pack(anchor='w', pady=8)
        self.phone_calibration_text = tk.StringVar(value='Phone calibration: no phone connected.')
        ttk.Label(page, textvariable=self.phone_calibration_text, wraplength=790).pack(anchor='w', pady=4)
        self.export_button = ttk.Button(page, text='Export sanitized report…', command=self.export_diagnostics)
        self.export_button.pack(anchor='w', pady=6)
        self.note(page, 'Preview the report fields below; export saves the latest measurements. Reports exclude movie names, paths, network addresses, device identifiers, pairing data and raw logs. Counters reset when the Windows host restarts; drift statistics use the latest 600 accepted samples.')
        ttk.Label(page, textvariable=self.export_notice, foreground='#245e39').pack(anchor='w')
        self.diagnostic_preview = tk.Text(page, height=12, wrap='word', state='disabled', font=('Consolas', 9))
        self.diagnostic_preview.pack(fill='both', expand=True, pady=6)

    def export_diagnostics(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='Export sanitized diagnostic report',
            defaultextension='.json', initialfile='DualTheater-diagnostics.json', filetypes=[('JSON report', '*.json')])
        if path:
            self.export_notice.set('')
            self._queue('export_diagnostics', path=path)

    def _settings_page(self):
        ttk.Label(self.options, text='Receiver information (read only)', style='Heading.TLabel').pack(anchor='w')
        receiver_row = ttk.Frame(self.options); receiver_row.pack(fill='x', pady=5)
        ttk.Entry(receiver_row, textvariable=self.receiver_address, width=18).pack(side='left', padx=(0, 8))
        self.receiver_button = ttk.Button(receiver_row, text='Inspect LG S95TR',
            command=lambda: self._queue('inspect_s95tr', address=self.receiver_address.get().strip()))
        self.receiver_button.pack(side='left')
        self.hdmi_button = ttk.Button(receiver_row, text='Inspect HDMI latency', command=lambda: self._queue('inspect_hdmi'))
        self.hdmi_button.pack(side='left', padx=8)
        self.note(self.options, 'Enter the soundbar’s private network address. Queries preserve all settings. HDMI declarations may describe a different video path.')
        ttk.Label(self.options, textvariable=self.receiver_text, wraplength=790).pack(anchor='w', pady=(0, 8))
        ttk.Label(self.options, text='Lip-sync adjustment', style='Heading.TLabel').pack(anchor='w')
        self.note(self.options, 'If sound arrives early, increase Video lead. If sound arrives late, decrease it. Save and resynchronize applies the offset through coordinated playback. The separate phone client can measure before applying a correction.')
        row = ttk.Frame(self.options)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text='Video lead (ms)').pack(side='left')
        ttk.Spinbox(row, from_=-2000, to=2000, increment=10, textvariable=self.offset, width=10).pack(side='left', padx=8)
        self.offset_button = ttk.Button(row, text='Save and resynchronize', command=self.save_offset)
        self.offset_button.pack(side='left')
        self.note(self.options, 'The timing below is estimated from device APIs; it does not prove physical lip-sync. Confirm the TV HDR mode and receiver Atmos indication independently.')
        self.timing = ttk.Label(self.options, text='No timing samples yet.')
        self.timing.pack(anchor='w', pady=5)
        row = ttk.Frame(self.options)
        row.pack(fill='x', pady=10)
        ttk.Button(row, text='Open local settings folder', command=self.open_data).pack(side='left')
        self.browser_button = ttk.Button(row, text='Advanced browser controller', command=self.open_browser)
        self.browser_button.pack(side='left', padx=8)
        ttk.Button(row, text='Project instructions', command=lambda: webbrowser.open('https://github.com/shadow-pheonix/dualtheater#how-to-use')).pack(side='left')
        self.note(self.options, 'Download mpv on Connect fetches a checksum-pinned Windows package directly from the official mpv GitHub release. It is selected automatically and kept locally for offline use afterward. Browse lets you choose your own build instead. Disconnect before changing audio setup, then reconnect and reload the movie.')
        licenses = ttk.Frame(self.options)
        licenses.pack(anchor='w', pady=(0, 8))
        ttk.Button(licenses, text='Third-party licenses', command=self.open_licenses).pack(side='left')
        ttk.Button(licenses, text='mpv download / source', command=lambda:webbrowser.open(DOWNLOAD_PAGE)).pack(side='left', padx=(8, 0))
        ttk.Label(self.options, text='Local session details — may contain private paths/device information').pack(anchor='w')
        self.details = tk.Text(self.options, height=10, wrap='word', state='disabled', font=('Consolas', 9))
        self.details.pack(fill='both', expand=True, pady=6)

    def choose_mpv(self):
        chosen = filedialog.askopenfilename(parent=self.root, title='Select mpv.exe', filetypes=[('Windows player', 'mpv.exe'), ('Executables', '*.exe')])
        if chosen:
            self.mpv_path.set(chosen)
            self.auto_start = False
            self.refresh_devices()

    def refresh_devices(self):
        self.error_text.set('')
        self.devices = []
        self.device_box['values'] = []
        self.device_box.set('')
        self._queue('devices', mpv=self.mpv_path.get().strip().strip('"'))

    def download_mpv(self):
        self.auto_start = False
        self.downloading = True
        self.error_text.set('')
        self.download_hint.configure(text='Downloading from the official mpv GitHub release. Existing players are kept; close the app to cancel.')
        self._queue('download_mpv')

    def start(self):
        index = self.device_box.current()
        if index < 0:
            self.error_text.set('Choose your HDMI audio device from the list first.')
            return
        path = self.mpv_path.get().strip().strip('"')
        device = self.devices[index]['id']
        try:
            self.settings.save(path, device, self.mode_labels[self.sync_mode.get()])
        except (OSError, ValueError, RuntimeError) as e:
            self.error_text.set(str(e))
            return
        self.error_text.set('')
        self.offset_loaded = False
        self._queue('start', mpv=path, device=device, sync_mode=self.mode_labels[self.sync_mode.get()])

    def stop(self):
        if self.status.get('file') and not messagebox.askyesno('Disconnect TV', 'Stop playback and disconnect the TV?', parent=self.root):
            return
        self._queue('stop')

    def choose_movie(self):
        chosen = filedialog.askopenfilename(parent=self.root, title='Choose original movie', filetypes=[('Movie files', '*.mkv *.mp4 *.m2ts *.ts'), ('All files', '*.*')])
        if chosen:
            self.movie_path.set(chosen)

    def load_movie(self):
        path = self.movie_path.get().strip().strip('"')
        if not path:
            self.choose_movie()
            path = self.movie_path.get()
        if path:
            self.action('load', path=path, aid='auto')

    def action(self, name, **values):
        self.error_text.set('')
        self._queue('action', action=name, **values)

    def seek_relative(self, seconds):
        self.action('seek', seconds=max(0, min(self.status.get('duration_ms', 0)/1000 - .1,
                                             self.status.get('position_ms', 0)/1000 + seconds)))

    def seek_exact(self):
        try:
            seconds = float(self.seek_seconds.get())
        except ValueError:
            self.error_text.set('Enter the seek time in seconds, for example 600 for 10:00.')
            return
        self.action('seek', seconds=seconds)

    def seek_slider(self, event=None):
        self.dragging = False
        if self.status.get('file') and not self.busy:
            self.action('seek', seconds=min(self.timeline.get(), max(0, self.status.get('duration_ms', 0)/1000 - .1)))

    def switch_track(self):
        index = self.track_box.current()
        if 0 <= index < len(self.track_ids):
            self.action('track', aid=self.track_ids[index])

    def save_offset(self):
        try:
            value = float(self.offset.get())
            if not -2000 <= value <= 2000:
                raise ValueError()
        except ValueError:
            self.error_text.set('Enter a video lead between −2000 and 2000 milliseconds.')
            return
        self.action('offset', milliseconds=value)
        # Resync is enqueued only after saving succeeds; see action_done handling.

    def open_data(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.directory))

    def open_browser(self):
        if self.running:
            webbrowser.open('http://localhost:8764')

    def open_licenses(self):
        directory = Path(__file__).resolve().parent.parent
        path = directory / 'licenses'
        if not path.is_dir():
            path = directory / 'docs/licenses'
        os.startfile(str(path))

    def _queue(self, operation, **values):
        if self.service.submit(operation, **values):
            self.busy = True
            self.activity.start(12)
            self._update_controls()

    def _events(self):
        try:
            while True:
                kind, value = self.service.events.get_nowait()
                if kind == 'busy':
                    self.busy = value
                    if value:
                        self.activity.start(12)
                    else:
                        self.activity.stop()
                elif kind == 'receiver_information':
                    if isinstance(value, dict):
                        delay = value.get('added_av_delay_ms')
                        self.receiver_text.set('LG AV-delay setting: ' + ('unknown' if delay is None else str(delay) + ' ms')
                            + ' (community interpretation). Total processing delay remains unknown. No correction applied.')
                    else:
                        self.receiver_text.set(str(len(value)) + ' HDMI descriptors inspected. Declared audio delays: '
                            + ', '.join('unknown' if row['audio_latency_ms'] is None else str(row['audio_latency_ms']) + ' ms' for row in value)
                            + '. Route and processing-mode coverage are unverified. No correction applied.')
                elif kind == 'error':
                    self.error_text.set(value)
                    if self.downloading:
                        self.downloading = False
                        self.download_hint.configure(text='mpv setup did not complete. Check the error below, retry Download mpv or use Browse. Your previous player was kept.')
                elif kind == 'download_progress':
                    self.download_hint.configure(text=value)
                elif kind == 'mpv_ready':
                    self.downloading = False
                    self.mpv_path.set(value)
                    self.refresh_devices()
                elif kind == 'devices':
                    self.devices = value
                    self.device_box['values'] = [d['label'] for d in value]
                    saved = self.settings.values.get('device')
                    index = next((i for i, d in enumerate(value) if d['id'] == saved), -1)
                    if index >= 0:
                        self.device_box.current(index)
                        if self.auto_start:
                            self.root.after(0, self.start)
                    else:
                        self.device_box.set('')
                        if saved:
                            self.error_text.set('The saved HDMI output is not available. Reconnect it and refresh, or choose another output.')
                    self.auto_start = False
                elif kind == 'started':
                    self.running = True
                    self.offset_loaded = False
                    self.require_reload = True
                    self.export_notice.set('')
                elif kind == 'diagnostics_exported':
                    self.export_notice.set('Sanitized report saved.')
                elif kind == 'stopped':
                    self.running = False
                    self.status = {}
                    self.was_connected = False
                    self.require_reload = True
                    self.connection_text.set('Disconnected. Choose your audio output and start again.')
                    self.pairing_text.set('Connection stopped')
                    self.playback_text.set('Reconnect the TV, then reload the movie.')
                    self.track_ids = []
                    self.track_key = None
                    self.track_box['values'] = []
                    self.track_box.set('')
                    self.audio_text.set('No movie loaded.')
                    self.timeline.set(0)
                    self.time_text.set('0:00 / 0:00')
                    self.diagnostic_text.set('Session stopped. Start the TV connection to collect new diagnostics.')
                elif kind == 'status' and self.running:
                    self._status(value)
                elif kind == 'action_done':
                    self.error_text.set('')
                    if value == 'load':
                        self.require_reload = False
                    if value == 'offset' and self.status.get('file') and not self.require_reload and self.status.get('connected'):
                        self.service.submit('action', action='resync')
                self._update_controls()
        except queue.Empty:
            pass
        if self.closing and self.service.closed.is_set():
            self.root.destroy()
            return
        self.root.after(120, self._events)

    def _status(self, value):
        self.status = value
        connected = value['connected']
        self.connection_text.set(('TV connected to ' if connected else 'On the TV, choose ') + value['host_name'])
        code = value['pair_code']
        self.pairing_text.set(('Connected · Code ' if connected else 'Pairing code ') + code[:3] + ' ' + code[3:])
        if connected and not self.was_connected:
            self.tabs.select(self.player)
        if self.was_connected and not connected:
            self.require_reload = True
            self.error_text.set('TV disconnected. Reconnect it, then reload the movie before resuming.')
        self.was_connected = connected
        self.playback_text.set((value.get('file') or 'Choose a movie') + ' · ' + value['state'].replace('_', ' ').capitalize() + ' · ' + value.get('sync_mode', 'baseline'))
        position, duration = value.get('position_ms', 0), value.get('duration_ms', 0)
        if not self.dragging:
            self.timeline.configure(to=max(1, duration/1000))
            self.timeline.set(position/1000)
        self.time_text.set(f'{format_time(position)} / {format_time(duration)}')
        if not self.offset_loaded:
            self.offset.set(str(round(value['video_lead_ms'])))
            self.offset_loaded = True
        drift, rtt = value['drift_ms'], value['clock_rtt_ms']
        profile_note = ' · Saved adjustment context changed; verify it' if value.get('offset_profile') == 'context_changed' else ''
        self.timing.configure(text=f"Estimated drift: {'—' if drift is None else f'{drift:.1f} ms'} · Clock RTT: {'—' if rtt is None else f'{rtt:.1f} ms'}" + profile_note)
        report = value['diagnostics']
        telemetry, timing = report['telemetry'], report['timing']
        def metric(value, suffix=''):
            return '—' if value is None else f'{value:.1f}{suffix}'
        buffer_ms = telemetry['buffer_ahead_ms']
        self.diagnostic_text.set(
            f"Sync: {value.get('sync_mode')} · Remote clock: {report.get('sync', {}).get('remote_clock_state', 'unknown')}\n"
            f"TV telemetry: {telemetry['status']} · Buffer ahead: {metric(buffer_ms / 1000 if buffer_ms is not None else None, ' s')}\n"
            f"Last measured transfer: {metric(telemetry['transfer_mbps'], ' Mbps')} · Sample age: {metric(telemetry['transfer_age_ms'] / 1000 if telemetry['transfer_age_ms'] is not None else None, ' s')} · Dropped frames: {metric(telemetry['dropped_video_frames'])}\n"
            f"Drift |p95|: {metric(timing['p95_absolute_drift_ms'], ' ms')} · Timing sample age: {metric(timing['last_sample_age_ms'], ' ms')}\n"
            f"Buffer recoveries: {report['recoveries']['buffering']} · Drift recoveries: {report['recoveries']['drift']} · Errors: {report['errors']} · Disconnects: {report['disconnects']}")
        self.diagnostic_preview.configure(state='normal')
        self.diagnostic_preview.delete('1.0', 'end')
        self.diagnostic_preview.insert('1.0', json.dumps(report, indent=2, allow_nan=False))
        self.diagnostic_preview.configure(state='disabled')
        phone = value['phone_calibration']
        self.phone_calibration_text.set('Profile: ' + value.get('offset_profile', 'unknown')
            + ' · Lead: ' + str(value['video_lead_ms']) + ' ms · Phone calibration: ' + phone['state']
            + (' · ' + phone['error'] if phone['error'] else '')
            + (' · No phone connected' if not phone['phone_connected'] else ' · Phone connected'))
        self.audio_text.set('TrueHD bitstream reported by mpv. Confirm Atmos on your receiver.' if value.get('audio', {}).get('valid') else 'TrueHD output has not been confirmed for this session.')
        tracks = [t for t in value.get('audio_tracks', []) if t.get('type') == 'audio']
        key = json.dumps(tracks, sort_keys=True)
        if key != self.track_key:
            self.track_key = key
            self.track_ids = [t['id'] for t in tracks]
            self.track_box['values'] = [f"{t['id']}: {t.get('lang', '')} {t.get('codec', '')} {t.get('title', '')}" for t in tracks]
            selected = next((i for i, t in enumerate(tracks) if t.get('selected')), -1)
            if selected >= 0:
                self.track_box.current(selected)
            elif tracks:
                self.track_box.current(0)
            else:
                self.track_box.set('')
        if value.get('error'):
            self.error_text.set(value['error'])
        # Tokens, pairing credentials and addresses are intentionally omitted from this view.
        detail = {'state': value['state'], 'tv': value['tv'], 'audio': value['audio'], 'events': value['logs'][-8:]}
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', json.dumps(detail, indent=2, ensure_ascii=False))
        self.details.configure(state='disabled')

    def _update_controls(self):
        idle = not self.busy and not self.closing
        setup = idle and not self.running
        for control in (self.mpv_entry, self.mpv_button, self.refresh_button, self.download_button):
            control.configure(state='normal' if setup else 'disabled')
        self.device_box.configure(state='readonly' if setup else 'disabled')
        self.mode_box.configure(state='readonly' if setup else 'disabled')
        inspect_ready = idle and self.status.get('state') not in ('playing', 'armed', 'loading', 'seeking')
        self.receiver_button.configure(state='normal' if inspect_ready else 'disabled')
        self.hdmi_button.configure(state='normal' if inspect_ready else 'disabled')
        self.start_button.configure(state='normal' if setup and self.devices else 'disabled')
        self.stop_button.configure(state='normal' if self.running and not self.closing else 'disabled')
        ready = idle and self.running and self.status.get('connected', False)
        loaded = ready and bool(self.status.get('file')) and not self.require_reload
        self.load_button.configure(state='normal' if ready else 'disabled')
        for control in (self.play_button, self.back_button, self.forward_button, self.resync_button,
                        self.seek_button, self.track_button):
            control.configure(state='normal' if loaded else 'disabled')
        self.timeline.configure(state='normal' if loaded else 'disabled')
        self.track_box.configure(state='readonly' if loaded else 'disabled')
        self.pause_button.configure(state='normal' if self.running and self.status.get('file') and not self.closing else 'disabled')
        self.offset_button.configure(state='normal' if idle and self.running else 'disabled')
        self.browser_button.configure(state='normal' if self.running else 'disabled')
        self.export_button.configure(state='normal' if idle and self.running else 'disabled')

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.error_text.set('Stopping both players and closing the connection…')
        if not self.service.submit('close'):
            self.closing = False
            self.root.after(250, self.close)
        self._update_controls()


def smoke_test(path):
    """Exercise the packaged GUI/resources and local host without TV/HDMI playback."""
    with tempfile.TemporaryDirectory(prefix='dualtheater-smoke-') as directory:
        root = tk.Tk()
        root.withdraw()
        window = DesktopWindow(root, directory, auto_start=False)
        root.update()
        assert len(window.tabs.tabs()) == 4
        download_check = 'not configured'
        if os.environ.get('DUALTHEATER_SMOKE_DOWNLOAD') == '1':
            window.download_mpv()
            deadline = time.monotonic()+50
            while window.downloading or window.busy:
                if time.monotonic() > deadline:
                    raise TimeoutError('Packaged mpv download/selection timed out')
                root.update()
                time.sleep(.02)
            error = window.error_text.get()
            assert not error or error.startswith('No Windows WASAPI devices found.'), error
            assert window.mpv_path.get() == find_mpv(data_dir=directory)
            # Headless CI can legitimately have no WASAPI endpoints.
            download_check = 'passed'
        for resource in ('controller.html', 'select_audio.lua', 'audio_timing.lua'):
            assert Path(__file__).with_name(resource).is_file(), resource
        from .calibration import FIXTURE_SHA256
        import hashlib
        fixture = Path(__file__).resolve().parent.parent / 'calibration-phone-SDR-TrueHD.mkv'
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == FIXTURE_SHA256
        runtime = HostRuntime(runtime_args('unused.exe', 'wasapi/smoke-test', directory, ephemeral=True))
        try:
            runtime.start()
            import http.client
            connection = http.client.HTTPConnection('127.0.0.1', runtime.args.ui_port, timeout=5)
            connection.request('GET', '/')
            response = connection.getresponse()
            assert response.status == 200
            assert b'DualTheater' in response.read()
            connection.close()
            # Exercise the new diagnostics widgets using the real local runtime.
            window._status(runtime.app.snapshot())
            assert 'schema_version' in window.diagnostic_preview.get('1.0', 'end')
            report_path = Path(directory) / 'diagnostics.json'
            save_report(report_path, runtime.app.diagnostic_report())
            assert json.loads(report_path.read_text())['schema_version'] == 1
            assert runtime.app.ui_token not in report_path.read_text()
            assert (Path(directory)/'pairings.json').is_file()
        finally:
            runtime.close()
        player_check = 'not configured'
        if os.environ.get('DUALTHEATER_MPV'):
            # Runs the external player from the frozen process, including its DLLs.
            list_devices(os.environ['DUALTHEATER_MPV'],allow_empty=True)
            player_check = 'passed'
        window.close()
        while not window.service.closed.wait(.05):
            root.update()
        root.destroy()
        Path(path).write_text(json.dumps({'version': VERSION, 'gui': 'passed', 'pages': 4,
                                        'resources': 'passed', 'host_start_stop': 'passed',
                                        'external_player': player_check,
                                        'download_select': download_check,
                                        'diagnostics': 'passed',
                                        'physical_playback': 'not tested'}), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', metavar='RESULT_JSON', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test(args.smoke_test)
        return
    mutex = None
    try:
        if os.name == 'nt':
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('DualTheater.Desktop.RobustSync')
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            mutex = kernel.CreateMutexW(None, False, 'Local\\DualTheaterDesktop')
            if not mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:
                messagebox.showinfo('DualTheater', 'DualTheater is already running. Open its existing window.')
                return
        root = tk.Tk()
        DesktopWindow(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror('DualTheater could not start', str(e))
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == '__main__':
    main()
