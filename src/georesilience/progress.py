"""Timestamped stage progress with heartbeats and an elapsed-rate ETA."""

from threading import Event, Thread
from time import perf_counter

from .network import _log


class StageProgress:
    def __init__(self, label, total):
        self.label, self.total, self.done = label, total, 0
        self.started = self.last_log = perf_counter()
        self.stop = Event()
        self.thread = Thread(target=self._heartbeat, daemon=True)

    def log(self):
        elapsed = perf_counter() - self.started
        eta = f"{elapsed * (self.total - self.done) / self.done:.1f}s" if self.done else "pending"
        _log(f"{self.label}: {self.done}/{self.total}; estimated time remaining {eta}")
        self.last_log = perf_counter()

    def _heartbeat(self):
        while not self.stop.wait(30):
            self.log()

    def advance(self):
        self.done += 1
        if self.done == self.total or perf_counter() - self.last_log >= 10:
            self.log()

    def __enter__(self):
        self.log()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
