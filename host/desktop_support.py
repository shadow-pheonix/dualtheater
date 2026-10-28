"""Desktop settings, device discovery and background operations; no GUI dependency."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading

from .server import HostRuntime, lan_address
from .player_download import managed_player, install_player
from . import __version__
from .diagnostics import save_report

VERSION = __version__
PROFILE_NAME = 'DualTheater-Preview'


def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / PROFILE_NAME


def find_mpv(saved='', executable_dir=None, data_dir=None):
    directory = Path(executable_dir or (Path(sys.executable).parent if getattr(sys, 'frozen', False)
                                      else Path(__file__).resolve().parent.parent))
    data_dir = Path(data_dir or default_data_dir())
    downloaded = managed_player(data_dir)
    # Saved managed paths must pass the receipt check, including supporting DLLs.
    if saved and Path(saved).resolve().is_relative_to((data_dir/'players').resolve()):
        saved = downloaded
    for candidate in (saved, downloaded,
                      directory / 'mpv.exe', directory / 'tools/mpv.exe', shutil.which('mpv.exe')):
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return ''


class Settings:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'settings.local.json'
        self.values = {}
        self.warning = ''
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict):
                    raise ValueError('Expected a JSON object')
                self.values = {key: value[key] for key in ('mpv', 'device') if isinstance(value.get(key), str)}
            except (OSError, ValueError):
                self.warning = 'Saved audio setup could not be read. Choose mpv and HDMI audio again.'

    def save(self, mpv, device):
        if not Path(mpv).is_file() or not device.startswith('wasapi/'):
            raise ValueError('Choose an existing mpv executable and a WASAPI audio device.')
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.warning and self.path.exists():
            # Preserve unreadable settings for local recovery; never publish them.
            backup = self.path.with_name('settings.local.unreadable.json')
            if backup.exists():
                raise RuntimeError('An unreadable settings backup already exists; preserve it before saving again.')
            self.path.replace(backup)
        temporary = self.path.with_suffix('.tmp')
        self.values = {'mpv': str(Path(mpv).resolve()), 'device': device}
        temporary.write_text(json.dumps(self.values, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)
        self.warning = ''


def parse_devices(output):
    devices = []
    for line in output.splitlines():
        match = re.match(r"\s*'([^']+)'\s+\((.*)\)\s*$", line)
        if match and match[1].startswith('wasapi/'):
            devices.append({'id': match[1], 'label': match[2] or match[1]})
    # Friendly names may collide; number them rather than displaying long endpoint IDs.
    counts = {}
    for device in devices:
        label = device['label']
        counts[label] = counts.get(label, 0) + 1
        if sum(d['label'] == label for d in devices) > 1 or counts[label] > 1:
            device['label'] = f"{label} ({counts[label]})"
    return devices


def list_devices(executable, allow_empty=False):
    if not Path(executable).is_file():
        raise ValueError('Select mpv.exe first.')
    result = subprocess.run([str(executable), '--no-config', '--audio-device=help'],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('mpv could not list audio devices. Choose a working Windows mpv build.')
    devices = parse_devices((result.stdout + result.stderr).decode('utf-8', errors='replace'))
    if not devices and not allow_empty:
        raise RuntimeError('No Windows WASAPI devices found. Check the HDMI connection and refresh.')
    return devices


def runtime_args(mpv, device, directory, ephemeral=False):
    return argparse.Namespace(mpv=str(mpv), device=device, data_dir=str(directory),
                              diagnostic=False, host=lan_address(),
                              ui_port=0 if ephemeral else 8764, media_port=0 if ephemeral else 8765,
                              control_port=0 if ephemeral else 8766,
                              discovery_port=0 if ephemeral else 8767)


def format_time(milliseconds):
    seconds = max(0, int((milliseconds or 0) / 1000))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


class DesktopService:
    """Keep slow IPC/network work off Tk's thread; preserve Coordinator transport logic."""
    def __init__(self, directory, runtime_factory=HostRuntime):
        self.directory = Path(directory)
        self.runtime_factory = runtime_factory
        self.runtime = None
        self.commands = queue.Queue(maxsize=8)
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.cancel_download = threading.Event()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.poller = threading.Thread(target=self._poll, daemon=True)
        self.worker.start()
        self.poller.start()

    def submit(self, operation, **values):
        if operation == 'download_mpv':
            self.cancel_download.clear()
        if operation in ('stop', 'close'):
            self.cancel_download.set()
        if operation in ('stop', 'close') or (operation == 'action' and values.get('action') == 'pause'):
            if self.runtime:
                self.runtime.app.cancel.set()
        try:
            self.commands.put_nowait((operation, values))
            return True
        except queue.Full:
            self.events.put(('error', 'Please wait for the current operation.'))
            return False

    def _work(self):
        while not self.closed.is_set():
            operation, values = self.commands.get()
            self.events.put(('busy', True))
            try:
                if operation == 'devices':
                    self.events.put(('devices', list_devices(values['mpv'])))
                elif operation == 'download_mpv':
                    player = install_player(self.directory, cancel=self.cancel_download,
                        progress=lambda message:self.events.put(('download_progress',message)))
                    self.events.put(('mpv_ready',player))
                elif operation == 'start':
                    if self.runtime:
                        raise RuntimeError('Stop the connection before changing audio setup.')
                    runtime = self.runtime_factory(runtime_args(values['mpv'], values['device'], self.directory))
                    runtime.start()
                    self.runtime = runtime
                    self.events.put(('started', None))
                elif operation == 'action':
                    if not self.runtime:
                        raise RuntimeError('Start the TV connection first.')
                    self.runtime.app.action(values)
                    self.events.put(('action_done', values['action']))
                elif operation == 'export_diagnostics':
                    if not self.runtime:
                        raise RuntimeError('Start the TV connection before exporting diagnostics.')
                    save_report(values['path'], self.runtime.app.diagnostic_report())
                    self.events.put(('diagnostics_exported', None))
                elif operation in ('stop', 'close'):
                    runtime, self.runtime = self.runtime, None
                    if runtime:
                        runtime.close()
                    self.events.put(('stopped', None))
                    if operation == 'close':
                        self.closed.set()
                else:
                    raise ValueError('Unknown desktop operation')
            except Exception as e:
                message = str(e)
                if isinstance(e, OSError) and getattr(e, 'winerror', None) == 10048:
                    message = 'Another DualTheater host is using the connection ports. Close it, then try again.'
                self.events.put(('error', message))
                if operation == 'close':
                    self.closed.set()
            finally:
                self.events.put(('busy', False))

    def _poll(self):
        while not self.closed.wait(.6):
            runtime = self.runtime
            if runtime:
                try:
                    self.events.put(('status', runtime.app.snapshot()))
                except Exception:
                    # IPC can disappear during load/stop. The operation result owns errors.
                    pass
