"""Short sounds generated in memory and played locally. Nothing is downloaded.

`afplay` on a Mac, `paplay` or `aplay` elsewhere. A missing player is ignored.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from sideband.desert import tone_wav

_PATHS: dict[str, str] = {}


def blip(name: str, freq: float, ms: int, volume: float = 0.28, noise: float = 0.0) -> None:
    path = _PATHS.get(name)
    if path is None:
        try:
            fd, path = tempfile.mkstemp(prefix=f"sideband-{name}-", suffix=".wav")
            os.close(fd)
            with open(path, "wb") as handle:
                handle.write(tone_wav(freq, ms, volume, noise))
        except OSError:
            return
        _PATHS[name] = path
    for cmd in (["afplay", "-v", "0.4", path], ["paplay", path], ["aplay", "-q", path]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
