"""Sideband in the menu bar: the Omi's state at a glance, talk, record and your latest thoughts.

A native NSStatusItem (PyObjC). The menu is rebuilt each time it opens, from the Hub's state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import AppKit
from Foundation import NSObject

from sideband.macui import symbol, target_for
from sideband.recordings import list_recordings
from sideband.thoughtdoc import friendly_when, parse_thought

if TYPE_CHECKING:
    from sideband.ui import Hub


class MenuDelegate(NSObject):
    def menuNeedsUpdate_(self, menu):
        self.bar.fill(menu)


class MenuBar:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self.icon = ""
        self.delegate = MenuDelegate.alloc().init()
        self.delegate.bar = self
        menu = AppKit.NSMenu.alloc().init()
        menu.setDelegate_(self.delegate)
        self.item.setMenu_(menu)
        self.update()

    def update(self) -> None:
        """Called from the Hub's tick: the icon says listening, recording, or just connected."""
        hub = self.hub
        if hub.rec_path is not None:
            name = "record.circle.fill"
        elif hub.talking:
            name = "waveform.circle.fill"
        elif hub.status.get() == "connected":
            name = "waveform"
        else:
            name = "waveform.slash"
        if name != self.icon:
            self.icon = name
            image = symbol(name, 14)
            if image is not None:
                image.setTemplate_(True)
            self.item.button().setImage_(image)

    def _add(self, menu, title: str, callback=None, key: str = "", icon: str | None = None, enabled: bool = True) -> None:
        if callback is None:
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            item.setEnabled_(False)
        else:
            target, action = target_for(callback)
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            item.setTarget_(target)
            item.setEnabled_(enabled)
        if icon:
            item.setImage_(symbol(icon, 13))
        menu.addItem_(item)

    def fill(self, menu) -> None:
        hub = self.hub
        menu.removeAllItems()
        state = hub.status.get()
        battery = f" · {hub.battery_level}%" if hub.battery_level is not None else ""
        self._add(menu, f"Omi {state}{battery}", icon="dot.radiowaves.left.and.right")
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add(menu, "Stop Talking" if hub.talking else "Talk to Sideband", hub.toggle_talk, icon="waveform")
        self._add(menu, "Stop Recording" if hub.rec_path else "Record a Thought", hub.toggle_recording, icon="record.circle")
        self._add(menu, "Open Sideband", lambda: hub.open("thoughts"), icon="brain.head.profile")
        recent = [r for r in list_recordings(hub.app.recordings_dir) if r.transcript is not None][:5]
        if recent:
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            self._add(menu, "Latest thoughts")
            for rec in recent:
                try:
                    doc = parse_thought(rec.transcript.read_text(encoding="utf-8"))
                except OSError:
                    continue
                name = doc.title or doc.snippet(40) or "Thought"
                self._add(menu, f"{name}  —  {friendly_when(rec.started)}", lambda s=rec.stem: self._show(s))
        menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self._add(menu, "Quit Sideband", hub.close, key="q")

    def _show(self, stem: str) -> None:
        self.hub.open("thoughts")
        win = self.hub.transcriber_win
        if hasattr(win, "show_place"):
            win.show_place("all")
            win.refresh(select=stem)

    def close(self) -> None:
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
