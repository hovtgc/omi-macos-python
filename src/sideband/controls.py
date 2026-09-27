"""Controls app: live pendant inputs and the gesture → Mac action map.

A window of the Sideband launcher. The launcher owns the connection and fires mapped actions even
while this window is closed; this window only shows inputs and edits the map.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

from sideband.inputs import ACTIONS, GESTURES, NEEDS_ACCESSIBILITY, combo_from_key, installed_apps
from sideband.motion import Motion

if TYPE_CHECKING:
    from sideband.ui import Hub

FLASH_MS = 220
ACCENT = "#2f7cf6"
IDLE = "#c9ced6"
KEYSTROKE_EXAMPLES = ["cmd+tab", "space", "right", "left", "cmd+shift+4", "ctrl+up", "cmd+w", "escape"]
APPLESCRIPT_EXAMPLES = [
    'tell application "Spotify" to playpause',
    'tell application "Spotify" to next track',
    'tell application "Music" to playpause',
]
APP_FOLDERS = [Path("/Applications"), Path("/System/Applications"), Path.home() / "Applications"]


class ControlsWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Controls")
        self.top.geometry("1060x560")
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.apps = installed_apps(APP_FOLDERS)
        self.shortcuts: list[str] = []
        self.presses = 0
        self.fired = {g: 0 for g in GESTURES}
        self.recording_for: str | None = None
        self._build()
        threading.Thread(target=self._load_shortcuts, daemon=True).start()
        self._check_access()

    # --- layout ----------------------------------------------------------------------------

    def _build(self) -> None:
        body = ttk.Frame(self.top, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2, uniform="col")
        body.columnconfigure(1, weight=3, uniform="col")
        body.rowconfigure(0, weight=1)
        self._build_live(ttk.LabelFrame(body, text="Live inputs", padding=12)).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_map(ttk.LabelFrame(body, text="Gesture → Mac action", padding=12)).grid(row=0, column=1, sticky="nsew", padx=(8, 0))

    def _build_live(self, frame: ttk.LabelFrame) -> ttk.LabelFrame:
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Button").grid(row=0, column=0, sticky="w")
        self.led = tk.Canvas(frame, width=44, height=44, highlightthickness=0)
        self.led.grid(row=0, column=1, sticky="w", pady=4)
        self.led_dot = self.led.create_oval(4, 4, 40, 40, fill=IDLE, outline="")
        self.button_info = tk.StringVar(value="taps 0")
        ttk.Label(frame, textvariable=self.button_info).grid(row=1, column=0, columnspan=2, sticky="w")

        ttk.Separator(frame).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(frame, text="Gesture").grid(row=3, column=0, sticky="w")
        self.gesture = tk.StringVar(value="—")
        ttk.Label(frame, textvariable=self.gesture, font=("Helvetica", 22, "bold")).grid(row=3, column=1, sticky="w")
        tiles = ttk.Frame(frame)
        tiles.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.tiles: dict[str, tk.Label] = {}
        for i, gesture in enumerate(GESTURES):
            tile = tk.Label(tiles, text=f"{gesture}\n0", width=9, height=2, bg=IDLE, fg="#1d1d1f")
            tile.grid(row=0, column=i, padx=3)
            self.tiles[gesture] = tile
        ttk.Label(
            tiles,
            text="hold = press ½–2 s, then let go. Holding 3 s powers the pendant off. Mapping triple delays double by 0.9 s.",
            foreground="#888",
            wraplength=300,
        ).grid(row=1, column=0, columnspan=len(GESTURES), sticky="w", pady=(6, 0))

        ttk.Separator(frame).grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)
        self.mic_state = tk.StringVar(value="Microphone off")
        ttk.Label(frame, textvariable=self.mic_state).grid(row=6, column=0, columnspan=2, sticky="w")
        self.level = ttk.Progressbar(frame, maximum=60)
        self.level.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        self.mic_info = tk.StringVar(value="— frames/s")
        ttk.Label(frame, textvariable=self.mic_info, foreground="#888").grid(row=8, column=0, columnspan=2, sticky="w")

        ttk.Separator(frame).grid(row=9, column=0, columnspan=2, sticky="ew", pady=10)
        self.state_info = tk.StringVar(value="charging —")
        ttk.Label(frame, textvariable=self.state_info, foreground="#888").grid(row=10, column=0, columnspan=2, sticky="w")
        self.motion_info = tk.StringVar(value="Motion: waiting for the pendant (stock firmware does not stream it)")
        ttk.Label(frame, textvariable=self.motion_info, wraplength=330).grid(row=11, column=0, columnspan=2, sticky="w", pady=(10, 0))
        return frame

    def _build_map(self, frame: ttk.LabelFrame) -> ttk.LabelFrame:
        frame.columnconfigure(2, weight=1)
        self.rows: dict[str, tuple[tk.StringVar, tk.StringVar, ttk.Combobox]] = {}
        self.record_buttons: dict[str, ttk.Button] = {}
        for i, gesture in enumerate(GESTURES):
            mapping = self.hub.map.gestures[gesture]
            action = tk.StringVar(value=mapping.action)
            arg = tk.StringVar(value=mapping.arg)
            ttk.Label(frame, text=gesture, width=7).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Combobox(frame, textvariable=action, values=list(ACTIONS), state="readonly", width=13).grid(row=i, column=1, padx=6)
            argbox = ttk.Combobox(frame, textvariable=arg)
            argbox.grid(row=i, column=2, sticky="ew")
            record = ttk.Button(frame, text="Record", width=7, command=lambda g=gesture: self._record_keys(g))
            record.grid(row=i, column=3, padx=(6, 0))
            self.record_buttons[gesture] = record
            ttk.Button(frame, text="Test", width=5, command=lambda g=gesture: self.hub.fire(g, test=True)).grid(row=i, column=4, padx=(6, 0))
            action.trace_add("write", lambda *_, g=gesture: self._action_changed(g))
            arg.trace_add("write", lambda *_: self._save_map())
            self.rows[gesture] = (action, arg, argbox)
            self._fill_choices(gesture)

        self.hint = tk.StringVar()
        ttk.Label(frame, textvariable=self.hint, foreground="#888", wraplength=560, justify="left").grid(
            row=len(GESTURES), column=0, columnspan=5, sticky="w", pady=(12, 0)
        )
        self._update_hint()
        access = ttk.Frame(frame)
        access.grid(row=len(GESTURES) + 1, column=0, columnspan=5, sticky="w", pady=(12, 0))
        self.access = tk.StringVar()
        ttk.Label(access, textvariable=self.access).pack(side="left")
        ttk.Button(access, text="Open Accessibility settings", command=self.hub.app.open_accessibility_settings).pack(side="left", padx=8)
        return frame

    # --- mapping ---------------------------------------------------------------------------

    def _check_access(self) -> None:
        allowed = self.hub.app.keystrokes_allowed()
        self.access.set({True: "Keystrokes: allowed", False: "Keystrokes: not allowed yet", None: "Keystrokes: unknown"}[allowed])
        self._access_job = self.top.after(2000, self._check_access)

    def _load_shortcuts(self) -> None:
        try:
            out = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            return
        self.shortcuts = sorted(line.strip() for line in out.splitlines() if line.strip())
        self.hub.post("refill")

    def refill(self) -> None:
        for gesture in self.rows:
            self._fill_choices(gesture)

    def _fill_choices(self, gesture: str) -> None:
        action, _arg, argbox = self.rows[gesture]
        choices = {
            "open app": self.apps,
            "shortcut": self.shortcuts,
            "keystroke": KEYSTROKE_EXAMPLES,
            "applescript": APPLESCRIPT_EXAMPLES,
        }.get(action.get(), [])
        takes_arg = bool(ACTIONS.get(action.get())) and action.get() not in ("microphone", "record", "voice menu")
        argbox.configure(values=choices, state="normal" if takes_arg else "disabled")
        if gesture in self.record_buttons:
            self.record_buttons[gesture].configure(state="normal" if action.get() == "keystroke" else "disabled")

    def _record_keys(self, gesture: str) -> None:
        """Capture the next key combo pressed in this window into the gesture's keystroke."""
        if self.recording_for is not None:
            self._stop_key_recording("cancelled")
            return
        self.recording_for = gesture
        self.record_buttons[gesture].configure(text="Press…")
        self.top.focus_set()
        self.top.bind("<KeyPress>", self._recorded_key)
        self._record_timeout = self.top.after(8000, lambda: self._stop_key_recording("timed out"))

    def _recorded_key(self, event: tk.Event) -> str | None:
        combo = combo_from_key(event.keycode >> 24, event.keysym, event.state)
        if combo is None:
            return None
        gesture = self.recording_for
        self._stop_key_recording(None)
        if gesture is not None:
            self.rows[gesture][1].set(combo)
            self.hub.log(f"{gesture}: recorded keystroke {combo}")
        return "break"

    def _stop_key_recording(self, reason: str | None) -> None:
        if self.recording_for is None:
            return
        self.top.unbind("<KeyPress>")
        self.top.after_cancel(self._record_timeout)
        self.record_buttons[self.recording_for].configure(text="Record")
        if reason:
            self.hub.log(f"{self.recording_for}: key recording {reason}")
        self.recording_for = None

    def _action_changed(self, gesture: str) -> None:
        self._fill_choices(gesture)
        self._save_map()

    def _save_map(self) -> None:
        for gesture, (action, arg, _box) in self.rows.items():
            mapping = self.hub.map.gestures[gesture]
            mapping.action, mapping.arg = action.get(), arg.get()
        self.hub.map.save(self.hub.app.map_path)
        self._update_hint()

    def _update_hint(self) -> None:
        notes = [f"{g}: {ACTIONS[m.action]}" for g, m in self.hub.map.gestures.items() if ACTIONS.get(m.action)]
        if any(m.action in NEEDS_ACCESSIBILITY for m in self.hub.map.gestures.values()):
            notes.append("keystroke: turn Sideband on in Privacy & Security → Accessibility (button below)")
        self.hint.set("Saved automatically. Works while this window is closed.\n" + "\n".join(notes))

    # --- live updates from the launcher ----------------------------------------------------

    def on_button(self, kind: str, code: int | None, tap: bool) -> None:
        if tap:
            self.presses += 1
            self.led.itemconfigure(self.led_dot, fill=ACCENT)
            self.top.after(FLASH_MS, lambda: self.led.itemconfigure(self.led_dot, fill=IDLE))
        self.button_info.set(f"taps {self.presses} · last {kind} (code {code})")

    def on_fired(self, gesture: str) -> None:
        self.fired[gesture] += 1
        self.gesture.set(gesture)
        tile = self.tiles[gesture]
        tile.configure(text=f"{gesture}\n{self.fired[gesture]}", bg=ACCENT, fg="white")
        self.top.after(FLASH_MS * 2, lambda: tile.configure(bg=IDLE, fg="#1d1d1f"))

    def on_charging(self, charging: bool | None) -> None:
        self.state_info.set({True: "⚡ charging", False: "not charging", None: "charging —"}[charging])

    def on_motion(self, sample: Motion, tilt: float, count: int) -> None:
        if count % 5 == 0:
            self.motion_info.set(
                f"Motion: a=({sample.ax:+.1f}, {sample.ay:+.1f}, {sample.az:+.1f}) m/s²  "
                f"g=({sample.gx:+.1f}, {sample.gy:+.1f}, {sample.gz:+.1f}) rad/s  tilt {tilt:+.2f}"
            )

    def on_tick(self, frames_per_s: float | None, mic_on: bool, level_db: float) -> None:
        if frames_per_s is not None:
            self.mic_info.set(f"stream {frames_per_s:.1f} frames/s")
        self.mic_state.set("● Microphone live (not recorded)" if mic_on else "Microphone off")
        self.level["value"] = max(0.0, level_db + 60) if mic_on else 0

    def close(self) -> None:
        self._stop_key_recording(None)
        self.top.after_cancel(self._access_job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()
