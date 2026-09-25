"""Stdout log with an optional file. Safe to use from the radio thread."""

from __future__ import annotations

import threading
import time
from pathlib import Path


class HoldLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.codec = "unread"
        self.battery: int | None = None
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self._lock:
            print(line, flush=True)
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
