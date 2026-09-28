"""Sideband launcher: one pendant connection shared by a collection of small apps.

Runs inside Sideband.app (`sideband --via-app ui`, or double-click the app) so macOS grants
Bluetooth. Tk owns the main thread; bleak runs on its own asyncio thread and hands events over a
queue. The launcher owns everything long-lived: the connection, gesture actions (they work with every
app window closed), the recorder, the Whisper worker, the 24-hour audio limit, voice commands, and
the event log. Apps are windows on top: Transcriber, Controls, and the Arcade games.
"""

from __future__ import annotations

import array
import asyncio
import json
import math
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from sideband.app import SidebandApp
from sideband.audio import AudioUnavailable, WavSink, decoder_for, file_to_wav
from sideband.game import GameWindow
from sideband.inputs import (
    BUTTON_UUID,
    CHARGING_UUID,
    STORAGE_UUID,
    ButtonDecoder,
    InputMap,
    battery_text,
    button_code,
    charging_from,
    button_kind,
    input_name,
)
from sideband.motion import MOTION_UUID, Motion, ShakeDetector, Tilt2D, parse_motion
from sideband.protocol import AUDIO_CODEC_UUID, AUDIO_DATA_UUID, BATTERY_LEVEL_UUID, codec_name, strip_packet
from sideband.llm import Doc, Job, LocalLLM, ask_all_messages, ask_messages, clean_summary, pick_context, summary_messages, transcript_text, with_summary
from sideband.llm import callout_messages, callout_of, clean_callout, with_callout
from sideband.speech import Speaker
from sideband.llm import title as transcript_title
from sideband.recordings import list_recordings, new_path
from sideband.transcribe import Transcriber
from sideband.voice import VoiceListener, model_path

PUMP_MS = 10
SWEEP_MS = 10 * 60 * 1000  # check the 24-hour audio limit this often
GREY = "#8a8f98"
APPS = (
    ("transcriber", "🎙", "Transcriber", "Record from your Omi or pick an audio file. Transcribed on this Mac."),
    ("controls", "🎛", "Controls", "Map taps to Mac actions and watch every live input."),
    ("arcade", "🕹", "Arcade", "Sky Ace 1943, Omi Flap 3D, Corn Maze, Star Dodger, Omi Catch, Voice Flap. Played with the pendant."),
    ("bluetooth", "📶", "Bluetooth", "Connect, scan, switch pendants and debug the link."),
)
REQUEST_MS = 400  # how often the launcher checks for `sideband open <app>` requests
MENU_LISTEN_S = 5.0
DEFAULT_SETTINGS = {"auto_summary": True, "speak_callout": True}
MENU_HINT = "say: open transcriber · start recording · summarize that · open arcade · play sky ace · close"


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
        self.recording: WavSink | None = None  # set while a recording runs; decodes on its own
        self._decoder = None
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session: asyncio.Event | None = None  # set to end the current attempt or wait
        self._closed = False
        self.paused = False
        self.connected_at: float | None = None
        self.last_error = ""
        self.attempts = 0

    def run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        from sideband.radio import scan, watch_inputs

        self._loop = asyncio.get_running_loop()
        while not self._closed:
            self._session = asyncio.Event()
            if self.paused:
                self._post("status", "paused")
                await self._session.wait()
                continue
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
            self.attempts += 1
            try:
                await watch_inputs(self.address, self._on_event, self._session, skip=())
                if not self._closed and not self._session.is_set():
                    self.last_error = "link dropped"
                    self._post("status", "disconnected")
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}".rstrip(": ")
                self._post("status", f"not reachable ({type(exc).__name__}), retrying")
            self.connected_at = None
            if not self._session.is_set():
                await self._pause(2.0)

    async def _pause(self, seconds: float) -> None:
        assert self._session is not None
        try:
            await asyncio.wait_for(self._session.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # --- control from the Tk thread --------------------------------------------------------

    def _kick(self) -> None:
        """End the current connection or wait so the loop picks up new settings."""
        if self._loop is not None and self._session is not None:
            self._loop.call_soon_threadsafe(self._session.set)

    def reconnect(self) -> None:
        self.paused = False
        self._kick()

    def use(self, address: str | None) -> None:
        """Switch to another device, or None to scan for the first Omi."""
        self.address, self.paused = address, False
        self._kick()

    def pause(self) -> None:
        self.paused = True
        self._kick()

    def scan_all(self, seconds: float = 8.0) -> None:
        """Scan in the background; posts ("scan_result", rows, error)."""
        if self._loop is None:
            self._post("scan_result", [], "radio not started")
            return
        from sideband.radio import scan_all

        future = asyncio.run_coroutine_threadsafe(scan_all(seconds), self._loop)

        def done(f) -> None:
            try:
                self._post("scan_result", f.result(), "")
            except Exception as exc:
                self._post("scan_result", [], f"{type(exc).__name__}: {exc}")

        future.add_done_callback(done)

    def _post(self, *event: object) -> None:
        self.events.put((time.monotonic(), *event))

    def _on_event(self, uuid: str, raw: bytes) -> None:
        if uuid == AUDIO_DATA_UUID:
            self._on_audio(raw)
        elif uuid == AUDIO_CODEC_UUID:
            self.codec = codec_name(raw[0]) if raw else "unread"
            self._post("codec", self.codec)
        elif not uuid:
            self.connected_at = time.time()
            self.last_error = ""
            self._post("status", "connected")
        else:
            self._post("char", uuid, raw)

    def _on_audio(self, raw: bytes) -> None:
        payload = strip_packet(raw)
        if not payload:
            return
        with self._lock:
            self.frames += 1
            recording = self.recording
        if recording is not None:
            recording.feed(payload)
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
        self._kick()


class Hub:
    def __init__(self, app: SidebandApp, address: str | None, open_app: str | None = None) -> None:
        self.app = app
        self.open_first = open_app
        self.events: queue.Queue = queue.Queue()
        self.radio = Radio(address or self._saved_address(), self.events)
        self.map = InputMap.load(app.map_path)
        self.decoder = ButtonDecoder()
        self.tilt = Tilt2D()
        self._load_tilt()
        self.shaker = ShakeDetector()
        self.last_motion: Motion | None = None
        self.motion_at = 0.0
        self.motion_count = 0
        self.transcriber = Transcriber(lambda wav, md, msg: self.post("transcribed", wav, md, msg))
        self.rec_path: Path | None = None
        self.rec_started = 0.0
        self.voice: VoiceListener | None = None
        self.voice_on = False
        self.voice_heard = ""
        self.controls = None
        self.transcriber_win = None
        self.arcade = None
        self.bluetooth = None
        self.stream_rate: float | None = None
        self.battery_level: int | None = None
        self.charging: bool | None = None
        self.game = None  # the open game window: Flap, Voice Flap or a mini game
        self.game_name = ""
        self.last_tap_at = 0.0
        self.menu_voice: VoiceListener | None = None
        self.menu_until: float | None = None
        self.menu_mic_was_on = False
        self.windows: list[object] = []  # open app windows, most recent last, for "close"
        self.llm: LocalLLM | None = None
        self.job_ids = 0
        self.settings = self._load_settings()
        self.speaker = Speaker()
        self.last_audio = (0, time.monotonic())

        self.root = tk.Tk()
        self.root.title("Sideband")
        self.root.geometry("780x640")
        self.root.minsize(700, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._menus()
        self.log(f"mappings {app.map_path}")
        if self.radio.address:
            self.device.set(self.radio.address)

    # --- launcher window -------------------------------------------------------------------

    def _build(self) -> None:
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        top = ttk.Frame(root, padding=(18, 14, 18, 4))
        top.grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar(value="starting")
        self.device = tk.StringVar(value="looking for an Omi…")
        self.codec = tk.StringVar(value="")
        self.battery = tk.StringVar(value="battery —")
        self.rec_badge = tk.StringVar(value="")
        self.llm_status = tk.StringVar(value="assistant: local, loads on first use")
        ttk.Label(top, text="Sideband", font=("Helvetica", 24, "bold")).pack(side="left")
        ttk.Label(top, text="for Omi", foreground=GREY, font=("Helvetica", 14)).pack(side="left", padx=(6, 0), pady=(8, 0))
        for var in (self.battery, self.status):
            ttk.Label(top, textvariable=var).pack(side="right", padx=8)
        ttk.Label(top, textvariable=self.rec_badge, foreground="#e5484d", font=("Helvetica", 14, "bold")).pack(side="right", padx=8)
        ttk.Label(root, textvariable=self.device, foreground=GREY, padding=(18, 0)).grid(row=1, column=0, sticky="w")
        voice = ttk.Frame(root, padding=(18, 8, 18, 0))
        voice.grid(row=4, column=0, sticky="ew")
        self.menu_button = ttk.Button(voice, text="🎤 Voice  ⌘L", command=self.voice_menu)
        self.menu_button.pack(side="left")
        self.menu_state = tk.StringVar(value=MENU_HINT)
        ttk.Label(voice, textvariable=self.menu_state, foreground=GREY).pack(side="left", padx=10)

        body = ttk.Frame(root, padding=(18, 10))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        cards = ttk.Frame(body)
        cards.grid(row=0, column=0, sticky="ew")
        for i, (key, icon, title, blurb) in enumerate(APPS):
            card = ttk.LabelFrame(cards, padding=12, cursor="hand2")
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=6, pady=6)
            cards.columnconfigure(i % 2, weight=1, uniform="card")
            card.columnconfigure(1, weight=1)
            ttk.Label(card, text=icon, font=("Helvetica", 30)).grid(row=0, column=0, rowspan=2, padx=(0, 12))
            ttk.Label(card, text=title, font=("Helvetica", 16, "bold")).grid(row=0, column=1, sticky="w")
            ttk.Label(card, text=blurb, foreground=GREY, wraplength=240).grid(row=1, column=1, sticky="w")
            ttk.Button(card, text=f"Open  ⌘{i + 1}", command=lambda k=key: self.open(k)).grid(row=0, column=2, rowspan=2, padx=(8, 0))
            for widget in (card, *card.winfo_children()):  # the whole card is clickable
                widget.bind("<Button-1>", lambda _e, k=key: self.open(k), add="+")

        logs = ttk.LabelFrame(body, text="Event log", padding=6)
        logs.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log_text = tk.Text(logs, height=8, font=("Menlo", 11), wrap="none", state="disabled", borderwidth=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(logs, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text["yscrollcommand"] = scroll.set
        ttk.Label(
            root,
            text="Taps keep running their mapped actions with every app closed. Nothing leaves this Mac.",
            foreground=GREY,
            padding=(18, 0, 18, 4),
        ).grid(row=3, column=0, sticky="w")

    def _menus(self) -> None:
        """An Apps menu in the menu bar with ⌘1…⌘4, working from every Sideband window."""
        bar = tk.Menu(self.root)
        apps = tk.Menu(bar, tearoff=False)
        for i, (key, icon, title, _blurb) in enumerate(APPS):
            apps.add_command(label=f"{icon}  {title}", accelerator=f"Command-{i + 1}", command=lambda k=key: self.open(k))
            self.root.bind_all(f"<Command-Key-{i + 1}>", lambda _e, k=key: self.open(k))
        apps.add_separator()
        apps.add_command(label="🎤  Voice command", accelerator="Command-L", command=self.voice_menu)
        self.root.bind_all("<Command-Key-l>", lambda _e: self.voice_menu())
        apps.add_command(label="Show launcher", accelerator="Command-0", command=self.show)
        self.root.bind_all("<Command-Key-0>", lambda _e: self.show())
        bar.add_cascade(label="Apps", menu=apps)
        self.root.configure(menu=bar)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def open(self, key: str) -> None:
        if key == "transcriber":
            from sideband.transcriber_app import TranscriberWindow

            if self.transcriber_win is None:
                self.transcriber_win = TranscriberWindow(self)
            self.transcriber_win.lift()
            self._opened(self.transcriber_win)
        elif key == "controls":
            from sideband.controls import ControlsWindow

            if self.controls is None:
                self.controls = ControlsWindow(self)
            self.controls.lift()
            self._opened(self.controls)
        elif key == "bluetooth":
            from sideband.bluetooth_app import BluetoothWindow

            if self.bluetooth is None:
                self.bluetooth = BluetoothWindow(self)
            self.bluetooth.lift()
            self._opened(self.bluetooth)
        elif key == "arcade":
            from sideband.arcade import ArcadeWindow

            if self.arcade is None:
                self.arcade = ArcadeWindow(self)
            self.arcade.lift()
            self._opened(self.arcade)
        else:
            self.open_game(key)

    def _opened(self, window: object) -> None:
        if window in self.windows:
            self.windows.remove(window)
        self.windows.append(window)

    def window_closed(self, window: object) -> None:
        if window in self.windows:
            self.windows.remove(window)
        if window is self.controls:
            self.controls = None
        elif window is self.transcriber_win:
            self.transcriber_win = None
        elif window is self.arcade:
            self.arcade = None
        elif window is self.bluetooth:
            self.bluetooth = None

    # --- shared services -------------------------------------------------------------------

    def post(self, *event: object) -> None:
        self.events.put((time.monotonic(), *event))

    def log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def fire(self, gesture: str, test: bool = False) -> None:
        if self.controls is not None:
            self.controls.on_fired(gesture)
        mapping = self.map.gestures[gesture]
        if mapping.action == "microphone":
            self.toggle_mic()
        elif mapping.action == "record":
            self.toggle_recording()
        elif mapping.action == "voice menu":
            self.voice_menu()
        else:
            self.log(("test " if test else "") + self.app.perform(gesture, mapping))

    # --- assistant (local LLM) -------------------------------------------------------------

    @property
    def _settings_path(self) -> Path:
        return self.app.support_dir / "settings.json"

    def _load_settings(self) -> dict[str, object]:
        try:
            return {**DEFAULT_SETTINGS, **json.loads(self._settings_path.read_text(encoding="utf-8"))}
        except (OSError, ValueError, TypeError):
            return dict(DEFAULT_SETTINGS)

    def set_setting(self, key: str, value: object) -> None:
        self.settings[key] = value
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(json.dumps(self.settings, indent=2) + "\n", encoding="utf-8")

    def _assistant(self) -> LocalLLM:
        if self.llm is None:
            self.llm = LocalLLM(lambda text: self.post("llm_status", text))
            self.llm.start()
        return self.llm

    def _job(self, messages: list[dict[str, str]], done_kind: str, *extra: object, max_tokens: int = 600) -> int:
        self.job_ids += 1
        job_id = self.job_ids
        self._assistant().submit(
            Job(
                messages,
                lambda token: self.post("llm_token", job_id, token),
                lambda text, error: self.post(done_kind, job_id, text, error, *extra),
                max_tokens=max_tokens,
            )
        )
        return job_id

    def summarize(self, transcript: Path) -> int | None:
        text = transcript_text(transcript.read_text(encoding="utf-8"))
        if not text:
            self.log(f"{transcript.stem}: nothing to summarize")
            return None
        self.llm_status.set("assistant: summarizing…")
        self.log(f"{transcript.stem}: summarizing on this Mac")
        return self._job(summary_messages(text), "llm_summary", transcript)

    def ask(self, question: str, transcript: Path | None) -> int:
        """Ask about one transcript, or (None) about the recent ones, newest first."""
        if transcript is not None:
            messages = ask_messages(question, transcript_text(transcript.read_text(encoding="utf-8")))
        else:
            docs = []
            for rec in list_recordings(self.app.recordings_dir):
                if rec.transcript is not None:
                    markdown = rec.transcript.read_text(encoding="utf-8")
                    docs.append(Doc(transcript_title(markdown), transcript_text(markdown)))
            messages = ask_all_messages(question, pick_context(docs))
        self.llm_status.set("assistant: thinking…")
        return self._job(messages, "llm_answer", max_tokens=500)

    def callout(self, transcript: Path, speak: bool = True) -> int | None:
        """A short spoken summary of one recording, written for the ear, then read aloud."""
        text = transcript_text(transcript.read_text(encoding="utf-8"))
        if not text:
            return None
        self.llm_status.set("assistant: writing the callout…")
        return self._job(callout_messages(text), "llm_callout", transcript, speak, max_tokens=120)

    def speak_recording(self, transcript: Path) -> int | None:
        """Speak a recording's callout, writing one first if it has none."""
        stored = callout_of(transcript.read_text(encoding="utf-8"))
        if stored:
            self.speaker.speak(stored)
            return None
        return self.callout(transcript, speak=True)

    def _on_callout(self, job_id: int, text: str, error: str, transcript: Path, speak: bool) -> None:
        self.llm_status.set("assistant: ready")
        spoken = clean_callout(text)
        if error or not spoken:
            self.log(f"{transcript.stem}: callout failed: {error or 'empty reply'}")
        else:
            transcript.write_text(with_callout(transcript.read_text(encoding="utf-8"), spoken), encoding="utf-8")
            self.log(f"{transcript.stem}: 🔊 {spoken}")
            if speak and self.radio.recording is None:  # never talk over a new recording
                self.speaker.speak(spoken)
        if self.transcriber_win is not None:
            self.transcriber_win.job_done(job_id, spoken, error, transcript)

    def latest_transcript(self) -> Path | None:
        return next((rec.transcript for rec in list_recordings(self.app.recordings_dir) if rec.transcript), None)

    def _on_summary(self, job_id: int, text: str, error: str, transcript: Path) -> None:
        self.llm_status.set("assistant: ready")
        if error or not text:
            self.log(f"{transcript.stem}: summary failed: {error or 'empty reply'}")
        else:
            transcript.write_text(with_summary(transcript.read_text(encoding="utf-8"), clean_summary(text)), encoding="utf-8")
            self.log(f"{transcript.stem}: summary and action items added")
            subprocess.Popen(["osascript", "-e", 'display notification "Summary and action items ready" with title "Omi"'])
        if self.transcriber_win is not None:
            self.transcriber_win.job_done(job_id, text, error, transcript)

    # --- voice menu ------------------------------------------------------------------------

    def voice_menu(self) -> None:
        """Listen for one spoken menu command, up to MENU_LISTEN_S. Pressing again cancels."""
        if self.menu_until is not None:
            self._stop_menu("cancelled")
            return
        if self.voice is not None:
            self.menu_state.set("Voice Flap is using the mic; close it first")
            return
        if self.menu_voice is None:
            self.menu_voice = VoiceListener(
                model_path(self.app.support_dir),
                lambda command: self.post("menu_cmd", command),
                lambda text: self.post("menu_text", text),
                menu=True,
            )
            self.menu_voice.start()
        self.menu_mic_was_on = self.radio.mic_on
        error = self.radio.set_mic(True)
        if error:
            self.menu_state.set(f"voice: {error}")
            return
        if self.status.get() != "connected":
            self.menu_state.set("connect the pendant first (Bluetooth app)")
            self.radio.set_mic(self.menu_mic_was_on)
            return
        self.menu_voice.reset()
        self.radio.pcm_sink = self.menu_voice.feed
        self.menu_until = time.monotonic() + MENU_LISTEN_S
        self.menu_button.configure(text="■ Listening…")
        self.menu_state.set("🎤 listening… " + MENU_HINT.replace("say: ", ""))

    def _stop_menu(self, note: str) -> None:
        if self.menu_until is None:
            return
        self.menu_until = None
        self.radio.pcm_sink = None
        self.radio.set_mic(self.menu_mic_was_on)
        self.menu_button.configure(text="🎤 Voice  ⌘L")
        self.menu_state.set(note)

    def _run_menu(self, command: str) -> None:
        self.log(f"voice menu: {command}")
        self._stop_menu(f"heard “{command.replace(':', ' ')}”")
        kind, _, target = command.partition(":")
        if kind == "open":
            self.open(target)
        elif kind == "play":
            if self.game is not None and self.game_name != target:
                self.game.close()
            self.open_game(target)
        elif kind == "summarize":
            latest = self.latest_transcript()
            self.open("transcriber")
            if latest is None:
                self.log("voice menu: no transcript to summarize yet")
                self.speaker.speak("There's no recording to summarize yet.")
            else:
                self.speak_recording(latest)
                if "<!-- summary -->" not in latest.read_text(encoding="utf-8"):
                    self.summarize(latest)
        elif kind == "record":
            recording = self.radio.recording is not None
            if target == "toggle" or (target == "start") != recording:
                self.toggle_recording()
            self.open("transcriber")
        elif kind == "close":
            if self.game is not None:
                self.game.close()
            elif self.windows:
                self.windows[-1].close()  # type: ignore[attr-defined]
        elif kind == "home":
            self.show()

    def toggle_mic(self) -> None:
        error = self.radio.set_mic(not self.radio.mic_on)
        if error:
            self.log(f"microphone: {error}")
            return
        self.log("microphone live (not recorded)" if self.radio.mic_on else "microphone off")

    def record_hint(self) -> str:
        gestures = [g for g, m in self.map.gestures.items() if m.action == "record"]
        how = f"{' or '.join(gestures)} tap on your Omi" if gestures else "the button"
        verb = "stop" if self.rec_path else "start"
        return f"Click the button or {how} to {verb}."

    def rec_level(self) -> float:
        sink = self.radio.recording
        return sink.level_db if sink is not None else -90.0

    def toggle_recording(self) -> None:
        if self.radio.recording is None:
            folder = self.app.recordings_dir
            folder.mkdir(parents=True, exist_ok=True)
            path = new_path(folder, time.time())
            sink = WavSink(path)
            try:
                sink.open(self.radio.codec)
            except AudioUnavailable as exc:
                self.log(f"record: {exc}")
                return
            self.speaker.stop()  # the pendant would record the Mac talking
            self.radio.recording = sink
            self.rec_path, self.rec_started = path, time.monotonic()
            self.log(f"recording → {path.name}")
        else:
            sink, self.radio.recording = self.radio.recording, None
            sink.close()
            self.rec_path = None
            self.rec_badge.set("")
            self.log(f"recording saved {sink.path.name} ({sink.seconds():.0f}s), transcribing on this Mac")
            self.transcriber.submit(sink.path)
        if self.transcriber_win is not None:
            self.transcriber_win.recording_changed(self.rec_path is not None)

    def import_file(self, source: Path) -> None:
        """Decode any audio file to a 16 kHz WAV in the recordings folder, then transcribe it."""
        folder = self.app.recordings_dir
        folder.mkdir(parents=True, exist_ok=True)
        target = new_path(folder, time.time())
        self.log(f"importing {source.name}")

        def work() -> None:
            try:
                seconds = file_to_wav(source, target)
            except Exception as exc:
                target.unlink(missing_ok=True)
                self.post("imported", source, None, str(exc))
                return
            self.post("imported", source, target, f"{seconds:.0f}s")

        threading.Thread(target=work, daemon=True).start()

    def _on_transcribed(self, wav: Path, transcript: Path | None, message: str) -> None:
        self.log(f"{wav.stem}: {message}")
        if transcript is not None:
            subprocess.Popen(["osascript", "-e", f'display notification "{message}" with title "Omi transcript ready"'])
            if self.settings.get("speak_callout"):
                self.callout(transcript)  # first: short, so it is spoken within seconds
            if self.settings.get("auto_summary"):
                self.summarize(transcript)
        if self.transcriber_win is not None:
            self.transcriber_win.transcript_ready(wav, transcript)

    def _sweep(self) -> None:
        keep = {self.rec_path} if self.rec_path else set()
        for path in self.app.sweep_recordings(keep):
            self.log(f"deleted audio older than 24 h: {path.name}")
        if self.transcriber_win is not None:
            self.transcriber_win.refresh()
        self.root.after(SWEEP_MS, self._sweep)

    def _queue_untranscribed(self) -> None:
        """Recordings whose transcription never finished (app closed) get queued again."""
        for rec in list_recordings(self.app.recordings_dir):
            if rec.audio is not None and rec.transcript is None:
                self.transcriber.submit(rec.audio)

    # --- device memory ---------------------------------------------------------------------

    @property
    def _device_path(self) -> Path:
        return self.app.support_dir / "device.json"

    def _saved_address(self) -> str | None:
        try:
            return json.loads(self._device_path.read_text(encoding="utf-8")).get("address") or None
        except (OSError, ValueError):
            return None

    def use_device(self, address: str | None) -> None:
        """Switch pendants, or forget the saved one (None) so the next Omi found is used."""
        if address is None:
            self._device_path.unlink(missing_ok=True)
            self.device.set("looking for an Omi…")
        else:
            self.device.set(address)
        self.radio.use(address)

    def _remember_address(self) -> None:
        if self.radio.address and self.radio.address != self._saved_address():
            self._device_path.parent.mkdir(parents=True, exist_ok=True)
            self._device_path.write_text(json.dumps({"address": self.radio.address}) + "\n", encoding="utf-8")

    # --- games -----------------------------------------------------------------------------

    def open_game(self, name: str) -> None:
        if self.game is not None:
            self.game.top.lift()
            return
        self.recentre()
        name = "corn" if name == "marble" else name
        if name in ("corn", "dodger", "catch"):
            from sideband.arcade import MiniGameWindow

            self.game = MiniGameWindow(self, name, self._game_closed)
            self.game_name = name
            self.log(f"{name} open: taps, tilt and shakes go to the game")
            return
        if name == "fighter":
            from sideband.skyfighter_view import FighterWindow

            self.game = FighterWindow(self, self._game_closed)
            self.game_name = name
            self.log("Sky Ace 1943: tilt flies, tap fires, shake rolls, hold pauses")
            return
        self.game_name = name
        if name == "voice":
            self._stop_menu(MENU_HINT)
            self.voice_on, self.voice_heard = False, "loading voice model…"
            self.voice = VoiceListener(
                model_path(self.app.support_dir),
                lambda word: self.post("voice_cmd", word),
                lambda text: self.post("voice_text", text),
            )
            self.voice.start()
            self.game = GameWindow(self.root, self._game_closed, voice=True, voice_status=lambda: (self.voice_on, self.voice_heard))
            self.log("Voice Flap open: tap the pendant to unmute, say go left / right / up / down (nothing recorded)")
        else:
            self.game = GameWindow(self.root, self._game_closed, self._pendant_steer, self._game_key)
            self.log("Omi Flap 3D open: taps flap instead of running actions")

    def _toggle_voice(self) -> None:
        if self.voice is None:
            return
        if not self.voice_on:
            error = self.radio.set_mic(True)
            if error:
                self.voice_heard = error
                self.log(f"voice: {error}")
                return
            self.voice.reset()
            self.radio.pcm_sink = self.voice.feed
            self.voice_on = True
            self.log("voice: listening")
        else:
            self.radio.pcm_sink = None
            self.radio.set_mic(False)
            self.voice_on = False
            self.log("voice: muted")

    def _game_closed(self) -> None:
        game, self.game = self.game, None
        if self.arcade is not None:
            self.arcade.lift()
        flight = getattr(game, "game", None)
        if isinstance(game, GameWindow) and flight is not None and getattr(flight, "best", 0):
            self.record_score(self.game_name, float(flight.best))
        if self.voice is not None:
            self.radio.pcm_sink = None
            self.radio.set_mic(False)
            self.voice.close()
            self.voice, self.voice_on = None, False
        self.log("game closed")

    def stick(self) -> tuple[float, float, str] | None:
        """2-axis pendant tilt, or None when no motion arrived in the last half second."""
        if time.monotonic() - self.motion_at > 0.5:
            return None
        return self.tilt.x, self.tilt.y, "pendant tilt · C recentre"

    def latest_motion(self) -> Motion | None:
        return self.last_motion if time.monotonic() - self.motion_at < 0.5 else None

    def recentre(self) -> None:
        self.tilt.rest = None  # the next sample becomes "level"

    def _pendant_steer(self) -> tuple[float, str] | None:
        stick = self.stick()
        return None if stick is None else (stick[0], stick[2])

    def _game_key(self, key: str) -> None:
        if key == "c":
            self.recentre()

    @property
    def _scores_path(self) -> Path:
        return self.app.support_dir / "arcade.json"

    def _scores(self) -> dict[str, float]:
        try:
            return {k: float(v) for k, v in json.loads(self._scores_path.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def best(self, name: str) -> float | None:
        return self._scores().get(name)

    def record_score(self, name: str, score: float, lower_is_better: bool = False) -> None:
        scores = self._scores()
        old = scores.get(name)
        if old is None or (score < old if lower_is_better else score > old):
            scores[name] = score
            self._scores_path.parent.mkdir(parents=True, exist_ok=True)
            self._scores_path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
            self.log(f"{name}: new best {score:g}")
        if self.arcade is not None:
            self.arcade.refresh_scores()

    @property
    def _tilt_path(self) -> Path:
        return self.app.support_dir / "tilt.json"

    def _load_tilt(self) -> None:
        try:
            self.tilt.load(json.loads(self._tilt_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError):
            pass

    def tilt_calibrated(self) -> bool:
        try:
            return bool(json.loads(self._tilt_path.read_text(encoding="utf-8")).get("calibrated"))
        except (OSError, ValueError, AttributeError):
            return False

    def save_tilt(self) -> None:
        self._tilt_path.parent.mkdir(parents=True, exist_ok=True)
        self._tilt_path.write_text(json.dumps({**self.tilt.settings(), "calibrated": True}) + "\n", encoding="utf-8")
        self.log(f"tilt calibration saved {self.tilt.settings()}")

    # --- events ----------------------------------------------------------------------------

    def _on_button(self, raw: bytes, at: float) -> None:
        code = button_code(raw)
        kind = button_kind(code)
        tap = kind in ("single", "double")
        if self.controls is not None:
            self.controls.on_button(kind, code, tap)
        held = kind == "release" and at - self.last_tap_at > 0.6  # a press past the tap threshold
        if tap:
            self.last_tap_at = at
        target = self.game if self.game is not None else self.arcade
        if target is not None:  # games and the Arcade menu own the button while open
            if self.voice is not None and kind == "single" and getattr(self.game, "playing", False):
                self._toggle_voice()  # Voice Flap in play: one tap mutes / unmutes the mic
            elif tap:  # raw taps at once; no gesture decoding delay
                target.on_tap(kind)
            elif held:
                target.on_hold()
            return
        self.log(f"button  {raw.hex()}  {kind}")
        self.decoder.triples = self.map.gestures["triple"].action != "none"
        for gesture in self.decoder.feed(code, at):
            self.fire(gesture)

    def _on_motion(self, raw: bytes, at: float) -> None:
        sample = parse_motion(raw)
        if sample is None:
            self.log(f"motion  unknown payload {len(raw)} bytes {raw.hex()}")
            return
        self.tilt.update(sample)
        self.last_motion, self.motion_at = sample, at
        self.motion_count += 1
        if self.shaker.feed(sample, at):
            self.log("shake")
            if self.game is not None:
                self.game.on_shake()
        if self.arcade is not None:
            self.arcade.on_motion(sample)
        if self.controls is not None:
            self.controls.on_motion(sample, self.tilt.x, self.motion_count)

    def _handle(self, at: float, kind: str, *rest: object) -> None:
        if kind == "status":
            self.status.set(str(rest[0]))
            self.log(f"status  {rest[0]}")
            if self.bluetooth is not None:
                self.bluetooth.add_log(str(rest[0]) + (f" — {self.radio.last_error}" if "not reachable" in str(rest[0]) else ""))
            if rest[0] == "connected":
                self._remember_address()
        elif kind == "scan_result":
            if self.bluetooth is not None:
                self.bluetooth.scan_result(rest[0], str(rest[1]))  # type: ignore[arg-type]
        elif kind == "device":
            self.device.set(str(rest[0]))
        elif kind == "codec":
            self.codec.set(f"codec {rest[0]}")
        elif kind == "voice_cmd":
            if self.game is not None and self.voice_on:
                self.game.command(str(rest[0]))
                self.log(f"voice: {rest[0]}")
        elif kind == "llm_status":
            self.llm_status.set(f"assistant: {rest[0]}")
            self.log(f"assistant: {rest[0]}")
        elif kind == "llm_token":
            if self.transcriber_win is not None:
                self.transcriber_win.token(int(rest[0]), str(rest[1]))  # type: ignore[arg-type]
        elif kind == "llm_summary":
            self._on_summary(int(rest[0]), str(rest[1]), str(rest[2]), rest[3])  # type: ignore[arg-type]
        elif kind == "llm_callout":
            self._on_callout(int(rest[0]), str(rest[1]), str(rest[2]), rest[3], bool(rest[4]))  # type: ignore[arg-type]
        elif kind == "llm_answer":
            self.llm_status.set("assistant: ready")
            if self.transcriber_win is not None:
                self.transcriber_win.job_done(int(rest[0]), str(rest[1]), str(rest[2]), None)  # type: ignore[arg-type]
        elif kind == "menu_cmd":
            if self.menu_until is not None:
                self._run_menu(str(rest[0]))
        elif kind == "menu_text":
            if self.menu_until is not None and rest[0] != "listening":
                self.menu_state.set(f"🎤 heard: {rest[0]}")
        elif kind == "voice_text":
            self.voice_heard = str(rest[0])
        elif kind == "transcribed":
            self._on_transcribed(rest[0], rest[1], str(rest[2]))  # type: ignore[arg-type]
        elif kind == "imported":
            source, target, message = rest
            if target is None:
                self.log(f"import {source.name} failed: {message}")  # type: ignore[union-attr]
            else:
                self.log(f"imported {source.name} ({message}), transcribing on this Mac")  # type: ignore[union-attr]
                self.transcriber.submit(target)  # type: ignore[arg-type]
                if self.transcriber_win is not None:
                    self.transcriber_win.refresh(select=target.stem)  # type: ignore[union-attr]
        elif kind == "refill":
            if self.controls is not None:
                self.controls.refill()
        elif kind == "char":
            uuid, raw = str(rest[0]), bytes(rest[1])  # type: ignore[arg-type]
            if uuid == BUTTON_UUID:
                self._on_button(raw, at)
            elif uuid == MOTION_UUID:
                self._on_motion(raw, at)
            elif uuid == BATTERY_LEVEL_UUID:
                self.battery_level = raw[0] if raw else None
                self.battery.set(battery_text(self.battery_level, self.charging))
            elif uuid == CHARGING_UUID:
                charging = charging_from(raw)
                if charging is not None and charging != self.charging:
                    if self.charging is not None or charging:
                        self.log("pendant plugged in: charging" if charging else "pendant unplugged")
                    self.charging = charging
                self.battery.set(battery_text(self.battery_level, self.charging))
                if self.controls is not None:
                    self.controls.on_charging(self.charging)
            elif uuid != STORAGE_UUID:
                self.log(f"{input_name(uuid):8} {raw.hex()}")

    def _pump(self) -> None:
        self.root.after(PUMP_MS, self._pump)  # first, so an error below cannot stop the loop
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle(*event)
        now = time.monotonic()
        for gesture in self.decoder.poll(now):
            self.fire(gesture)
        if self.menu_until is not None and now > self.menu_until:
            self._stop_menu("didn't catch that · " + MENU_HINT)
        frames, level_db = self.radio.audio_stats()
        then_frames, then = self.last_audio
        rate = None
        if now - then >= 1.0:
            rate = (frames - then_frames) / (now - then)
            self.last_audio = (frames, now)
            self.stream_rate = rate if self.status.get() == "connected" else None
        if self.radio.recording is not None:
            span = int(now - self.rec_started)
            self.rec_badge.set(f"● REC {span // 60}:{span % 60:02d}")
        if self.controls is not None:
            self.controls.on_tick(rate, self.radio.mic_on, level_db)
        if self.transcriber_win is not None:
            self.transcriber_win.on_tick()

    def _check_requests(self) -> None:
        """`sideband open <app>` from a shell, Shortcuts or Raycast drops a request file here."""
        self.root.after(REQUEST_MS, self._check_requests)
        request = self.app.open_request_path
        if request.exists():
            wanted = request.read_text(encoding="utf-8").strip()
            request.unlink(missing_ok=True)
            self.show()
            if wanted and wanted != "launcher":
                self.open(wanted)

    def close(self) -> None:
        self.app.launcher_pid_path.unlink(missing_ok=True)
        if self.radio.recording is not None:  # keep what was captured; it is transcribed next launch
            self.radio.recording.close()
            self.radio.recording = None
        self.transcriber.close()
        if self.menu_voice is not None:
            self.menu_voice.close()
        if self.llm is not None:
            self.llm.close()
        self.speaker.stop()
        if self.voice is not None:
            self.voice.close()
        self.radio.close()
        self.root.destroy()

    def run(self) -> int:
        self.app.launcher_pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.app.launcher_pid_path.write_text(str(os.getpid()), encoding="utf-8")
        self.app.open_request_path.unlink(missing_ok=True)
        self.root.after(REQUEST_MS, self._check_requests)
        self.radio.start()
        self.transcriber.start()
        self._queue_untranscribed()
        self.root.after(0, self._sweep)
        self.root.after(PUMP_MS, self._pump)
        if self.open_first:
            self.root.after(200, lambda: self.open(self.open_first or ""))
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.root.mainloop()
        return 0


def run(app: SidebandApp, address: str | None, open_app: str | None = None) -> int:
    code = Hub(app, address, open_app).run()
    # Bluetooth (CoreBluetooth) and model threads can still be running here, and Python's
    # interpreter teardown then crashes with SIGTRAP ("Python quit unexpectedly"). Everything
    # worth keeping is already on disk, so leave without the teardown.
    import sys

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
