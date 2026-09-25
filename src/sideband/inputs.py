"""Pendant inputs other than audio: what each notifying characteristic is, button gestures, and the
gesture → Mac action map. Pure. No Bluetooth, no UI.

The firmware detects gestures itself and notifies `23ba7925` with an 8-byte little-endian code
(omi/firmware/omi/src/lib/core/button.c): 1 single tap (about 300 ms after the press), 2 double tap
(600 ms window), 5 release. `ButtonDecoder` adds two gestures on the Mac:

- triple: the firmware resets after a double, so a third tap arrives as a single shortly after it.
- hold: a press held past the 300 ms tap threshold and let go before 3 s sends only a release (5),
  with no tap before it. At 3 s the firmware powers the pendant off and sends nothing.

Motion is compiled out of stock firmware (CONFIG_OMI_ENABLE_ACCELEROMETER=n).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sideband.protocol import AUDIO_DATA_UUID, BATTERY_LEVEL_UUID

BUTTON_UUID = "23ba7925-0000-1000-7450-346eac492e92"
DEVICE_STATE_UUID = "19b10013-e8f2-537e-4f6c-d104768a1214"
STORAGE_UUID = "30295782-4301-eabd-2904-2849adfeae43"
STORAGE_CONTROL_UUID = "30295781-4301-eabd-2904-2849adfeae43"
SMP_UUID = "da2e7828-fbce-4e01-ae9e-261174997c48"

INPUTS = {
    BUTTON_UUID: "button",
    AUDIO_DATA_UUID: "microphone",
    BATTERY_LEVEL_UUID: "battery",
    DEVICE_STATE_UUID: "device state",
    STORAGE_UUID: "storage",
    STORAGE_CONTROL_UUID: "storage control",
    SMP_UUID: "firmware (SMP)",
}

BUTTON_CODES = {1: "single", 2: "double", 3: "long", 4: "press", 5: "release"}
GESTURES = ("single", "double", "triple", "hold")
TRIPLE_WINDOW_S = 0.9  # after a double, a single this soon makes it a triple
TAP_ECHO_S = 0.6  # a release this soon after a tap belongs to that tap


def input_name(uuid: str) -> str:
    return INPUTS.get(uuid.lower(), uuid[:8])


def button_code(raw: bytes) -> int | None:
    if not raw:
        return None
    return int.from_bytes(raw[:8], "little")


def button_kind(code: int | None) -> str:
    if code is None:
        return "empty"
    return BUTTON_CODES.get(code, f"code-{code}")


@dataclass
class ButtonDecoder:
    """Firmware codes with a clock in, gestures out. Call `poll` often so a lone double is released.

    With `triples` off, a double fires at once. With it on, a double waits `TRIPLE_WINDOW_S` for a
    third tap.
    """

    triples: bool = True
    last_tap_at: float | None = None
    pending_double_at: float | None = None

    def feed(self, code: int | None, now: float) -> list[str]:
        kind = button_kind(code)
        if kind == "single":
            self.last_tap_at = now
            if self.pending_double_at is not None and now - self.pending_double_at <= TRIPLE_WINDOW_S:
                self.pending_double_at = None
                return ["triple"]
            return self.poll(now, force=True) + ["single"]
        if kind == "double":
            out = self.poll(now, force=True)
            self.last_tap_at = now
            if not self.triples:
                return out + ["double"]
            self.pending_double_at = now
            return out
        if kind == "release":
            if self.last_tap_at is None or now - self.last_tap_at > TAP_ECHO_S:
                return self.poll(now, force=True) + ["hold"]
        return []

    def poll(self, now: float, force: bool = False) -> list[str]:
        if self.pending_double_at is None:
            return []
        if force or now - self.pending_double_at > TRIPLE_WINDOW_S:
            self.pending_double_at = None
            return ["double"]
        return []


# --- Mac actions ------------------------------------------------------------------------------

ACTIONS = {
    # name: hint for the argument, "" when it takes none
    "none": "",
    "microphone": "toggle the live pendant mic (level only, nothing recorded)",
    "open app": "app to open or switch to",
    "notify": "notification text",
    "keystroke": "e.g. cmd+tab, space, cmd+shift+4, right",
    "open url": "https://… or any URL",
    "shortcut": "Shortcuts app name",
    "volume up": "",
    "volume down": "",
    "mute": "",
    "sleep display": "",
    "applescript": 'e.g. tell application "Spotify" to playpause',
    "shell": "shell command",
}
NEEDS_ACCESSIBILITY = ("keystroke",)

KEY_CODES = {
    "return": 36, "enter": 76, "tab": 48, "space": 49, "delete": 51, "escape": 53, "esc": 53,
    "left": 123, "right": 124, "down": 125, "up": 126, "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121, "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96,
    "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
MODIFIERS = {
    "cmd": "command down", "command": "command down", "shift": "shift down",
    "opt": "option down", "option": "option down", "alt": "option down",
    "ctrl": "control down", "control": "control down",
}


def keystroke_script(combo: str) -> str | None:
    """`cmd+shift+4` → a System Events AppleScript line. None when the combo is empty or has no key."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    *mods, key = parts
    if key in MODIFIERS or any(m not in MODIFIERS for m in mods):
        return None
    using = ""
    if mods:
        using = " using {" + ", ".join(dict.fromkeys(MODIFIERS[m] for m in mods)) + "}"
    if key in KEY_CODES:
        press = f"key code {KEY_CODES[key]}"
    elif len(key) == 1:
        press = f"keystroke {json.dumps(key)}"
    else:
        return None
    return f'tell application "System Events" to {press}{using}'


# macOS virtual key codes (ANSI layout) for recorded shortcuts. Named keys reuse KEY_CODES.
_VK_CHARS = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v", 11: "b", 12: "q",
    13: "w", 14: "e", 15: "r", 16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5",
    24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "o", 32: "u", 33: "[", 34: "i",
    35: "p", 37: "l", 38: "j", 39: "'", 40: "k", 41: ";", 42: "\\", 43: ",", 44: "/", 45: "n", 46: "m",
    47: ".", 50: "`",
}
_VK_NAMES = {code: name for name, code in KEY_CODES.items() if name not in ("esc",)}
MODIFIER_KEYSYMS = ("shift", "control", "meta", "alt", "super", "option", "command", "caps_lock")
# Tk on macOS: Shift 0x1, Control 0x4, Command 0x8 (Mod1), Option 0x10 (Mod2).
TK_MODIFIERS = ((0x8, "cmd"), (0x4, "ctrl"), (0x10, "opt"), (0x1, "shift"))


def combo_from_key(vk: int, keysym: str, state: int) -> str | None:
    """A recorded key press as `cmd+shift+4`. None while only modifiers are down or the key is unknown."""
    if keysym.lower().startswith(MODIFIER_KEYSYMS):
        return None
    key = _VK_NAMES.get(vk) or _VK_CHARS.get(vk)
    if key is None:
        lower = keysym.lower()
        key = {"backspace": "delete", "prior": "pageup", "next": "pagedown"}.get(lower, lower)
        if key not in KEY_CODES and len(key) != 1:
            return None
    mods = [name for bit, name in TK_MODIFIERS if state & bit]
    return "+".join(mods + [key])


def _osascript(script: str) -> list[str]:
    return ["osascript", "-e", script]


def action_command(action: str, arg: str, gesture: str) -> list[str] | None:
    """The process to start for an action, or None when there is nothing to run."""
    arg = arg.strip()
    if action == "open app" and arg:
        return ["open", "-a", arg]
    if action == "notify":
        text = json.dumps(arg or f"Omi {gesture}", ensure_ascii=False)
        return _osascript(f'display notification {text} with title "Sideband"')
    if action == "keystroke":
        script = keystroke_script(arg)
        return _osascript(script) if script else None
    if action == "open url" and arg:
        return ["open", arg]
    if action == "shortcut" and arg:
        return ["shortcuts", "run", arg]
    if action == "volume up":
        return _osascript("set volume output volume ((output volume of (get volume settings)) + 10)")
    if action == "volume down":
        return _osascript("set volume output volume ((output volume of (get volume settings)) - 10)")
    if action == "mute":
        return _osascript("set volume output muted (not (output muted of (get volume settings)))")
    if action == "sleep display":
        return ["pmset", "displaysleepnow"]
    if action == "applescript" and arg:
        return _osascript(arg)
    if action == "shell" and arg:
        return ["/bin/sh", "-c", arg]
    return None


def installed_apps(folders: list[Path]) -> list[str]:
    """App names (without .app) in the given folders and one level of subfolders, sorted, unique."""
    names: set[str] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.suffix == ".app":
                names.add(entry.stem)
            elif entry.is_dir() and not entry.name.startswith("."):
                names.update(child.stem for child in entry.glob("*.app"))
    return sorted(names, key=str.lower)


# --- Mapping ----------------------------------------------------------------------------------


@dataclass
class Mapping:
    action: str = "none"
    arg: str = ""


def default_gestures() -> dict[str, Mapping]:
    found = {g: Mapping() for g in GESTURES}
    found["single"] = Mapping("notify", "Omi tap")
    found["double"] = Mapping("microphone", "")
    return found


@dataclass
class InputMap:
    gestures: dict[str, Mapping] = field(default_factory=default_gestures)

    @classmethod
    def load(cls, path: Path) -> InputMap:
        found = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return found
        for gesture in GESTURES:
            entry = data.get(gesture) or {}
            action = entry.get("action", "none")
            found.gestures[gesture] = Mapping(action if action in ACTIONS else "none", str(entry.get("arg", "")))
        return found

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {g: {"action": m.action, "arg": m.arg} for g, m in self.gestures.items()}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
