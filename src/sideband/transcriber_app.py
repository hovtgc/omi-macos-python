"""Transcriber app: record from the Omi (or pick an audio file), read the transcript, copy or open it.

A window of the Sideband launcher, which owns the recorder, the Whisper worker and the 24-hour audio
limit. Transcripts are Markdown files next to the audio in the recordings folder.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from sideband.recordings import Recording, list_recordings

if TYPE_CHECKING:
    from sideband.ui import Hub

RED = "#e5484d"
RED_DIM = "#f3b0b2"
GREY = "#8a8f98"
AUDIO_TYPES = [("Audio and video", "*.wav *.m4a *.mp3 *.aac *.flac *.ogg *.opus *.mp4 *.mov *.caf *.aiff"), ("All files", "*")]


class TranscriberWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Transcriber")
        self.top.geometry("980x640")
        self.top.minsize(820, 520)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.rows: dict[str, Recording] = {}
        self.shown: str | None = None
        self._build()
        self.refresh(select_newest=True)

    # --- layout ----------------------------------------------------------------------------

    def _build(self) -> None:
        top = self.top
        top.columnconfigure(0, weight=1)
        top.rowconfigure(1, weight=1)

        head = ttk.Frame(top, padding=(18, 16, 18, 8))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(2, weight=1)
        self.button = tk.Canvas(head, width=84, height=84, highlightthickness=0, cursor="hand2")
        self.button.grid(row=0, column=0, rowspan=3, padx=(0, 18))
        self.button.bind("<Button-1>", lambda _e: self.hub.toggle_recording())
        self.timer = tk.StringVar(value="Ready")
        ttk.Label(head, textvariable=self.timer, font=("Helvetica", 28, "bold")).grid(row=0, column=1, columnspan=2, sticky="w")
        self.level = ttk.Progressbar(head, maximum=60, length=320)
        self.level.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)
        self.hint = tk.StringVar()
        ttk.Label(head, textvariable=self.hint, foreground=GREY).grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Label(head, textvariable=self.hub.llm_status, foreground=GREY).grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Button(head, text="Transcribe a file…", command=self._pick_file).grid(row=0, column=3, sticky="ne")
        self._draw_button(False)

        split = ttk.PanedWindow(top, orient="horizontal")
        split.grid(row=1, column=0, sticky="nsew", padx=18, pady=(4, 8))

        left = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(left, columns=("when", "length", "status"), show="headings", selectmode="browse")
        for column, title, width in (("when", "When", 170), ("length", "Length", 60), ("status", "Status", 150)):
            self.table.heading(column, text=title)
            self.table.column(column, width=width, anchor="w", stretch=column == "status")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())
        scroll = ttk.Scrollbar(left, command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table["yscrollcommand"] = scroll.set
        split.add(left, weight=2)

        right = ttk.Frame(split)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(3, weight=2)
        self.text = tk.Text(right, wrap="word", font=("Helvetica", 14), padx=14, pady=12, borderwidth=0, state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(right, command=self.text.yview)
        text_scroll.grid(row=0, column=1, sticky="ns")
        self.text["yscrollcommand"] = text_scroll.set
        actions = ttk.Frame(right)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for label, command in (
            ("🔊 Speak", self._speak),
            ("■", self.hub.speaker.stop),
            ("✨ Summarize", self._summarize),
            ("Copy text", self._copy),
            ("Open", self._open),
            ("Play audio", self._play),
            ("Show in Finder", self._reveal),
        ):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 8))
        self.auto_open = tk.BooleanVar(value=False)
        self.auto_summary = tk.BooleanVar(value=bool(self.hub.settings.get("auto_summary", True)))
        self.speak_new = tk.BooleanVar(value=bool(self.hub.settings.get("speak_callout", True)))
        options = ttk.Frame(right)
        options.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            options, text="Speak a callout after each recording", variable=self.speak_new,
            command=lambda: self.hub.set_setting("speak_callout", self.speak_new.get()),
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="Write a summary and action items", variable=self.auto_summary,
            command=lambda: self.hub.set_setting("auto_summary", self.auto_summary.get()),
        ).pack(side="left", padx=12)

        ask = ttk.Frame(right)
        ask.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        ask.columnconfigure(0, weight=1)
        self.question = tk.StringVar()
        entry = ttk.Entry(ask, textvariable=self.question)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self._ask())
        self.scope = tk.StringVar(value="this recording")
        ttk.Combobox(ask, textvariable=self.scope, values=("this recording", "all recordings"), state="readonly", width=14).grid(row=0, column=1, padx=6)
        ttk.Button(ask, text="Ask", command=self._ask).grid(row=0, column=2)
        self.answer = tk.Text(right, wrap="word", height=7, font=("Helvetica", 13), padx=12, pady=8, borderwidth=0, state="disabled")
        self.answer.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self._set_answer("Ask about a recording, or all of them: “what did I promise?”, “what were the numbers?”. "
                         "Answers come from a model running on this Mac.")
        self.stream_job: int | None = None
        split.add(right, weight=3)

        foot = ttk.Label(
            top,
            text="Transcribed on this Mac with Whisper. Audio deletes itself after 24 hours; transcripts are kept.",
            foreground=GREY,
            padding=(18, 0, 18, 12),
        )
        foot.grid(row=2, column=0, sticky="w")

    def _draw_button(self, recording: bool) -> None:
        c = self.button
        c.delete("all")
        c.create_oval(4, 4, 80, 80, fill="", outline=RED if recording else RED_DIM, width=4)
        if recording:
            c.create_rectangle(28, 28, 56, 56, fill=RED, outline="")
        else:
            c.create_oval(18, 18, 66, 66, fill=RED, outline="")

    # --- data ------------------------------------------------------------------------------

    def refresh(self, select_newest: bool = False, select: str | None = None) -> None:
        busy = self.hub.transcriber.busy
        current = self.table.selection()
        self.table.delete(*self.table.get_children())
        self.rows = {}
        for rec in list_recordings(self.hub.app.recordings_dir):
            if rec.audio is not None and rec.audio == self.hub.rec_path:
                status = "● recording"
            elif rec.audio is not None and rec.audio == busy:
                status = "transcribing…"
            elif rec.transcript is not None:
                status = "ready" if rec.audio is not None else "ready · audio deleted"
            else:
                status = "waiting to transcribe"
            length = "—" if rec.seconds is None else f"{int(rec.seconds) // 60}:{int(rec.seconds) % 60:02d}"
            self.table.insert("", "end", iid=rec.stem, values=(rec.label, length, status))
            self.rows[rec.stem] = rec
        target = select or (current[0] if current else None)
        self.shown = None  # re-read: the file may have gained a summary
        if select_newest and not target and self.rows:
            target = next(iter(self.rows))
        if target and self.table.exists(target):
            self.table.selection_set(target)
            self.table.see(target)
        self._show_selected(force=True)

    def _selected(self) -> Recording | None:
        chosen = self.table.selection()
        return self.rows.get(chosen[0]) if chosen else None

    def _show_selected(self, force: bool = False) -> None:
        rec = self._selected()
        stem = rec.stem if rec else None
        if stem == self.shown and not force:
            return
        self.shown = stem
        if rec is None:
            body = "Record something with your Omi, or pick an audio file to transcribe."
        elif rec.transcript is None:
            body = "Recording…" if rec.audio == self.hub.rec_path else "Transcribing on this Mac…"
        else:
            body = rec.transcript.read_text(encoding="utf-8")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", body)
        self.text.configure(state="disabled")

    # --- assistant ---------------------------------------------------------------------------

    def _set_answer(self, text: str) -> None:
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", text)
        self.answer.configure(state="disabled")

    def _summarize(self) -> None:
        rec = self._need("summarize")
        if rec is None or rec.transcript is None:
            return
        self.show_summary_job(self.hub.summarize(rec.transcript))

    def _speak(self) -> None:
        rec = self._need("speak")
        if rec is None or rec.transcript is None:
            return
        job_id = self.hub.speak_recording(rec.transcript)
        if job_id is not None:
            self.stream_job = job_id
            self._set_answer("🔊 Writing a callout on this Mac…\n\n")

    def show_summary_job(self, job_id: int | None) -> None:
        if job_id is not None:
            self.stream_job = job_id
            self._set_answer("✨ Summarizing on this Mac…\n\n")

    def _ask(self) -> None:
        question = self.question.get().strip()
        if not question:
            return
        rec = self._selected()
        if self.scope.get() == "this recording":
            if rec is None or rec.transcript is None:
                self._set_answer("Pick a transcribed recording first, or ask about all recordings.")
                return
            self.stream_job = self.hub.ask(question, rec.transcript)
        else:
            self.stream_job = self.hub.ask(question, None)
        self._set_answer(f"Q: {question}\n\n")

    def token(self, job_id: int, text: str) -> None:
        if job_id != self.stream_job:
            return
        self.answer.configure(state="normal")
        self.answer.insert("end", text)
        self.answer.see("end")
        self.answer.configure(state="disabled")

    def job_done(self, job_id: int, text: str, error: str, transcript: Path | None) -> None:
        if transcript is not None:
            self.refresh(select=transcript.stem)
        if job_id == self.stream_job and error:
            self.token(job_id, f"\n\n(assistant failed: {error})")

    def transcript_ready(self, wav: Path, transcript: Path | None) -> None:
        self.refresh(select=wav.stem)
        if transcript is not None and self.auto_open.get():
            self.hub.app.open_path(transcript)

    # --- actions ---------------------------------------------------------------------------

    def _need(self, what: str) -> Recording | None:
        rec = self._selected()
        if rec is None:
            self.hub.log(f"transcriber: pick a recording to {what}")
        return rec

    def _copy(self) -> None:
        rec = self._need("copy")
        if rec is None or rec.transcript is None:
            return
        lines = [line for line in rec.transcript.read_text(encoding="utf-8").splitlines() if line.startswith("**[")]
        text = " ".join(line.split("** ", 1)[-1].strip() for line in lines)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)
        self.hub.log(f"transcriber: copied {len(text.split())} words")

    def _open(self) -> None:
        rec = self._need("open")
        if rec is not None and rec.transcript is not None:
            self.hub.app.open_path(rec.transcript)

    def _play(self) -> None:
        rec = self._need("play")
        if rec is None:
            return
        if rec.audio is None:
            self.hub.log(f"{rec.stem}: audio already deleted (24 h limit)")
            return
        self.hub.app.open_path(rec.audio)

    def _reveal(self) -> None:
        rec = self._need("show")
        if rec is not None:
            self.hub.app.open_path(rec.transcript or rec.audio, reveal=True)

    def _pick_file(self) -> None:
        chosen = filedialog.askopenfilename(parent=self.top, title="Transcribe an audio file", filetypes=AUDIO_TYPES)
        if chosen:
            self.hub.import_file(Path(chosen))

    # --- live updates from the launcher ----------------------------------------------------

    def on_tick(self) -> None:
        if self.hub.rec_path is not None:
            span = int(time.monotonic() - self.hub.rec_started)
            self.timer.set(f"● {span // 60}:{span % 60:02d}")
            self.level["value"] = max(0.0, self.hub.rec_level() + 60)
        else:
            queued = self.hub.transcriber.pending()
            self.timer.set(f"Transcribing {queued}…" if queued else "Ready")
            self.level["value"] = 0
        self.hint.set(self.hub.record_hint())

    def recording_changed(self, recording: bool) -> None:
        self._draw_button(recording)
        self.refresh(select_newest=recording)

    def close(self) -> None:
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()
