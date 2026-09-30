"""Thought Map: talk into the Omi (or type, or pick an audio file) and each thought is filed into folders.

A window of the Sideband launcher, which owns the recorder, the Whisper worker, the assistant and the
24-hour audio limit. Every thought is a Markdown file in the recordings folder; the AI writes the
folder it belongs in (2 to 3 levels deep) into that file, and this window draws the folders as a tree.
Anything not filed yet waits in the Inbox at the top.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING

from sideband import maturity
from sideband.buckets import SEP, Filed, all_folders, folder_counts, read_bucket, split_path
from sideband.llm import PRESETS, callout_of
from sideband.recordings import Recording, list_recordings

if TYPE_CHECKING:
    from sideband.ui import Hub

RED = "#e5484d"
RED_DIM = "#f3b0b2"
GREY = "#8a8f98"
GREEN = "#2f9e5b"
INBOX = "inbox"
AUDIO_TYPES = [("Audio and video", "*.wav *.m4a *.mp3 *.aac *.flac *.ogg *.opus *.mp4 *.mov *.caf *.aiff"), ("All files", "*")]
SCOPES = ("this thought", "this folder", "everything")

Folder = tuple[str, ...]


def folder_id(folder: Folder) -> str:
    return "dir:" + "\x1f".join(folder)


def id_folder(iid: str) -> Folder | None:
    return tuple(iid[4:].split("\x1f")) if iid.startswith("dir:") else None


class TranscriberWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Thought Map")
        self.top.geometry("1120x720")
        self.top.minsize(900, 560)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.rows: dict[str, Recording] = {}
        self.filings: dict[str, Filed] = {}
        self.ripeness: dict[str, maturity.Maturity] = {}
        self.fresh: set[Folder] = set()  # folders the AI made while this window was open
        self.opened: set[str] | None = None  # folder rows left open; None until the first draw
        self.shown: str | None = None
        self.stream_job: int | None = None
        self._build()
        self.refresh(select_newest=True)

    # --- layout ----------------------------------------------------------------------------

    def _build(self) -> None:
        top = self.top
        top.columnconfigure(0, weight=1)
        top.rowconfigure(3, weight=1)

        head = ttk.Frame(top, padding=(18, 16, 18, 4))
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(2, weight=1)
        self.button = tk.Canvas(head, width=84, height=84, highlightthickness=0, cursor="hand2")
        self.button.grid(row=0, column=0, rowspan=4, padx=(0, 18))
        self.button.bind("<Button-1>", lambda _e: self.hub.toggle_recording())
        self.timer = tk.StringVar(value="Ready")
        ttk.Label(head, textvariable=self.timer, font=("Helvetica", 28, "bold")).grid(row=0, column=1, columnspan=2, sticky="w")
        self.level = ttk.Progressbar(head, maximum=60, length=320)
        self.level.grid(row=1, column=1, columnspan=2, sticky="w", pady=6)
        self.hint = tk.StringVar()
        ttk.Label(head, textvariable=self.hint, foreground=GREY).grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Label(head, textvariable=self.hub.llm_status, foreground=GREY).grid(row=3, column=1, columnspan=2, sticky="w")
        side = ttk.Frame(head)
        side.grid(row=0, column=3, rowspan=4, sticky="ne")
        ttk.Button(side, text="Transcribe a file…", command=self._pick_file).pack(fill="x")
        ttk.Button(side, text="⚙︎ AI settings…", command=self._ai_settings).pack(fill="x", pady=(6, 0))
        self._draw_button(False)

        jot = ttk.Frame(top, padding=(18, 6, 18, 0))
        jot.grid(row=1, column=0, sticky="ew")
        jot.columnconfigure(1, weight=1)
        ttk.Label(jot, text="💭").grid(row=0, column=0, padx=(0, 6))
        self.thought = tk.StringVar()
        jot_entry = ttk.Entry(jot, textvariable=self.thought, font=("Helvetica", 14))
        jot_entry.grid(row=0, column=1, sticky="ew")
        jot_entry.bind("<Return>", lambda _e: self._add_thought())
        ttk.Button(jot, text="Add thought", command=self._add_thought).grid(row=0, column=2, padx=(6, 0))

        self.banner = tk.StringVar(value="Talk or type; each thought is filed into a folder. New folders are marked ✨.")
        self.banner_label = ttk.Label(top, textvariable=self.banner, foreground=GREY, padding=(18, 6, 18, 0))
        self.banner_label.grid(row=2, column=0, sticky="w")

        split = ttk.PanedWindow(top, orient="horizontal")
        split.grid(row=3, column=0, sticky="nsew", padx=18, pady=(6, 8))

        left = ttk.Frame(split)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(left, columns=("when", "status"), show="tree headings", selectmode="browse")
        self.table.heading("#0", text="Folders and thoughts")
        self.table.heading("when", text="When")
        self.table.heading("status", text="")
        self.table.column("#0", width=280, stretch=True)
        self.table.column("when", width=120, anchor="w", stretch=False)
        self.table.column("status", width=110, anchor="w", stretch=False)
        self.table.tag_configure("folder", font=("Helvetica", 13, "bold"))
        self.table.tag_configure("fresh", foreground=GREEN)
        self.table.tag_configure("inbox", foreground=GREY)
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<<TreeviewSelect>>", lambda _e: self._show_selected())
        scroll = ttk.Scrollbar(left, command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table["yscrollcommand"] = scroll.set
        tools = ttk.Frame(left)
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.sort_label = tk.StringVar(value="✨ File the inbox")
        ttk.Button(tools, textvariable=self.sort_label, command=self._file_inbox).pack(side="left")
        ttk.Button(tools, text="Move…", command=self._move).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="Re-file", command=self._refile).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="🌱 Mature", command=self._mature).pack(side="left", padx=(12, 0))
        ttk.Button(tools, text="✅ Make it an action", command=self._to_action).pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="⊞", width=2, command=lambda: self._expand(True)).pack(side="right")
        ttk.Button(tools, text="⊟", width=2, command=lambda: self._expand(False)).pack(side="right", padx=(0, 4))
        split.add(left, weight=2)

        right = ttk.Frame(split)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=3)
        right.rowconfigure(3, weight=2)
        self.text = tk.Text(right, wrap="word", font=("Helvetica", 14), padx=14, pady=12, borderwidth=0, state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")
        self.text.tag_configure("h", font=("Helvetica", 18, "bold"))
        self.text.tag_configure("dim", foreground=GREY)
        self.text.tag_configure("folder", font=("Helvetica", 14, "bold"))
        self.text.tag_configure("card", background="#eef7f0", lmargin1=10, lmargin2=10, rmargin=10, spacing1=2, spacing3=2)
        self.text.tag_configure("action", font=("Helvetica", 15, "bold"), foreground=GREEN, background="#eef7f0", lmargin1=10, lmargin2=10)
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

        ask = ttk.Frame(right)
        ask.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        ask.columnconfigure(0, weight=1)
        self.question = tk.StringVar()
        entry = ttk.Entry(ask, textvariable=self.question)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _e: self._ask())
        self.scope = tk.StringVar(value=SCOPES[0])
        ttk.Combobox(ask, textvariable=self.scope, values=SCOPES, state="readonly", width=12).grid(row=0, column=1, padx=6)
        ttk.Button(ask, text="Ask", command=self._ask).grid(row=0, column=2)
        self.answer = tk.Text(right, wrap="word", height=7, font=("Helvetica", 13), padx=12, pady=8, borderwidth=0, state="disabled")
        self.answer.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self._set_answer("Ask about a thought, a folder, or everything: “what did I promise?”, “what's in my Work ideas?”.")

        self.auto_bucket = tk.BooleanVar(value=bool(self.hub.settings.get("auto_bucket", True)))
        self.auto_mature = tk.BooleanVar(value=bool(self.hub.settings.get("auto_mature", True)))
        self.auto_summary = tk.BooleanVar(value=bool(self.hub.settings.get("auto_summary", True)))
        self.speak_new = tk.BooleanVar(value=bool(self.hub.settings.get("speak_callout", True)))
        options = ttk.Frame(right)
        options.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for n, (text, var, key) in enumerate((
            ("File each thought into a folder", self.auto_bucket, "auto_bucket"),
            ("Suggest next steps as ideas grow", self.auto_mature, "auto_mature"),
            ("Speak a callout", self.speak_new, "speak_callout"),
            ("Write a summary and action items", self.auto_summary, "auto_summary"),
        )):
            ttk.Checkbutton(options, text=text, variable=var, command=lambda v=var, k=key: self.hub.set_setting(k, v.get())).grid(
                row=n // 2, column=n % 2, sticky="w", padx=(0, 16)
            )
        split.add(right, weight=3)

        self.foot = tk.StringVar()
        ttk.Label(top, textvariable=self.foot, foreground=GREY, padding=(18, 0, 18, 12)).grid(row=4, column=0, sticky="w")
        self._update_foot()

    def _update_foot(self) -> None:
        backend = self.hub.backend()
        where = "on this Mac" if backend.local else f"by {backend.describe()} (transcript text is sent there)"
        self.foot.set(f"Transcribed on this Mac with Whisper; filed {where}. Audio deletes itself after 24 hours; thoughts are kept.")

    def _draw_button(self, recording: bool) -> None:
        c = self.button
        c.delete("all")
        c.create_oval(4, 4, 80, 80, fill="", outline=RED if recording else RED_DIM, width=4)
        if recording:
            c.create_rectangle(28, 28, 56, 56, fill=RED, outline="")
        else:
            c.create_oval(18, 18, 66, 66, fill=RED, outline="")

    # --- the map ---------------------------------------------------------------------------

    def _status(self, rec: Recording) -> str:
        if rec.audio is not None and rec.audio == self.hub.rec_path:
            return "● recording"
        if rec.audio is not None and rec.audio == self.hub.transcriber.busy:
            return "transcribing…"
        if rec.transcript is None:
            return "waiting"
        return self.hub.bucket_state(rec.transcript) or ("unsorted" if rec.stem not in self.filings else "")

    def _thought_label(self, rec: Recording) -> str:
        filed = self.filings.get(rec.stem)
        if filed and filed.title:
            return f"💭 {filed.title}"
        return f"🎙 {rec.label}" if rec.audio is not None else f"💭 {rec.label}"

    def refresh(self, select_newest: bool = False, select: str | None = None) -> None:
        table = self.table
        if self.opened is not None or table.get_children():
            self.opened = {iid for iid in self._all_ids() if table.item(iid, "open")}
        current = table.selection()
        table.delete(*table.get_children())
        self.rows, self.filings = {}, {}
        recs = list_recordings(self.hub.app.recordings_dir)
        for rec in recs:
            self.rows[rec.stem] = rec
            filed = read_bucket(rec.transcript)
            if filed is not None:
                self.filings[rec.stem] = filed

        inbox = [rec for rec in recs if rec.stem not in self.filings]
        table.insert("", "end", iid=INBOX, text=f"📥 Inbox", values=(f"{len(inbox)} waiting" if inbox else "empty", ""),
                     open=True, tags=("folder", "inbox"))
        for rec in inbox:
            table.insert(INBOX, "end", iid=rec.stem, text=self._thought_label(rec), values=(self._short(rec), self._status(rec)))

        self.ripeness = self.hub.maturities()
        folders = [f.folder for f in self.filings.values()]
        counts = folder_counts(folders)
        for folder in all_folders(folders):
            iid = folder_id(folder)
            parent = folder_id(folder[:-1]) if len(folder) > 1 else ""
            opened = len(folder) == 1 if self.opened is None else iid in self.opened
            n = counts.get(folder, 0)
            tags = ("folder", "fresh") if folder in self.fresh else ("folder",)
            ripe = self.ripeness.get(maturity.key(folder))
            label = f"📁 {folder[-1]}" + (f"  {ripe.badge}" if ripe else "") + ("  ✨" if folder in self.fresh else "")
            table.insert(parent, "end", iid=iid, text=label, values=(f"{n} thought{'s' * (n != 1)}", ""), open=opened, tags=tags)
        for rec in recs:  # newest first inside each folder, below its subfolders
            filed = self.filings.get(rec.stem)
            if filed is not None:
                table.insert(folder_id(filed.folder), "end", iid=rec.stem, text=self._thought_label(rec),
                             values=(self._short(rec), self._status(rec)))

        unsorted = sum(1 for rec in inbox if rec.transcript is not None)
        self.sort_label.set(f"✨ File the inbox ({unsorted})" if unsorted else "✨ File the inbox")

        target = select or (current[0] if current else None)
        self.shown = None  # re-read: the file may have gained a summary or a folder
        if select_newest and not target and recs:
            target = recs[0].stem
        if target and table.exists(target):
            self._reveal_row(target)
            table.selection_set(target)
        self._show_selected(force=True)

    def _all_ids(self, parent: str = "") -> list[str]:
        out = []
        for iid in self.table.get_children(parent):
            out.append(iid)
            out.extend(self._all_ids(iid))
        return out

    def _reveal_row(self, iid: str) -> None:
        parent = self.table.parent(iid)
        while parent:
            self.table.item(parent, open=True)
            parent = self.table.parent(parent)
        self.table.see(iid)

    def _expand(self, open_: bool) -> None:
        for iid in self._all_ids():
            if iid.startswith("dir:"):
                self.table.item(iid, open=open_)

    @staticmethod
    def _short(rec: Recording) -> str:
        return time.strftime("%a %d %b %H:%M", time.localtime(rec.started))

    def _selected_id(self) -> str | None:
        chosen = self.table.selection()
        return chosen[0] if chosen else None

    def _selected(self) -> Recording | None:
        iid = self._selected_id()
        return self.rows.get(iid) if iid else None

    def _selected_folder(self) -> Folder | None:
        """The folder picked in the tree, or the folder of the picked thought."""
        iid = self._selected_id()
        if iid is None:
            return None
        if iid in self.filings:
            return self.filings[iid].folder
        return id_folder(iid)

    def _write(self, pieces: list[tuple[str, str]]) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for text, tag in pieces:
            self.text.insert("end", text, tag or ())
        self.text.configure(state="disabled")

    def _show_selected(self, force: bool = False) -> None:
        iid = self._selected_id()
        if iid == self.shown and not force:
            return
        self.shown = iid
        rec = self.rows.get(iid) if iid else None
        if iid == INBOX:
            self._show_inbox()
        elif iid and iid.startswith("dir:"):
            self._show_folder(id_folder(iid) or ())
        elif rec is None:
            self._write([("Tap your Omi and talk, type a thought above, or pick an audio file.\n\n", ""),
                         ("Each thought is transcribed on this Mac, then the AI files it into a folder "
                          "2 to 3 levels deep. Folders it makes show up here with a ✨.", "dim")])
        elif rec.transcript is None:
            self._write([("Recording…" if rec.audio == self.hub.rec_path else "Transcribing on this Mac…", "dim")])
        else:
            filed = self.filings.get(rec.stem)
            head = [(f"📁 {SEP.join(filed.folder)}\n", "dim")] if filed else [("📥 Inbox, not filed yet\n", "dim")]
            self._write(head + [("\n", ""), (rec.transcript.read_text(encoding="utf-8"), "")])

    def _show_inbox(self) -> None:
        waiting = [rec for rec in self.rows.values() if rec.stem not in self.filings]
        pieces = [("📥 Inbox\n", "h"), ("Thoughts that are still being recorded, transcribed or filed.\n\n", "dim")]
        if not waiting:
            pieces.append(("Empty: everything is filed.", "dim"))
        for rec in waiting:
            pieces.append((f"{self._thought_label(rec)}  ", ""))
            pieces.append((f"{self._status(rec)}\n", "dim"))
        self._write(pieces)

    def _show_folder(self, folder: Folder) -> None:
        folders = [f.folder for f in self.filings.values()]
        counts = folder_counts(folders)
        children = [f for f in all_folders(folders) if len(f) == len(folder) + 1 and f[: len(folder)] == folder]
        here = [rec for rec in self.rows.values() if (f := self.filings.get(rec.stem)) and f.folder == folder]
        n = counts.get(folder, 0)
        pieces = [(f"📁 {SEP.join(folder)}\n", "h"), (f"{n} thought{'s' * (n != 1)}", "dim")]
        if children:
            pieces.append((f" · {len(children)} folder{'s' * (len(children) != 1)} inside", "dim"))
        pieces.append(("\n\n", ""))
        pieces += self._ripeness_card(folder, n)
        for child in children:
            ripe = self.ripeness.get(maturity.key(child))
            pieces.append((f"📁 {child[-1]}" + (f"  {ripe.badge}" if ripe else ""), "folder"))
            pieces.append((f"   {counts.get(child, 0)}\n", "dim"))
        if children and here:
            pieces.append(("\n", ""))
        for rec in here:
            pieces.append((f"{self._thought_label(rec)}\n", ""))
            said = callout_of(rec.transcript.read_text(encoding="utf-8")) if rec.transcript else None
            pieces.append((f"    {self._short(rec)}" + (f" · {said}" if said else "") + "\n\n", "dim"))
        self._write(pieces)

    def _ripeness_card(self, folder: Folder, count: int) -> list[tuple[str, str]]:
        ripe = self.ripeness.get(maturity.key(folder))
        if folder in self.hub.maturing:
            return [("  🌱 Reading these thoughts for a next step…\n\n", "card")]
        if ripe is None:
            more = maturity.MIN_THOUGHTS - count
            hint = (f"{more} more thought{'s' * (more != 1)} here and the AI suggests a next step on its own, "
                    if more > 0 else "") + "or press 🌱 Mature now."
            return [(f"  🌱 From thought to action: {hint}\n\n", "card")]
        names = {"seed": "Seed", "growing": "Growing", "ready": "Ready for action", "action": "In action"}
        out = [(f"  {ripe.badge} {names.get(ripe.stage, ripe.stage)}", "card")]
        if count > ripe.count and not ripe.acted:
            out.append((f"  ·  {count - ripe.count} new since; 🌱 Mature to update", "card"))
        out.append(("\n", "card"))
        stands = maturity.field(ripe.text, "where it stands")
        if stands:
            out.append((f"  {stands}\n", "card"))
        if ripe.acted:
            out.append((f"  ✅ In Reminders: {ripe.acted}\n", "action"))
        else:
            out.append((f"  → {ripe.next_action}\n", "action"))
            why = maturity.field(ripe.text, "why now")
            if why:
                out.append((f"  {why}\n", "card"))
        questions = [line.strip()[1:].strip() for line in ripe.text.split("Open questions", 1)[-1].splitlines()[1:]
                     if line.strip().startswith(("-", "•", "*"))] if "Open questions" in ripe.text else []
        for q in questions[:3]:
            out.append((f"  ? {q}\n", "card"))
        if not ripe.acted:
            out.append(("  ✅ Make it an action puts the step in Reminders.\n", "card"))
        return out + [("\n", "")]

    # --- maturing ----------------------------------------------------------------------------

    def _mature(self) -> None:
        folder = self._selected_folder()
        if folder is None:
            self.banner.set("Pick a folder (or a thought in it) to mature.")
            return
        job = self.hub.mature(folder)
        if job is not None:
            self.stream_job = job
            self._set_answer(f"🌱 Reading {SEP.join(folder)} for a next step…\n\n")
            self._show_selected(force=True)

    def _to_action(self) -> None:
        folder = self._selected_folder()
        if folder is None:
            return
        ripe = self.ripeness.get(maturity.key(folder))
        if ripe is None:
            self.banner.set("Mature this folder first: 🌱 Mature suggests the next step.")
            return
        error = self.hub.to_action(folder)
        self.banner.set(f"Could not add the reminder: {error}" if error else f"✅ In Reminders: {ripe.next_action}")
        self.refresh(select=folder_id(folder))

    def matured(self, job_id: int, folder: Folder, entry: maturity.Maturity | None, error: str) -> None:
        if entry is not None:
            self.banner.set(f"{entry.badge} {SEP.join(folder)}, next step: {entry.next_action}")
            self.banner_label.configure(foreground=GREEN)
            self.top.after(10000, lambda: self.banner_label.configure(foreground=GREY))
        elif job_id == self.stream_job:
            self.token(job_id, f"\n\n(could not mature it: {error or 'no next action in the reply'})")
        self.refresh()

    # --- filing ----------------------------------------------------------------------------

    def filed(self, transcript: Path, filed: Filed, fresh: Folder | None) -> None:
        """The AI just filed a thought: say where, mark any new folder, and show it."""
        where = SEP.join(filed.folder)
        name = f"“{filed.title}”" if filed.title else "A thought"
        if fresh is not None:
            for depth in range(len(fresh), len(filed.folder) + 1):
                self.fresh.add(filed.folder[:depth])
            self.banner.set(f"✨ New folder {SEP.join(fresh)}: filed {name} in {where}")
        else:
            self.banner.set(f"📁 Filed {name} in {where}")
        self.banner_label.configure(foreground=GREEN)
        self.top.after(8000, lambda: self.banner_label.configure(foreground=GREY))
        self.refresh(select=transcript.stem)

    def _file_inbox(self) -> None:
        count = self.hub.bucket_unsorted()
        self.banner.set(f"Filing {count} thought{'s' * (count != 1)}, oldest first…" if count else "Nothing to file.")

    def _refile(self) -> None:
        rec = self._need("re-file")
        if rec is not None and rec.transcript is not None:
            self.hub.bucket(rec.transcript)
            self.banner.set("Asking the AI where it goes…")

    def _move(self) -> None:
        rec = self._need("move")
        if rec is None or rec.transcript is None:
            return
        filed = self.filings.get(rec.stem)
        dialog = tk.Toplevel(self.top)
        dialog.title("Move thought")
        dialog.transient(self.top)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both")
        ttk.Label(body, text="Folder (Area / Topic / Thread)").grid(row=0, column=0, sticky="w")
        choices = [" / ".join(f) for f in all_folders([f.folder for f in self.filings.values()])]
        where = tk.StringVar(value=" / ".join(filed.folder) if filed else "")
        box = ttk.Combobox(body, textvariable=where, values=choices, width=44)
        box.grid(row=1, column=0, sticky="ew", pady=(2, 10))
        ttk.Label(body, text="Title").grid(row=2, column=0, sticky="w")
        name = tk.StringVar(value=filed.title if filed else "")
        ttk.Entry(body, textvariable=name, width=46).grid(row=3, column=0, sticky="ew", pady=(2, 12))

        def save() -> None:
            folder = split_path(where.get())[:3]
            if not folder:
                return
            self.hub.move_thought(rec.transcript, folder, name.get().strip())  # type: ignore[arg-type]
            dialog.destroy()
            self.banner.set(f"📁 Moved to {SEP.join(folder)}")
            self.refresh(select=rec.stem)

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, sticky="e")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Move", command=save).pack(side="left")
        box.focus_set()
        dialog.bind("<Return>", lambda _e: save())

    def _add_thought(self) -> None:
        path = self.hub.add_thought(self.thought.get())
        if path is not None:
            self.thought.set("")
            self.refresh(select=path.stem)

    def _ai_settings(self) -> None:
        dialog = tk.Toplevel(self.top)
        dialog.title("AI settings")
        dialog.transient(self.top)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both")
        backend = self.hub.backend()
        kind = tk.StringVar(value=backend.kind)
        model = tk.StringVar(value=backend.model)
        base = tk.StringVar(value=backend.base_url)
        key = tk.StringVar()
        ttk.Label(body, text="Which model files your thoughts, summarizes and answers?", font=("Helvetica", 13, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        preset = tk.StringVar(value=next((p[0] for p in PRESETS if p[1] == backend.kind and p[3] == backend.base_url), "Custom"))

        def use_preset(_e: object = None) -> None:
            for label, k, m, url in PRESETS:
                if label == preset.get():
                    kind.set(k), model.set(m), base.set(url)
            refresh_warning()

        ttk.Label(body, text="Preset").grid(row=1, column=0, sticky="w")
        pick = ttk.Combobox(body, textvariable=preset, values=[p[0] for p in PRESETS], state="readonly", width=34)
        pick.grid(row=1, column=1, sticky="ew", pady=2)
        pick.bind("<<ComboboxSelected>>", use_preset)
        ttk.Label(body, text="Runs with").grid(row=2, column=0, sticky="w")
        runs = ttk.Frame(body)
        runs.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Radiobutton(runs, text="MLX on this Mac", value="mlx", variable=kind, command=lambda: refresh_warning()).pack(side="left")
        ttk.Radiobutton(runs, text="OpenAI-compatible server", value="api", variable=kind, command=lambda: refresh_warning()).pack(side="left", padx=8)
        ttk.Label(body, text="Model").grid(row=3, column=0, sticky="w")
        ttk.Entry(body, textvariable=model, width=36).grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(body, text="Server URL").grid(row=4, column=0, sticky="w")
        ttk.Entry(body, textvariable=base, width=36).grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Label(body, text="API key").grid(row=5, column=0, sticky="w")
        ttk.Entry(body, textvariable=key, show="•", width=36).grid(row=5, column=1, sticky="ew", pady=2)
        has_key = bool(self.hub.app.api_key())
        ttk.Label(body, text=("A key is saved in your Keychain; leave blank to keep it." if has_key else
                              "Only for hosted APIs. Kept in your macOS Keychain."), foreground=GREY).grid(row=6, column=1, sticky="w")
        clear_key = tk.BooleanVar(value=False)
        if has_key:
            ttk.Checkbutton(body, text="Remove the saved key", variable=clear_key).grid(row=7, column=1, sticky="w")
        warning = tk.StringVar()
        ttk.Label(body, textvariable=warning, foreground=RED, wraplength=420).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def refresh_warning() -> None:
            from sideband.llm import Backend

            chosen = Backend(kind.get(), model.get(), base.get())
            warning.set("" if chosen.local else f"Transcript text will be sent to {base.get().split('://', 1)[-1].split('/', 1)[0]}.")

        refresh_warning()
        base.trace_add("write", lambda *_a: refresh_warning())

        def save(test: bool = False) -> None:
            new_key = "" if clear_key.get() else (key.get().strip() or None)
            self.hub.set_backend(kind.get(), model.get().strip(), base.get().strip(), new_key)
            self._update_foot()
            dialog.destroy()
            if test:
                self.stream_job = self.hub.test_backend()
                self._set_answer(f"Testing {self.hub.backend().describe()}…\n\n")

        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save and test", command=lambda: save(True)).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save", command=save).pack(side="left")

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
            self._set_answer("🔊 Writing a callout…\n\n")

    def show_summary_job(self, job_id: int | None) -> None:
        if job_id is not None:
            self.stream_job = job_id
            self._set_answer("✨ Summarizing…\n\n")

    def _ask(self) -> None:
        question = self.question.get().strip()
        if not question:
            return
        scope = self.scope.get()
        if scope == "this thought":
            rec = self._selected()
            if rec is None or rec.transcript is None:
                self._set_answer("Pick a thought first, or ask about a folder or everything.")
                return
            self.stream_job = self.hub.ask(question, rec.transcript)
        elif scope == "this folder":
            folder = self._selected_folder()
            if folder is None:
                self._set_answer("Pick a folder (or a thought in it) first.")
                return
            among = [rec.transcript for rec in self.rows.values()
                     if rec.transcript and (f := self.filings.get(rec.stem)) and f.folder[: len(folder)] == folder]
            self.stream_job = self.hub.ask(question, None, among)
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

    # --- actions ---------------------------------------------------------------------------

    def _need(self, what: str) -> Recording | None:
        rec = self._selected()
        if rec is None:
            self.hub.log(f"thought map: pick a thought to {what}")
        return rec

    def _copy(self) -> None:
        rec = self._need("copy")
        if rec is None or rec.transcript is None:
            return
        lines = [line for line in rec.transcript.read_text(encoding="utf-8").splitlines() if line.startswith("**[")]
        text = " ".join(line.split("** ", 1)[-1].strip() for line in lines)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)
        self.hub.log(f"thought map: copied {len(text.split())} words")

    def _open(self) -> None:
        rec = self._need("open")
        if rec is not None and rec.transcript is not None:
            self.hub.app.open_path(rec.transcript)

    def _play(self) -> None:
        rec = self._need("play")
        if rec is None:
            return
        if rec.audio is None:
            self.hub.log(f"{rec.stem}: no audio (typed, or deleted after 24 h)")
            return
        self.hub.app.open_path(rec.audio)

    def _reveal(self) -> None:
        rec = self._need("show")
        if rec is not None:
            self.hub.app.open_path(rec.transcript or rec.audio, reveal=True)  # type: ignore[arg-type]

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
