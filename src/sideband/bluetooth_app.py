"""Bluetooth app: see the pendant connection, scan, pick a device, reconnect, and debug.

A window of the Sideband launcher, which owns the radio thread. Scanning runs on that thread and
does not drop the current connection. A connected pendant stops advertising, so it will not show
in a scan while it is connected.
"""

from __future__ import annotations

import subprocess
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sideband.ui import Hub

GREY = "#8a8f98"
GREEN, AMBER, RED = "#3ddc84", "#ffb347", "#ff6b6b"
TIPS = (
    "Tap the pendant once to wake it.",
    "Holding the button 3 s powers the pendant off; tap to turn it back on.",
    "Close the Omi phone app if it keeps the pendant busy.",
    "Keep the pendant within a few metres of the Mac.",
    "Bluetooth must be on, and Sideband allowed under Privacy & Security → Bluetooth.",
)


def signal_bars(rssi: int) -> str:
    """-50 dBm or better is four bars; each 10 dB weaker drops one."""
    bars = max(0, min(4, (rssi + 100) // 10 - 1))
    return "▂▄▆█"[:bars].ljust(4, "·")


class BluetoothWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.top = tk.Toplevel(hub.root)
        self.top.title("Sideband · Bluetooth")
        self.top.geometry("820x620")
        self.top.minsize(720, 540)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.scanning = False
        self._build()
        self._tick()

    def _build(self) -> None:
        body = ttk.Frame(self.top, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        head = ttk.Frame(body)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(1, weight=1)
        self.light = tk.Canvas(head, width=22, height=22, highlightthickness=0)
        self.light.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self.headline = tk.StringVar()
        ttk.Label(head, textvariable=self.headline, font=("Helvetica", 20, "bold")).grid(row=0, column=1, sticky="w")
        self.detail = tk.StringVar()
        ttk.Label(head, textvariable=self.detail, foreground=GREY).grid(row=1, column=1, sticky="w")

        info = ttk.LabelFrame(body, text="Connection", padding=10)
        info.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        info.columnconfigure(1, weight=1)
        self.fields: dict[str, tk.StringVar] = {}
        for i, name in enumerate(("Device", "Status", "Connected for", "Attempts", "Last error", "Battery", "Audio stream", "Motion")):
            ttk.Label(info, text=name, foreground=GREY).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 8))
            var = tk.StringVar(value="—")
            ttk.Label(info, textvariable=var).grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 20))
            self.fields[name] = var
        buttons = ttk.Frame(info)
        buttons.grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))
        for label, command in (
            ("Reconnect now", self.hub.radio.reconnect),
            ("Pause", self.hub.radio.pause),
            ("Forget device", self._forget),
            ("Bluetooth settings", lambda: subprocess.Popen(["open", "x-apple.systempreferences:com.apple.BluetoothSettings"])),
            ("Permission", lambda: subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"])),
        ):
            ttk.Button(buttons, text=label, command=command).pack(side="left", padx=(0, 8))

        scan = ttk.Frame(body)
        scan.grid(row=2, column=0, sticky="ew", pady=(14, 4))
        self.scan_button = ttk.Button(scan, text="Scan for devices", command=self._scan)
        self.scan_button.pack(side="left")
        ttk.Button(scan, text="Use selected", command=self._use_selected).pack(side="left", padx=8)
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, text="Show all Bluetooth devices", variable=self.show_all, command=self._render_scan).pack(side="left", padx=8)
        self.scan_note = tk.StringVar(value="A connected pendant stops advertising, so it only shows here while disconnected.")
        ttk.Label(scan, textvariable=self.scan_note, foreground=GREY).pack(side="left", padx=8)

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.grid(row=3, column=0, sticky="nsew")
        found = ttk.Frame(panes)
        found.columnconfigure(0, weight=1)
        found.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(found, columns=("name", "signal", "address"), show="headings", selectmode="browse")
        for column, title, width in (("name", "Name", 150), ("signal", "Signal", 110), ("address", "Address", 280)):
            self.table.heading(column, text=title)
            self.table.column(column, width=width, anchor="w")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<Double-1>", lambda _e: self._use_selected())
        panes.add(found, weight=3)
        tips = ttk.LabelFrame(panes, text="If it won't connect", padding=10)
        for tip in TIPS:
            ttk.Label(tips, text=f"• {tip}", wraplength=220, justify="left").pack(anchor="w", pady=2)
        panes.add(tips, weight=2)

        log = ttk.LabelFrame(body, text="Connection log", padding=6)
        log.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        log.columnconfigure(0, weight=1)
        self.log = tk.Text(log, height=6, font=("Menlo", 11), state="disabled", borderwidth=0)
        self.log.grid(row=0, column=0, sticky="ew")
        self.rows: list[tuple[str, str, int]] = []

    # --- actions ---------------------------------------------------------------------------

    def _scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.scan_button.configure(text="Scanning… 8 s", state="disabled")
        self.add_log("scanning for 8 s")
        self.hub.radio.scan_all(8.0)

    def scan_result(self, rows: list[tuple[str, str, int]], error: str) -> None:
        self.scanning = False
        self.scan_button.configure(text="Scan for devices", state="normal")
        if error:
            self.add_log(f"scan failed: {error}")
            self.scan_note.set("Scan failed. Is Bluetooth on, and is Sideband allowed to use it?")
            return
        self.rows = rows
        omis = sum(1 for name, _a, _r in rows if "omi" in name.lower())
        self.add_log(f"scan found {len(rows)} devices, {omis} Omi")
        self.scan_note.set(f"{omis} Omi found." + ("" if omis else " Tap the pendant to wake it, then scan again."))
        self._render_scan()

    def _render_scan(self) -> None:
        self.table.delete(*self.table.get_children())
        for name, address, rssi in self.rows:
            omi = "omi" in name.lower()
            if not omi and not self.show_all.get():
                continue
            label = f"● {name}" if omi else (name or "(unnamed)")
            self.table.insert("", "end", iid=address, values=(label, f"{signal_bars(rssi)}  {rssi} dBm", address))

    def _use_selected(self) -> None:
        chosen = self.table.selection()
        if not chosen:
            self.add_log("pick a device from the scan first")
            return
        self.hub.use_device(chosen[0])
        self.add_log(f"switching to {chosen[0]}")

    def _forget(self) -> None:
        self.hub.use_device(None)
        self.add_log("forgot the saved pendant; scanning for the first Omi")

    def add_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # --- live status -----------------------------------------------------------------------

    def _tick(self) -> None:
        self._job = self.top.after(500, self._tick)
        radio, hub = self.hub.radio, self.hub
        status = hub.status.get()
        if radio.paused:
            colour, headline = AMBER, "Paused"
        elif status == "connected":
            colour, headline = GREEN, "Connected"
        elif status in ("connecting", "scanning"):
            colour, headline = AMBER, status.capitalize() + "…"
        else:
            colour, headline = RED, "Not connected"
        self.light.delete("all")
        self.light.create_oval(2, 2, 20, 20, fill=colour, outline="")
        self.headline.set(headline)
        self.detail.set(status if headline == "Not connected" else (radio.address or "looking for the first Omi"))
        since = f"{int(time.time() - radio.connected_at)} s" if radio.connected_at else "—"
        frames = hub.stream_rate
        self.fields["Device"].set(radio.address or "any Omi (not chosen)")
        self.fields["Status"].set(status)
        self.fields["Connected for"].set(since)
        self.fields["Attempts"].set(str(radio.attempts))
        self.fields["Last error"].set(radio.last_error or "none")
        self.fields["Battery"].set(hub.battery.get().replace("battery ", ""))
        self.fields["Audio stream"].set("—" if frames is None else f"{frames:.0f} frames/s")
        self.fields["Motion"].set("streaming" if hub.latest_motion() is not None else "none (stock firmware, or asleep)")

    def close(self) -> None:
        self.top.after_cancel(self._job)
        self.top.destroy()
        self.hub.window_closed(self)

    def lift(self) -> None:
        self.top.deiconify()
        self.top.lift()
        self.top.focus_force()
