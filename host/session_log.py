"""Bounded optional diagnostic I/O; playback never waits for a disk write."""
import csv
from pathlib import Path
import queue
import sys
import threading
import time


class SessionLog:
    def __init__(self, directory, capacity=128):
        self.directory = Path(directory)
        self.queue = queue.Queue(maxsize=capacity)
        self.closed = False
        self.errors = self.dropped = 0
        self.worker = threading.Thread(target=self._run, name='dualtheater-log', daemon=True)
        self.worker.start()

    def _offer(self, kind, value):
        if self.closed:
            return
        try:
            self.queue.put_nowait((kind, value))
        except queue.Full:
            self.dropped += 1

    def event(self, line):
        self._offer('event', str(line))

    def writerow(self, row):
        self._offer('timing', tuple(row))

    def flush(self):
        # Compatibility with the previous CSV writer. Only the worker flushes.
        pass

    def metrics(self):
        return {'errors': self.errors, 'dropped': self.dropped, 'pending': self.queue.qsize()}

    def _run(self):
        events = timing = writer = None
        retry_at = 0
        try:
            while not self.closed or not self.queue.empty():
                try:
                    kind, value = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                try:
                    if time.monotonic() < retry_at:
                        self.dropped += 1
                        continue
                    self.directory.mkdir(parents=True, exist_ok=True)
                    if kind == 'event':
                        if events is None:
                            events = (self.directory / 'events.log').open('a', encoding='utf-8')
                        events.write(value + '\n'); events.flush()
                        if sys.stdout is not None:
                            try:
                                print(value, flush=True)
                            except (OSError, ValueError):
                                pass
                    else:
                        if timing is None:
                            new = not (self.directory / 'timing.csv').exists()
                            timing = (self.directory / 'timing.csv').open('a', newline='', encoding='utf-8')
                            writer = csv.writer(timing)
                            if new:
                                writer.writerow(['host_ns', 'epoch', 'audio_ms', 'video_ms', 'error_ms',
                                                 'video_speed', 'clock_rtt_ms', 'ipc_uncertainty_ms'])
                        writer.writerow(value); timing.flush()
                except (OSError, ValueError, csv.Error):
                    self.errors += 1
                    retry_at = time.monotonic() + 5
                    for stream in (events, timing):
                        if stream is not None:
                            try:
                                stream.close()
                            except (OSError, ValueError):
                                pass
                    events = timing = writer = None
                finally:
                    self.queue.task_done()
        finally:
            for stream in (events, timing):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        self.errors += 1

    def close(self):
        self.closed = True
        # An unavailable/slow diagnostic filesystem cannot hold app shutdown.
        if threading.current_thread() is not self.worker:
            self.worker.join(timeout=1)
