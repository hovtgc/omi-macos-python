"""`sideband doctor`: what is ready, what is missing, and the exact next step. For people and agents.

The checks are plain functions over the machine and the support folder; `pendant_lines` reads a live
pendant through `radio.py` when asked. ONBOARDING.md walks through the same steps in order.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from sideband.app import SidebandApp
from sideband.llm import MODEL as LLM_MODEL
from sideband.transcribe import MODEL as WHISPER_MODEL
from sideband.transcribe import _cached
from sideband.voice import model_path

FEATURES = {
    0: "speaker",
    1: "motion",
    2: "button",
    3: "battery",
    4: "usb",
    5: "haptic",
    6: "offline storage",
    7: "LED dimming",
    8: "mic gain",
}
EXTRAS = (
    ("bleak", "bluetooth", "base install"),
    ("av", "audio decoding", "audio"),
    ("mlx_whisper", "transcription", "transcribe"),
    ("mlx_lm", "assistant", "llm"),
    ("vosk", "voice commands", "voice"),
    ("smpclient", "firmware updates", "firmware"),
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool | None  # None: optional / informational
    detail: str
    fix: str = ""

    def line(self) -> str:
        mark = {True: "✓", False: "✗", None: "·"}[self.ok]
        tail = f"\n      → {self.fix}" if self.fix and self.ok is not True else ""
        return f"  {mark} {self.name}: {self.detail}{tail}"


def features(raw: bytes) -> list[str]:
    """Names from the pendant's feature bitmask (characteristic 19b10021, little-endian)."""
    mask = int.from_bytes(raw[:4], "little") if raw else 0
    return [name for bit, name in FEATURES.items() if mask & (1 << bit)]


def machine_checks() -> list[Check]:
    arm = platform.machine() == "arm64"
    mac = platform.mac_ver()[0] or "not macOS"
    major = int(mac.split(".")[0]) if mac[0].isdigit() else 0
    py = sys.version_info
    free_gb = shutil.disk_usage(Path.home()).free / 1e9
    return [
        Check("Mac", arm and major >= 13, f"{platform.machine()}, macOS {mac}",
              "Transcription and the assistant need an Apple silicon Mac on macOS 13+ (MLX). Bluetooth, controls and games work elsewhere."),
        Check("Python", py >= (3, 10), f"{py.major}.{py.minor}.{py.micro} at {sys.executable}",
              "Use Python 3.10+: `uv venv --python 3.12 .venv` (system python3 on macOS is 3.9)."),
        Check("Disk", free_gb >= 8, f"{free_gb:.0f} GB free", "Models need about 6 GB; free some space."),
    ]


def package_checks() -> list[Check]:
    out = []
    for module, purpose, extra in EXTRAS:
        found = importlib.util.find_spec(module) is not None
        fix = "pip install -e ." if extra == "base install" else f"pip install -e '.[{extra}]'"
        out.append(Check(f"{purpose} ({module})", found, "installed" if found else "missing", fix))
    return out


def model_checks(app: SidebandApp) -> list[Check]:
    vosk_dir = model_path(app.support_dir)
    return [
        Check("Whisper model", _cached(WHISPER_MODEL), WHISPER_MODEL, "sideband models --download (about 1.6 GB)"),
        Check("Assistant model", _cached(LLM_MODEL), LLM_MODEL, "sideband models --download (about 4.3 GB)"),
        Check("Voice model", vosk_dir.is_dir(), str(vosk_dir), "sideband models --download (about 40 MB)"),
    ]


def app_checks(app: SidebandApp) -> list[Check]:
    device = None
    try:
        import json

        device = json.loads((app.support_dir / "device.json").read_text(encoding="utf-8")).get("address")
    except (OSError, ValueError):
        pass
    return [
        Check("Sideband.app", app.app_path.exists(), str(app.app_path), "sideband build-app"),
        Check("Pendant remembered", True if device else None, device or "none yet",
              "Wake the pendant (tap it), then: sideband --via-app scan, or open the Bluetooth app"),
        Check("Launcher", True if app.launcher_running() else None, "running" if app.launcher_running() else "not running",
              "sideband open launcher"),
    ]


def report(app: SidebandApp) -> tuple[list[str], bool]:
    """All offline checks, grouped. The bool says whether every required check passed."""
    groups = (
        ("This Mac", machine_checks()),
        ("Packages", package_checks()),
        ("Models", model_checks(app)),
        ("App", app_checks(app)),
    )
    lines, ok = [], True
    for title, checks in groups:
        lines.append(title)
        for check in checks:
            lines.append(check.line())
            ok = ok and check.ok is not False
    return lines, ok


def pendant_lines(facts: dict[str, bytes]) -> list[str]:
    """Explain what a connected pendant reports (from `radio.pendant_facts`)."""
    text = {k: v.decode("utf-8", "replace").strip("\x00") for k, v in facts.items() if k in ("model", "firmware", "hardware")}
    have = features(facts.get("features", b""))
    motion = "motion" in have or bool(facts.get("motion_service"))
    lines = [
        "Pendant",
        f"  ✓ {text.get('model', '?')} · firmware {text.get('firmware', '?')} · hardware {text.get('hardware', '?')}",
        f"  · battery {facts['battery'][0]}%" if facts.get("battery") else "  · battery unread",
        f"  · features: {', '.join(have) or 'unread'}",
    ]
    if motion:
        lines.append("  ✓ motion: streaming firmware installed (tilt games work)")
    elif text.get("model") == "Omi CV 1":
        lines.append("  · motion: not in this firmware. Taps, transcriber, voice and Controls work as is.")
        lines.append("      → optional, for tilt games: ONBOARDING.md step 7 (flashing, needs your explicit yes)")
    else:
        lines.append("  · motion: not available. The motion firmware is only built for the Omi CV 1.")
    return lines
