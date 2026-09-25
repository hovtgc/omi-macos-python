"""Input explorer window. Shows every live pendant input and maps button gestures to Mac actions.

Runs inside Sideband.app (`sideband --via-app ui`) so macOS grants Bluetooth. Tk owns the main
thread; bleak runs on its own asyncio thread and hands events over a queue. Nothing is recorded.
"""

from __future__ import annotations

import array
import json
import asyncio
import math
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from sideband.app import SidebandApp
from sideband.audio import AudioUnavailable, decoder_for
from sideband.game import BOOST, GameWindow
from sideband.inputs import (
    ACTIONS,
    BUTTON_UUID,
    DEVICE_STATE_UUID,
    GESTURES,
    NEEDS_ACCESSIBILITY,
    STORAGE_UUID,
    InputMap,
    button_code,
    combo_from_key,
    button_kind,
    ButtonDecoder,
    input_name,
    installed_apps,
)
from sideband.motion import MOTION_UUID, Tilt, parse_motion
from sideband.voice import VoiceListener, model_path
from sideband.protocol import AUDIO_CODEC_UUID, AUDIO_DATA_UUID, BATTERY_LEVEL_UUID, codec_name, strip_packet

PUMP_MS = 10
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


class Radio(threading.Thread):
    """Owns the Bluetooth session. Reconnects until closed. Audio never crosses into Tk."""

    def __init__(self, address: str | None, events: queue.Queue) -> None:
        super().__init__(daemon=True)
        self.address = address
        self.events = events
        self.codec = "unread"
        self.frames = 0
        self.level_db = -90.0
        self.mic_on = False
        self.pcm_sink = None  # set while voice control listens; gets 16 kHz mono s16 PCM
        self._decoder = None
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._closed = False

    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        from sideband.radio import scan, watch_inputs

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        while not self._closed:
            if not self.address:
                self._post("status", "scanning")
                try:
                    rows = await scan(6.0)
                except Exception as exc:
                    self._post("status", f"scan failed: {exc}")
                    rows = []
                if not rows:
                    self._post("status", "no Omi found, retrying")
                    await self._pause(3.0)
                    continue
                self.address = rows[0][1]
                self._post("device", f"{rows[0][0]}  {self.address}")
            self._post("status", "connecting")
            try:
                await asyncio.wait_for(watch_inputs(self.address, self._on_event, self._stop, skip=()), timeout=None)
                if not self._closed:
                    self._post("status", "disconnected")
            except Exception as exc:
                self._post("status", f"not reachable ({type(exc).__name__}), retrying")
            await self._pause(2.0)

    async def _pause(self, seconds: float) -> None:
        assert self._stop is not None
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _post(self, *event: object) -> None:
        self.events.put((time.monotonic(), *event))

    def _on_event(self, uuid: str, raw: bytes) -> None:
        if uuid == AUDIO_DATA_UUID:
            self._on_audio(raw)
        elif uuid == AUDIO_CODEC_UUID:
            self.codec = codec_name(raw[0]) if raw else "unread"
            self._post("codec", self.codec)
        elif not uuid:
            self._post("status", "connected")
        else:
            self._post("char", uuid, raw)

    def _on_audio(self, raw: bytes) -> None:
        payload = strip_packet(raw)
        if not payload:
            return
        with self._lock:
            self.frames += 1
        if not self.mic_on or self._decoder is None:
            return
        try:
            decoded = self._decoder.decode(payload)
        except Exception:
            return
        sink = self.pcm_sink
        if sink is not None:
            sink(decoded)
        pcm = array.array("h", decoded)
        if pcm:
            rms = math.sqrt(sum(s * s for s in pcm) / len(pcm))
            self.level_db = 20 * math.log10(max(rms, 1.0) / 32768)

    def set_mic(self, on: bool) -> str | None:
        """Turn the live level on or off. Returns an error line when audio cannot be decoded."""
        if on and self._decoder is None:
            try:
                self._decoder = decoder_for(self.codec)
            except AudioUnavailable as exc:
                return str(exc)
        self.mic_on = on
        self.level_db = -90.0
        return None

    def audio_stats(self) -> tuple[int, float]:
        with self._lock:
            return self.frames, self.level_db

    def close(self) -> None:
        self._closed = True
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)


class InputWindow:
    def __init__(self, app: SidebandApp, address: str | None) -> None:
        self.app = app
        self.events: queue.Queue = queue.Queue()
        self.radio = Radio(address, self.events)
        self.map = InputMap.load(app.map_path)
        self.decoder = ButtonDecoder()
        self.game: GameWindow | None = None
        self.voice: VoiceListener | None = None
        self.voice_on = False
        self.voice_heard = ""
        self.apps = installed_apps(APP_FOLDERS)
        self.shortcuts: list[str] = []
        self.presses = 0
        self.state_changes = 0
        self.fired = {g: 0 for g in GESTURES}
        self.last_audio = (0, time.monotonic())
        self.tilt = Tilt()
        self._load_tilt()
        self.motion_at = 0.0
        self.motion_count = 0

        self.root = tk.Tk()
        self.root.title("Sideband · Omi inputs")
        self.root.geometry("1080x720")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._log(f"mappings {app.map_path}")
        if address:
            self.device.set(address)
        threading.Thread(target=self._load_shortcuts, daemon=True).start()

    # --- layout ----------------------------------------------------------------------------

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        top = ttk.Frame(root, padding=(14, 12, 14, 6))
        top.grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar(value="starting")
        self.device = tk.StringVar(value="looking for an Omi…")
        self.codec = tk.StringVar(value="codec —")
        self.battery = tk.StringVar(value="battery —")
        ttk.Label(top, text="Omi", font=("Helvetica", 20, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.device, foreground="#888").pack(side="left", padx=12)
        for var in (self.battery, self.codec, self.status):
            ttk.Label(top, textvariable=var).pack(side="right", padx=8)

        body = ttk.Frame(root, padding=(14, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=2, uniform="col")
        body.columnconfigure(1, weight=3, uniform="col")
        body.rowconfigure(1, weight=1)
        self._build_live(ttk.LabelFrame(body, text="Live inputs", padding=12)).grid(
            row=0, column=0, sticky="nsew", padx=(0, 8)
        )
        self._build_map(ttk.LabelFrame(body, text="Gesture → Mac action", padding=12)).grid(
            row=0, column=1, sticky="nsew", padx=(8, 0)
        )

        logs = ttk.LabelFrame(body, text="Event log", padding=8)
        logs.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 8))
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log = tk.Text(logs, height=8, font=("Menlo", 11), wrap="none", state="disabled", borderwidth=0)
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(logs, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log["yscrollcommand"] = scroll.set

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

        ttk.Label(tiles, text="hold = press ½–2 s, then let go. Holding 3 s powers the pendant off. "
                  "Mapping triple delays double by 0.9 s.",
                  foreground="#888", wraplength=300).grid(row=1, column=0, columnspan=len(GESTURES), sticky="w", pady=(6, 0))
        ttk.Separator(frame).grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)
        self.mic_state = tk.StringVar(value="Microphone off")
        ttk.Label(frame, textvariable=self.mic_state).grid(row=6, column=0, columnspan=2, sticky="w")
        self.level = ttk.Progressbar(frame, maximum=60)
        self.level.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        self.mic_info = tk.StringVar(value="— frames/s")
        ttk.Label(frame, textvariable=self.mic_info, foreground="#888").grid(row=8, column=0, columnspan=2, sticky="w")

        ttk.Separator(frame).grid(row=9, column=0, columnspan=2, sticky="ew", pady=10)
        self.motion_info = tk.StringVar(value="Motion: not streamed by this firmware (tilt falls back to ← →)")
        ttk.Label(frame, textvariable=self.motion_info, wraplength=330).grid(row=12, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.state_info = tk.StringVar(value="device state —")
        ttk.Label(frame, textvariable=self.state_info, foreground="#888").grid(row=10, column=0, columnspan=2, sticky="w")
        games = ttk.Frame(frame)
        games.grid(row=11, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Button(games, text="Play Omi Flap 3D", command=self._open_game).pack(side="left")
        ttk.Button(games, text="Play Voice Flap", command=self._open_voice_game).pack(side="left", padx=8)
        return frame

    def _build_map(self, frame: ttk.LabelFrame) -> ttk.LabelFrame:
        frame.columnconfigure(2, weight=1)
        self.rows: dict[str, tuple[tk.StringVar, tk.StringVar, ttk.Combobox]] = {}
        self.record_buttons: dict[str, ttk.Button] = {}
        self.recording_for: str | None = None
        for i, gesture in enumerate(GESTURES):
            mapping = self.map.gestures[gesture]
            action = tk.StringVar(value=mapping.action)
            arg = tk.StringVar(value=mapping.arg)
            ttk.Label(frame, text=gesture, width=7).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Combobox(frame, textvariable=action, values=list(ACTIONS), state="readonly", width=13).grid(
                row=i, column=1, padx=6
            )
            argbox = ttk.Combobox(frame, textvariable=arg)
            argbox.grid(row=i, column=2, sticky="ew")
            record = ttk.Button(frame, text="Record", width=7, command=lambda g=gesture: self._record_keys(g))
            record.grid(row=i, column=3, padx=(6, 0))
            self.record_buttons[gesture] = record
            ttk.Button(frame, text="Test", width=5, command=lambda g=gesture: self._fire(g, test=True)).grid(
                row=i, column=4, padx=(6, 0)
            )
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
        ttk.Button(access, text="Open Accessibility settings", command=self.app.open_accessibility_settings).pack(
            side="left", padx=8
        )
        self._check_access()
        return frame

    def _check_access(self) -> None:
        allowed = self.app.keystrokes_allowed()
        text = {True: "Keystrokes: allowed", False: "Keystrokes: not allowed yet", None: "Keystrokes: unknown"}
        self.access.set(text[allowed])
        self.root.after(2000, self._check_access)

    # --- mapping ---------------------------------------------------------------------------

    def _load_shortcuts(self) -> None:
        try:
            out = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            return
        self.shortcuts = sorted(line.strip() for line in out.splitlines() if line.strip())
        self.events.put((time.monotonic(), "refill"))

    def _fill_choices(self, gesture: str) -> None:
        action, arg, argbox = self.rows[gesture]
        choices = {
            "open app": self.apps,
            "shortcut": self.shortcuts,
            "keystroke": KEYSTROKE_EXAMPLES,
            "applescript": APPLESCRIPT_EXAMPLES,
        }.get(action.get(), [])
        takes_arg = bool(ACTIONS.get(action.get())) and action.get() != "microphone"
        argbox.configure(values=choices, state="normal" if takes_arg else "disabled")
        if gesture in self.record_buttons:
            self.record_buttons[gesture].configure(state="normal" if action.get() == "keystroke" else "disabled")

    def _record_keys(self, gesture: str) -> None:
        """Capture the next key combo pressed in this window into the gesture's keystroke."""
        if self.recording_for is not None:
            self._stop_recording("cancelled")
            return
        self.recording_for = gesture
        self.record_buttons[gesture].configure(text="Press…")
        self.root.focus_set()
        self.root.bind("<KeyPress>", self._recorded_key)
        self._record_timeout = self.root.after(8000, lambda: self._stop_recording("timed out"))

    def _recorded_key(self, event: tk.Event) -> str | None:
        combo = combo_from_key(event.keycode >> 24, event.keysym, event.state)
        if combo is None:
            return None
        gesture = self.recording_for
        self._stop_recording(None)
        if gesture is not None:
            self.rows[gesture][1].set(combo)
            self._log(f"{gesture}: recorded keystroke {combo}")
        return "break"

    def _stop_recording(self, reason: str | None) -> None:
        if self.recording_for is None:
            return
        self.root.unbind("<KeyPress>")
        self.root.after_cancel(self._record_timeout)
        self.record_buttons[self.recording_for].configure(text="Record")
        if reason:
            self._log(f"{self.recording_for}: key recording {reason}")
        self.recording_for = None

    def _action_changed(self, gesture: str) -> None:
        self._fill_choices(gesture)
        self._save_map()

    def _save_map(self) -> None:
        for gesture, (action, arg, _box) in self.rows.items():
            mapping = self.map.gestures[gesture]
            mapping.action, mapping.arg = action.get(), arg.get()
        self.map.save(self.app.map_path)
        self._update_hint()

    def _update_hint(self) -> None:
        notes = [f"{g}: {ACTIONS[m.action]}" for g, m in self.map.gestures.items() if ACTIONS.get(m.action)]
        if any(m.action in NEEDS_ACCESSIBILITY for m in self.map.gestures.values()):
            notes.append("keystroke: turn Sideband on in Privacy & Security → Accessibility (button below)")
        self.hint.set("Saved automatically.\n" + "\n".join(notes))

    # --- behaviour -------------------------------------------------------------------------

    def _fire(self, gesture: str, test: bool = False) -> None:
        self.fired[gesture] += 1
        self.gesture.set(gesture)
        tile = self.tiles[gesture]
        tile.configure(text=f"{gesture}\n{self.fired[gesture]}", bg=ACCENT, fg="white")
        self.root.after(FLASH_MS * 2, lambda: tile.configure(bg=IDLE, fg="#1d1d1f"))
        mapping = self.map.gestures[gesture]
        prefix = "test " if test else ""
        if mapping.action == "microphone":
            self._toggle_mic()
        else:
            self._log(prefix + self.app.perform(gesture, mapping))

    def _toggle_mic(self) -> None:
        error = self.radio.set_mic(not self.radio.mic_on)
        if error:
            self._log(f"microphone: {error}")
            return
        self.mic_state.set("● Microphone live" if self.radio.mic_on else "Microphone off")
        self._log("microphone live (not recorded)" if self.radio.mic_on else "microphone off")

    def _open_game(self) -> None:
        if self.game is None:
            self.game = GameWindow(self.root, self._game_closed, self._pendant_steer, self._game_key)
            self._log("Omi Flap 3D open: taps flap instead of running actions")

    def _open_voice_game(self) -> None:
        if self.game is not None:
            return
        self.voice_on, self.voice_heard = False, "loading voice model…"
        self.voice = VoiceListener(
            model_path(self.app.support_dir),
            lambda word: self.events.put((time.monotonic(), "voice_cmd", word)),
            lambda text: self.events.put((time.monotonic(), "voice_text", text)),
        )
        self.voice.start()
        self.game = GameWindow(self.root, self._game_closed, voice=True, voice_status=lambda: (self.voice_on, self.voice_heard))
        self._log("Voice Flap open: tap the pendant to unmute, say go left / right / up / down (nothing recorded)")

    def _toggle_voice(self) -> None:
        if self.voice is None:
            return
        if not self.voice_on:
            error = self.radio.set_mic(True)
            if error:
                self.voice_heard = error
                self._log(f"voice: {error}")
                return
            self.voice.reset()
            self.radio.pcm_sink = self.voice.feed
            self.voice_on = True
            self._log("voice: listening")
        else:
            self.radio.pcm_sink = None
            self.radio.set_mic(False)
            self.voice_on = False
            self._log("voice: muted")

    def _pendant_steer(self) -> tuple[float, str] | None:
        if time.monotonic() - self.motion_at > 0.5:
            return None
        axis = "xyz"[self.tilt.axis] + (" inverted" if self.tilt.invert else "")
        return self.tilt.value, f"pendant tilt ({axis}) · C recentre · X axis · I invert"

    def _game_key(self, key: str) -> None:
        if key == "c":
            self.tilt.rest = None
            return
        if key == "x":
            self.tilt.next_axis()
        elif key == "i":
            self.tilt.invert = not self.tilt.invert
        self._save_tilt()

    @property
    def _tilt_path(self) -> Path:
        return self.app.support_dir / "tilt.json"

    def _load_tilt(self) -> None:
        try:
            saved = json.loads(self._tilt_path.read_text(encoding="utf-8"))
            self.tilt.axis = int(saved.get("axis", 0)) % 3
            self.tilt.invert = bool(saved.get("invert", False))
        except (OSError, ValueError):
            pass

    def _save_tilt(self) -> None:
        self._tilt_path.parent.mkdir(parents=True, exist_ok=True)
        self._tilt_path.write_text(json.dumps({"axis": self.tilt.axis, "invert": self.tilt.invert}) + "\n", encoding="utf-8")
        self._log(f"tilt axis {'xyz'[self.tilt.axis]}{' inverted' if self.tilt.invert else ''} saved")

    def _on_motion(self, raw: bytes, at: float) -> None:
        sample = parse_motion(raw)
        if sample is None:
            self._log(f"motion  unknown payload {len(raw)} bytes {raw.hex()}")
            return
        self.tilt.update(sample)
        self.motion_at = at
        self.motion_count += 1
        if self.motion_count % 5 == 0:
            self.motion_info.set(
                f"Motion: a=({sample.ax:+.1f}, {sample.ay:+.1f}, {sample.az:+.1f}) m/s²  "
                f"g=({sample.gx:+.1f}, {sample.gy:+.1f}, {sample.gz:+.1f}) rad/s  tilt {self.tilt.value:+.2f}"
            )

    def _game_closed(self) -> None:
        self.game = None
        self._log("Omi Flap 3D closed")
        if self.voice is not None:
            self.radio.pcm_sink = None
            self.radio.set_mic(False)
            self.voice.close()
            self.voice, self.voice_on = None, False

    def _on_button(self, raw: bytes, at: float) -> None:
        code = button_code(raw)
        kind = button_kind(code)
        tap = kind in ("single", "double")
        if tap:
            self.presses += 1
            self.led.itemconfigure(self.led_dot, fill=ACCENT)
            self.root.after(FLASH_MS, lambda: self.led.itemconfigure(self.led_dot, fill=IDLE))
        self.button_info.set(f"taps {self.presses} · last {kind} (code {code})")
        if self.game is not None:
            if self.voice is not None:  # voice game: one tap mutes / unmutes the mic
                if kind == "single":
                    self._toggle_voice()
            elif tap:  # the game reacts to raw taps at once; no gesture decoding delay
                self.game.flap(BOOST if kind == "double" else 1.0)
            return
        self._log(f"button  {raw.hex()}  {kind}")
        self.decoder.triples = self.map.gestures["triple"].action != "none"
        for gesture in self.decoder.feed(code, at):
            self._fire(gesture)

    def _handle(self, at: float, kind: str, *rest: object) -> None:
        if kind == "status":
            self.status.set(str(rest[0]))
            self._log(f"status  {rest[0]}")
        elif kind == "device":
            self.device.set(str(rest[0]))
        elif kind == "codec":
            self.codec.set(f"codec {rest[0]}")
        elif kind == "voice_cmd":
            if self.game is not None and self.voice_on:
                self.game.command(str(rest[0]))
                self._log(f"voice: {rest[0]}")
        elif kind == "voice_text":
            self.voice_heard = str(rest[0])
        elif kind == "refill":
            for gesture in self.rows:
                self._fill_choices(gesture)
        elif kind == "char":
            uuid, raw = str(rest[0]), bytes(rest[1])  # type: ignore[arg-type]
            if uuid == BUTTON_UUID:
                self._on_button(raw, at)
            elif uuid == MOTION_UUID:
                self._on_motion(raw, at)
            elif uuid == BATTERY_LEVEL_UUID:
                self.battery.set(f"battery {raw[0]}%" if raw else "battery —")
            elif uuid == DEVICE_STATE_UUID:
                self.state_changes += 1
                self.state_info.set(f"device state {raw.hex()} · changes {self.state_changes}")
            elif uuid != STORAGE_UUID:
                self._log(f"{input_name(uuid):8} {raw.hex()}")

    def _pump(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle(*event)
        now = time.monotonic()
        for gesture in self.decoder.poll(now):
            self._fire(gesture)
        frames, level_db = self.radio.audio_stats()
        then_frames, then = self.last_audio
        if now - then >= 1.0:
            self.mic_info.set(f"stream {(frames - then_frames) / (now - then):.1f} frames/s")
            self.last_audio = (frames, now)
        self.level["value"] = max(0.0, level_db + 60) if self.radio.mic_on else 0
        self.root.after(PUMP_MS, self._pump)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self) -> None:
        if self.voice is not None:
            self.voice.close()
        self.radio.close()
        self.root.destroy()

    def run(self) -> int:
        self.radio.start()
        self.root.after(PUMP_MS, self._pump)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.root.mainloop()
        return 0


def run(app: SidebandApp, address: str | None) -> int:
    return InputWindow(app, address).run()
