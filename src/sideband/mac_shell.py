"""Sideband's main window, native AppKit through PyObjC: one window for everything.

Sidebar: your thoughts (Inbox, All thoughts, the folder map) and the apps (Arcade, Controls, Omi).
Middle: the thoughts in the place you picked, with the folder's next step on top. Right: the thought,
drawn as a page. Along the bottom floats the voice bar: tap the Omi or press ⌘L and just talk.

The launcher (`ui.Hub`) owns all state and the assistant. This window only draws it and forwards
clicks, typing and drops back to the Hub. It keeps the same methods the Tk Thought Map had, so the
Hub talks to either.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import AppKit
import objc
from Foundation import NSMakeRect, NSObject

from sideband import maturity
from sideband.buckets import SEP, Filed, all_folders, folder_counts, read_bucket, split_path
from sideband.commands import suggestions
from sideband.llm import PRESETS, Backend
from sideband.macui import (
    W_BOLD, W_MEDIUM, W_SEMIBOLD, attributed, button, card, fill_width, font, height, label, mono_digits, on, para,
    pin, rounded, stack, style, symbol, target_for, width,
)
from sideband.recordings import Recording, list_recordings
from sideband.thoughtdoc import friendly_when, parse_thought

if TYPE_CHECKING:
    from sideband.ui import Hub

C = AppKit.NSColor
THOUGHT_TYPE = "com.sideband.thought"
STAGE_NAMES = {"seed": "Seed", "growing": "Growing", "ready": "Ready for action", "action": "In action"}
PLACE_TITLES = {"inbox": "Inbox", "all": "All Thoughts", "arcade": "Arcade", "controls": "Controls", "pendant": "Omi"}

Folder = tuple[str, ...]


# --- sidebar -------------------------------------------------------------------------------

class SBNode(NSObject):
    """One sidebar row. Kept across refreshes (by key) so the outline remembers what is open."""

    @objc.python_method
    def setup(self, kind: str, key: str, title: str, icon: str, folder: Folder = ()) -> "SBNode":
        self.kind, self.key, self.title, self.icon, self.folder = kind, key, title, icon, folder
        self.children: list[SBNode] = []
        self.count = 0
        self.badge = ""
        self.fresh = False
        return self


class SidebarSource(NSObject):
    def outlineView_numberOfChildrenOfItem_(self, view, item):
        return len(self.shell.roots if item is None else item.children)

    def outlineView_child_ofItem_(self, view, index, item):
        return (self.shell.roots if item is None else item.children)[index]

    def outlineView_isItemExpandable_(self, view, item):
        return bool(item.children)

    def outlineView_isGroupItem_(self, view, item):
        return item.kind == "group"

    def outlineView_shouldSelectItem_(self, view, item):
        return item.kind != "group"

    def outlineView_viewForTableColumn_item_(self, view, column, item):
        return self.shell.sidebar_cell(item)

    def outlineViewSelectionDidChange_(self, note):
        self.shell.sidebar_changed()

    def outlineView_validateDrop_proposedItem_proposedChildIndex_(self, view, info, item, index):
        if item is not None and item.kind == "folder" and info.draggingPasteboard().stringForType_(THOUGHT_TYPE):
            view.setDropItem_dropChildIndex_(item, -1)
            return AppKit.NSDragOperationMove
        return AppKit.NSDragOperationNone

    def outlineView_acceptDrop_item_childIndex_(self, view, info, item, index):
        stem = info.draggingPasteboard().stringForType_(THOUGHT_TYPE)
        if not stem or item is None or item.kind != "folder":
            return False
        return self.shell.drop_thought(str(stem), item.folder)


# --- thought list ---------------------------------------------------------------------------

class ListSource(NSObject):
    def numberOfRowsInTableView_(self, view):
        return len(self.shell.items)

    def tableView_viewForTableColumn_row_(self, view, column, row):
        return self.shell.list_cell(row)

    def tableViewSelectionDidChange_(self, note):
        self.shell.list_changed()

    def tableView_pasteboardWriterForRow_(self, view, row):
        item = AppKit.NSPasteboardItem.alloc().init()
        item.setString_forType_(self.shell.items[row].stem, THOUGHT_TYPE)
        return item


class WindowDelegate(NSObject):
    def windowWillClose_(self, note):
        self.shell.closed()


class MeterView(AppKit.NSView):
    """Five soft bars that follow the mic level: the only moving thing on screen while you talk."""

    def initWithFrame_(self, frame):
        self = objc.super(MeterView, self).initWithFrame_(frame)
        if self is not None:
            self.level = 0.0
            self.active = False
        return self

    @objc.python_method
    def set_level(self, level, active):
        self.level, self.active = level, active
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        bars, gap = 5, 4.0
        w = (bounds.size.width - gap * (bars - 1)) / bars
        shape = (0.45, 0.75, 1.0, 0.75, 0.45)
        color = C.controlAccentColor() if self.active else C.tertiaryLabelColor()
        color.setFill()
        for i in range(bars):
            h = max(w, bounds.size.height * shape[i] * (0.18 + 0.82 * self.level if self.active else 0.18))
            y = (bounds.size.height - h) / 2
            AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(i * (w + gap), y, w, h), w / 2, w / 2).fill()


class ToolbarDelegate(NSObject):
    def toolbarDefaultItemIdentifiers_(self, toolbar):
        return ["record", AppKit.NSToolbarSidebarTrackingSeparatorItemIdentifier, AppKit.NSToolbarFlexibleSpaceItemIdentifier,
                "capture", AppKit.NSToolbarFlexibleSpaceItemIdentifier, "talk", "settings"]

    def toolbarAllowedItemIdentifiers_(self, toolbar):
        return self.toolbarDefaultItemIdentifiers_(toolbar)

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, toolbar, ident, insert):
        return self.shell.toolbar_item(str(ident))


# --- the window ------------------------------------------------------------------------------

class ShellWindow:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.rows: dict[str, Recording] = {}
        self.filings: dict[str, Filed] = {}
        self.docs: dict[str, object] = {}
        self.items: list[Recording] = []
        self.ripeness: dict[str, maturity.Maturity] = {}
        self.fresh: set[Folder] = set()
        self.nodes: dict[str, SBNode] = {}
        self.roots: list[SBNode] = []
        self.place, self.folder = "all", ()
        self.shown: str | None = None
        self.stream_job: int | None = None
        self.answer_job: int | None = None
        self.answer_text = ""
        self.last_tick = 0.0
        self.subtitle = ""
        self.meter_level = -1.0
        self._build()
        self.refresh(select_newest=False)
        self._select_node("all")

    # --- construction --------------------------------------------------------------------

    def _build(self) -> None:
        mask = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable | AppKit.NSWindowStyleMaskMiniaturizable
                | AppKit.NSWindowStyleMaskResizable | AppKit.NSWindowStyleMaskFullSizeContentView)
        win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 1240, 800), mask, AppKit.NSBackingStoreBuffered, False)
        win.setReleasedWhenClosed_(False)
        win.setTitle_("Sideband")
        win.setMinSize_(AppKit.NSMakeSize(960, 600))
        win.setTitlebarAppearsTransparent_(False)
        win.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
        win.setFrameAutosaveName_("SidebandShell")
        if win.frame().origin.x == 0 and win.frame().origin.y == 0:
            win.center()
        self.win = win
        self.delegate = WindowDelegate.alloc().init()
        self.delegate.shell = self
        win.setDelegate_(self.delegate)

        # sidebar
        self.sidebar_source = SidebarSource.alloc().init()
        self.sidebar_source.shell = self
        outline = AppKit.NSOutlineView.alloc().init()
        column = AppKit.NSTableColumn.alloc().initWithIdentifier_("main")
        outline.addTableColumn_(column)
        outline.setOutlineTableColumn_(column)
        outline.setHeaderView_(None)
        outline.setStyle_(AppKit.NSTableViewStyleSourceList)
        outline.setFloatsGroupRows_(False)
        outline.setRowSizeStyle_(AppKit.NSTableViewRowSizeStyleDefault)
        outline.setIndentationPerLevel_(14)
        outline.setDataSource_(self.sidebar_source)
        outline.setDelegate_(self.sidebar_source)
        outline.registerForDraggedTypes_([THOUGHT_TYPE])
        self.outline = outline
        side_scroll = AppKit.NSScrollView.alloc().init()
        side_scroll.setDocumentView_(outline)
        side_scroll.setDrawsBackground_(False)
        side_scroll.setHasVerticalScroller_(True)
        side_scroll.setAutohidesScrollers_(True)
        side_vc = AppKit.NSViewController.alloc().init()
        side_vc.setView_(side_scroll)

        # middle: the list, with the folder's next step on top
        self.list_source = ListSource.alloc().init()
        self.list_source.shell = self
        table = AppKit.NSTableView.alloc().init()
        table.addTableColumn_(AppKit.NSTableColumn.alloc().initWithIdentifier_("thought"))
        table.setHeaderView_(None)
        table.setStyle_(AppKit.NSTableViewStyleInset)
        table.setRowHeight_(66)
        table.setDataSource_(self.list_source)
        table.setDelegate_(self.list_source)
        table.setDraggingSourceOperationMask_forLocal_(AppKit.NSDragOperationMove, True)
        table.setMenu_(self._thought_menu())
        self.table = table
        list_scroll = AppKit.NSScrollView.alloc().init()
        list_scroll.setDocumentView_(table)
        list_scroll.setHasVerticalScroller_(True)
        list_scroll.setAutohidesScrollers_(True)
        list_scroll.setDrawsBackground_(False)
        self.list_title = label("All Thoughts", 22, W_BOLD)
        self.list_title.setFont_(rounded(22, W_BOLD))
        self.list_count = label("", 12, color=C.secondaryLabelColor())
        self.ripe_box = self._ripeness_card()
        head = stack([self.list_title, self.list_count, self.ripe_box], spacing=4, insets=(0, 0, 0, 0))
        head.setCustomSpacing_afterView_(12, self.list_count)
        middle = AppKit.NSView.alloc().init()
        pin(head, middle, top=None, left=18, bottom=None, right=18)
        head.topAnchor().constraintEqualToAnchor_constant_(middle.safeAreaLayoutGuide().topAnchor(), 14).setActive_(True)
        fill_width(self.ripe_box, head)
        pin(list_scroll, middle, top=None, left=0, bottom=0, right=0)
        list_scroll.topAnchor().constraintEqualToAnchor_constant_(head.bottomAnchor(), 8).setActive_(True)
        mid_vc = AppKit.NSViewController.alloc().init()
        mid_vc.setView_(middle)

        # right: the page
        self.detail = AppKit.NSView.alloc().init()
        page = AppKit.NSTextView.scrollableTextView()
        text = page.documentView()
        text.setEditable_(False)
        text.setSelectable_(True)
        text.setDrawsBackground_(False)
        text.setTextContainerInset_(AppKit.NSMakeSize(44, 30))
        self.text = text
        page.setHasVerticalScroller_(True)
        page.setAutohidesScrollers_(True)
        page.setDrawsBackground_(False)
        page.setAutomaticallyAdjustsContentInsets_(True)
        self.page = page
        pin(page, self.detail)
        self.app_pages: dict[str, AppKit.NSView] = {}
        for key, build in (("arcade", self._arcade_page), ("controls", self._controls_page), ("pendant", self._pendant_page)):
            view = build()
            pin(view, self.detail, safe=True)
            view.setHidden_(True)
            self.app_pages[key] = view
        detail_vc = AppKit.NSViewController.alloc().init()
        detail_vc.setView_(self.detail)

        split = AppKit.NSSplitViewController.alloc().init()
        side_item = AppKit.NSSplitViewItem.sidebarWithViewController_(side_vc)
        side_item.setMinimumThickness_(210)
        side_item.setMaximumThickness_(320)
        side_item.setCanCollapse_(True)
        self.list_item = AppKit.NSSplitViewItem.contentListWithViewController_(mid_vc)
        self.list_item.setMinimumThickness_(300)
        self.list_item.setMaximumThickness_(460)
        detail_item = AppKit.NSSplitViewItem.splitViewItemWithViewController_(detail_vc)
        detail_item.setMinimumThickness_(380)
        for item in (side_item, self.list_item, detail_item):
            split.addSplitViewItem_(item)
        split.splitView().setAutosaveName_("SidebandSplit")
        self.split = split

        # the voice bar floats over the bottom of the window
        root = AppKit.NSView.alloc().init()
        pin(split.view(), root)
        self.voice_bar = self._voice_bar()
        root.addSubview_(self.voice_bar)
        self.voice_bar.centerXAnchor().constraintEqualToAnchor_constant_(self.detail.centerXAnchor(), 0).setActive_(True)
        self.voice_bar.bottomAnchor().constraintEqualToAnchor_constant_(root.bottomAnchor(), -18).setActive_(True)
        self.voice_bar.widthAnchor().constraintLessThanOrEqualToAnchor_constant_(self.detail.widthAnchor(), -40).setActive_(True)
        width_pref = self.voice_bar.widthAnchor().constraintEqualToConstant_(620)
        width_pref.setPriority_(999)
        width_pref.setActive_(True)
        root_vc = AppKit.NSViewController.alloc().init()
        root_vc.setView_(root)
        root_vc.addChildViewController_(split)
        self.root_vc = root_vc
        win.setContentViewController_(root_vc)
        win.setContentSize_(AppKit.NSMakeSize(1240, 800))
        win.setFrameUsingName_("SidebandShell")

        self.toolbar_delegate = ToolbarDelegate.alloc().init()
        self.toolbar_delegate.shell = self
        toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_("SidebandToolbar")
        toolbar.setDelegate_(self.toolbar_delegate)
        toolbar.setDisplayMode_(AppKit.NSToolbarDisplayModeIconOnly)
        win.setToolbar_(toolbar)

        self.monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, self._key)
        self._set_voice_idle()

    def toolbar_item(self, ident: str) -> AppKit.NSToolbarItem | None:
        item = AppKit.NSToolbarItem.alloc().initWithItemIdentifier_(ident)
        if ident == "record":
            item.setLabel_("Record")
            item.setToolTip_("Record a long thought (⌘R)")
            item.setImage_(_red(symbol("record.circle", 15, color=C.systemRedColor())))
            target, action = target_for(self.hub.toggle_recording)
            item.setTarget_(target)
            item.setAction_(action)
            self.record_item = item
        elif ident == "capture":
            field = AppKit.NSTextField.alloc().init()
            field.setPlaceholderString_("Write a thought, or ask a question…")
            field.setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
            field.setFont_(font(13))
            field.setTranslatesAutoresizingMaskIntoConstraints_(False)
            width(field, 380)
            on(field, self._capture)
            self.capture = field
            item.setView_(field)
            item.setLabel_("Capture")
        elif ident == "talk":
            item.setLabel_("Talk")
            item.setToolTip_("Talk to Sideband (⌘L)")
            item.setImage_(symbol("waveform", 15))
            target, action = target_for(self.hub.toggle_talk)
            item.setTarget_(target)
            item.setAction_(action)
            self.talk_item = item
        elif ident == "settings":
            item.setLabel_("AI")
            item.setToolTip_("Which AI files and matures your thoughts")
            item.setImage_(symbol("gearshape", 15))
            target, action = target_for(self._ai_settings)
            item.setTarget_(target)
            item.setAction_(action)
        else:
            return None
        return item

    def _key(self, event):
        flags = event.modifierFlags() & AppKit.NSEventModifierFlagDeviceIndependentFlagsMask
        chars = (event.charactersIgnoringModifiers() or "").lower()
        if event.window() is not self.win or flags != AppKit.NSEventModifierFlagCommand:
            return event
        if chars == "l":
            self.hub.toggle_talk()
        elif chars == "n":
            self.win.makeFirstResponder_(self.capture)
        elif chars == "r":
            self.hub.toggle_recording()
        elif chars in "123":
            self._select_node({"1": "all", "2": "arcade", "3": "pendant"}[chars])
        else:
            return event
        return None

    # --- voice bar -------------------------------------------------------------------------

    def _voice_bar(self) -> AppKit.NSView:
        bar = AppKit.NSVisualEffectView.alloc().init()
        bar.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        bar.setBlendingMode_(AppKit.NSVisualEffectBlendingModeWithinWindow)
        bar.setState_(AppKit.NSVisualEffectStateActive)
        bar.setWantsLayer_(True)
        bar.layer().setCornerRadius_(22)
        bar.layer().setMasksToBounds_(True)
        bar.setTranslatesAutoresizingMaskIntoConstraints_(False)

        self.mic = AppKit.NSButton.buttonWithImage_target_action_(symbol("mic.fill", 20, W_MEDIUM), None, None)
        on(self.mic, self.hub.toggle_talk)
        self.mic.setBezelStyle_(AppKit.NSBezelStyleCircular)
        self.mic.setBordered_(False)
        self.mic.setTranslatesAutoresizingMaskIntoConstraints_(False)
        self.mic_bg = AppKit.NSBox.alloc().init()
        self.mic_bg.setBoxType_(AppKit.NSBoxCustom)
        self.mic_bg.setBorderWidth_(0)
        self.mic_bg.setCornerRadius_(22)
        self.mic_bg.setTitlePosition_(AppKit.NSNoTitle)
        self.mic_bg.setContentViewMargins_(AppKit.NSMakeSize(0, 0))
        self.mic_bg.setTranslatesAutoresizingMaskIntoConstraints_(False)
        width(self.mic_bg, 44)
        height(self.mic_bg, 44)
        pin(self.mic, self.mic_bg.contentView())
        self.meter = MeterView.alloc().initWithFrame_(NSMakeRect(0, 0, 38, 26))
        self.meter.setTranslatesAutoresizingMaskIntoConstraints_(False)
        width(self.meter, 38)
        height(self.meter, 26)
        self.caption = label("", 19, W_MEDIUM, wrap=True, lines=3)
        self.reply = label("", 13, color=C.secondaryLabelColor(), wrap=True, lines=8)
        self.hints = label("", 12, color=C.tertiaryLabelColor(), wrap=True, lines=2)
        words = stack([self.caption, self.reply, self.hints], spacing=3)
        for view in (self.caption, self.reply, self.hints):
            fill_width(view, words)
        row = stack([self.mic_bg, self.meter, words], vertical=False, spacing=12, align="center", insets=(14, 16, 14, 20))
        row.setAlignment_(AppKit.NSLayoutAttributeCenterY)
        pin(row, bar)
        return bar

    def _set_voice_idle(self) -> None:
        self.mic_bg.setFillColor_(C.controlAccentColor().colorWithAlphaComponent_(0.16))
        self.mic.setContentTintColor_(C.controlAccentColor())
        self.caption.setStringValue_("Tap your Omi or press ⌘L, then just talk")
        self.caption.setTextColor_(C.secondaryLabelColor())
        self.reply.setStringValue_("")
        self.reply.setHidden_(True)
        self._hints()

    def _hints(self) -> None:
        self.hints.setStringValue_("Try:  " + "   ·   ".join(suggestions(self.hub.voice_context())))

    def talk_state(self, listening: bool, note: str = "") -> None:
        """The Hub started or stopped conversation mode."""
        if listening:
            self.mic_bg.setFillColor_(C.systemRedColor())
            self.mic.setContentTintColor_(C.whiteColor())
            self.caption.setTextColor_(C.labelColor())
            self.caption.setStringValue_(note or "I'm listening…")
            self._hints()
        else:
            self._set_voice_idle()
            if note:
                self.reply.setStringValue_(note)
                self.reply.setHidden_(False)

    def heard(self, text: str, final: bool) -> None:
        """Live caption of what the pendant hears."""
        self.caption.setTextColor_(C.labelColor() if final else C.secondaryLabelColor())
        self.caption.setStringValue_(f"“{text}”")

    def did(self, text: str) -> None:
        """What Sideband did with the phrase (or its answer, streaming)."""
        self.reply.setStringValue_(text)
        self.reply.setHidden_(not text)
        self._hints()

    def stream_answer(self, job_id: int) -> None:
        self.answer_job, self.answer_text = job_id, ""
        self.did("Thinking…")

    # --- sidebar model -------------------------------------------------------------------

    def _node(self, key: str, kind: str, title: str, icon: str, folder: Folder = ()) -> SBNode:
        node = self.nodes.get(key)
        if node is None:
            node = SBNode.alloc().init().setup(kind, key, title, icon, folder)
            self.nodes[key] = node
        node.title, node.icon = title, icon
        node.children = []
        return node

    def _build_nodes(self) -> None:
        inbox_count = sum(1 for r in self.rows.values() if r.stem not in self.filings)
        thoughts = self._node("g:thoughts", "group", "Thoughts", "")
        inbox = self._node("inbox", "inbox", "Inbox", "tray")
        inbox.count = inbox_count
        everything = self._node("all", "all", "All Thoughts", "brain.head.profile")
        everything.count = len(self.rows)
        folders = [f.folder for f in self.filings.values()]
        counts = folder_counts(folders)
        by_path: dict[Folder, SBNode] = {}
        tops = []
        for folder in all_folders(folders):
            node = self._node("f:" + " / ".join(folder), "folder", folder[-1], "folder", folder)
            node.count = counts.get(folder, 0)
            ripe = self.ripeness.get(maturity.key(folder))
            node.badge = ripe.badge if ripe else ""
            node.fresh = folder in self.fresh
            by_path[folder] = node
            (by_path[folder[:-1]].children if len(folder) > 1 else tops).append(node)
        thoughts.children = [inbox, everything]
        map_group = self._node("g:map", "group", "Map", "")
        map_group.children = tops
        apps = self._node("g:apps", "group", "Apps", "")
        apps.children = [self._node("arcade", "arcade", "Arcade", "gamecontroller"),
                         self._node("controls", "controls", "Controls", "hand.tap"),
                         self._node("pendant", "pendant", "Omi", "dot.radiowaves.left.and.right")]
        pendant = self.nodes["pendant"]
        pendant.badge = f"{self.hub.battery_level}%" if self.hub.battery_level is not None else ""
        self.roots = [thoughts] + ([map_group] if tops else []) + [apps]

    def sidebar_cell(self, node: SBNode) -> AppKit.NSView:
        cell = AppKit.NSTableCellView.alloc().init()
        if node.kind == "group":
            text = label(node.title, 11, W_SEMIBOLD, C.secondaryLabelColor())
            pin(text, cell, top=None, left=4, bottom=None, right=4)
            text.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()).setActive_(True)
            cell.setTextField_(text)
            return cell
        tint = C.systemGreenColor() if node.fresh else (C.systemTealColor() if node.kind == "folder" else None)
        image = AppKit.NSImageView.imageViewWithImage_(symbol(node.icon, 14, color=tint) or AppKit.NSImage.alloc().init())
        image.setTranslatesAutoresizingMaskIntoConstraints_(False)
        title = label(node.title + ("  ✨" if node.fresh else ""), 13)
        extra = " ".join(x for x in (node.badge, str(node.count) if node.count and node.kind != "pendant" else "") if x)
        count = label(extra, 12, color=C.tertiaryLabelColor())
        count.setAlignment_(AppKit.NSTextAlignmentRight)
        row = stack([image, title, count], vertical=False, spacing=7, align="center")
        count.setContentHuggingPriority_forOrientation_(750, AppKit.NSLayoutConstraintOrientationHorizontal)
        title.setContentHuggingPriority_forOrientation_(200, AppKit.NSLayoutConstraintOrientationHorizontal)
        pin(row, cell, top=None, left=2, bottom=None, right=6)
        row.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()).setActive_(True)
        cell.setImageView_(image)
        cell.setTextField_(title)
        return cell

    def _select_node(self, key: str) -> None:
        node = self.nodes.get(key)
        if node is None:
            return
        parent = self.outline.parentForItem_(node)
        chain = []
        while parent is not None:
            chain.append(parent)
            parent = self.outline.parentForItem_(parent)
        for item in reversed(chain):
            self.outline.expandItem_(item)
        row = self.outline.rowForItem_(node)
        if row >= 0:
            self.outline.selectRowIndexes_byExtendingSelection_(AppKit.NSIndexSet.indexSetWithIndex_(row), False)
            self.outline.scrollRowToVisible_(row)

    def sidebar_changed(self) -> None:
        row = self.outline.selectedRow()
        node = self.outline.itemAtRow_(row) if row >= 0 else None
        if node is None:
            return
        self.place = node.kind if node.kind != "folder" else "folder"
        self.folder = node.folder
        self._show_place()

    def show_place(self, where: str) -> None:
        """From voice: 'thoughts', 'inbox', 'arcade', 'controls', 'pendant' or a folder path."""
        self.lift()
        key = {"thoughts": "all"}.get(where, where)
        if key in self.nodes:
            self._select_node(key)
            return
        folder = split_path(where)
        for depth in range(1, len(folder)):  # children only exist in the outline once their parent is open
            parent = self.nodes.get("f:" + " / ".join(folder[:depth]))
            if parent is not None:
                self.outline.expandItem_(parent)
        self._select_node("f:" + " / ".join(folder))

    def _show_place(self) -> None:
        app = self.place in self.app_pages
        self.list_item.setCollapsed_(app)
        self.page.setHidden_(app)
        for key, view in self.app_pages.items():
            view.setHidden_(key != self.place)
        if app:
            self._refresh_app_page()
        else:
            self._fill_list()
            self.shown = None
            if self.table.selectedRow() < 0:
                self._render_overview()
        self._hints()

    # --- the list --------------------------------------------------------------------------

    def _fill_list(self, select: str | None = None) -> None:
        recs = list(self.rows.values())
        if self.place == "inbox":
            items = [r for r in recs if r.stem not in self.filings]
        elif self.place == "folder":
            items = [r for r in recs if (f := self.filings.get(r.stem)) and f.folder[: len(self.folder)] == self.folder]
        else:
            items = recs
        self.items = sorted(items, key=lambda r: r.started, reverse=True)
        title = SEP.join(self.folder) if self.place == "folder" else PLACE_TITLES.get(self.place, "All Thoughts")
        self.list_title.setStringValue_(self.folder[-1] if self.place == "folder" else title)
        n = len(self.items)
        where = f"{SEP.join(self.folder[:-1])} · " if self.place == "folder" and len(self.folder) > 1 else ""
        self.list_count.setStringValue_(f"{where}{n} thought{'s' * (n != 1)}")
        self._fill_ripeness()
        current = select or self.shown
        self.table.reloadData()
        index = next((i for i, r in enumerate(self.items) if r.stem == current), None)
        if index is not None:
            self.table.selectRowIndexes_byExtendingSelection_(AppKit.NSIndexSet.indexSetWithIndex_(index), False)
            self.table.scrollRowToVisible_(index)

    def list_cell(self, row: int) -> AppKit.NSView:
        rec = self.items[row]
        doc = self.docs.get(rec.stem)
        filed = self.filings.get(rec.stem)
        status = self._status(rec)
        title_text = (filed.title if filed and filed.title else None) or self._fallback_title(rec, doc)
        title = label(title_text, 13, W_SEMIBOLD)
        when = label(friendly_when(rec.started), 11, color=C.tertiaryLabelColor())
        when.setContentHuggingPriority_forOrientation_(750, AppKit.NSLayoutConstraintOrientationHorizontal)
        when.setContentCompressionResistancePriority_forOrientation_(760, AppKit.NSLayoutConstraintOrientationHorizontal)
        top = stack([title, when], vertical=False, spacing=6, align="center")
        if status:
            snippet_text = status
            snippet_color = C.systemOrangeColor()
        else:
            where = SEP.join(filed.folder) if filed and self.place != "folder" else ""
            gist = doc.snippet(120) if doc else ""
            snippet_text = f"{where}  —  {gist}" if where and gist else (where or gist)
            snippet_color = C.secondaryLabelColor()
        snippet = label(snippet_text, 12, color=snippet_color, wrap=True, lines=2)
        body = stack([top, snippet], spacing=3)
        fill_width(top, body)
        fill_width(snippet, body)
        cell = AppKit.NSTableCellView.alloc().init()
        pin(body, cell, top=None, left=10, bottom=None, right=10)
        body.centerYAnchor().constraintEqualToAnchor_(cell.centerYAnchor()).setActive_(True)
        return cell

    @staticmethod
    def _fallback_title(rec: Recording, doc) -> str:
        if doc is not None and doc.lines:
            words = doc.lines[0][1].split()
            return " ".join(words[:7]) + ("…" if len(words) > 7 else "")
        return "Recording" if rec.audio is not None else "Thought"

    def _status(self, rec: Recording) -> str:
        if rec.audio is not None and rec.audio == self.hub.rec_path:
            return "● Recording…"
        if rec.audio is not None and rec.audio == self.hub.transcriber.busy:
            return "Transcribing…"
        if rec.transcript is None:
            return "Waiting to transcribe"
        state = self.hub.bucket_state(rec.transcript)
        if state:
            return state[:1].upper() + state[1:]
        return "" if rec.stem in self.filings else "Not filed yet"

    def list_changed(self) -> None:
        row = self.table.selectedRow()
        if row < 0 or row >= len(self.items):
            self.shown = None
            self._render_overview()
            return
        rec = self.items[row]
        if rec.stem != self.shown:
            self.shown = rec.stem
            self._render(rec)

    def _selected(self) -> Recording | None:
        row = self.table.clickedRow() if self.table.clickedRow() >= 0 else self.table.selectedRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    # --- the page ---------------------------------------------------------------------------

    def _render(self, rec: Recording) -> None:
        body = []
        wide = para(line=1.25, spacing_after=10)
        filed = self.filings.get(rec.stem)
        if rec.transcript is None:
            body.append(("Transcribing on this Mac…" if rec.audio != self.hub.rec_path else "Recording…",
                         style(20, W_SEMIBOLD, C.secondaryLabelColor())))
            self._page(body)
            return
        doc = parse_thought(rec.transcript.read_text(encoding="utf-8"))
        crumb = SEP.join(filed.folder) if filed else "Inbox · not filed yet"
        body.append((crumb.upper() + "\n", style(11, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_after=6))))
        title = (filed.title if filed and filed.title else None) or self._fallback_title(rec, doc)
        body.append((title + "\n", style(paragraph=para(spacing_after=4), fnt=rounded(28, W_BOLD))))
        length = f" · {int(rec.seconds) // 60}:{int(rec.seconds) % 60:02d}" if rec.seconds else ""
        kind = "Typed" if doc.typed else "Spoken"
        body.append((f"{kind} · {time.strftime('%A %-d %B, %H:%M', time.localtime(rec.started))}{length}\n",
                     style(12, color=C.tertiaryLabelColor(), paragraph=para(spacing_after=22))))
        if doc.callout:
            body.append((f"“{doc.callout}”\n", style(18, W_MEDIUM, C.labelColor(), para(line=1.3, spacing_after=22, indent=14))))
        if doc.summary:
            body.append(("Summary\n", style(13, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_after=4))))
            body.append((doc.summary + "\n", style(15, paragraph=wide)))
        if doc.actions:
            body.append(("Action items\n", style(13, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_before=8, spacing_after=6))))
            for done, action in doc.actions:
                mark = "✓" if done else "○"
                body.append((f"{mark}   {action}\n", style(15, color=C.secondaryLabelColor() if done else C.labelColor(),
                                                           paragraph=para(line=1.2, spacing_after=6, indent=0, head_indent=26))))
        if doc.lines:
            body.append(("What you said\n" if not doc.typed else "What you wrote\n",
                         style(13, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_before=10, spacing_after=8))))
            for stamp, said in doc.lines:
                if not doc.typed:
                    body.append((f"{stamp}   ", style(fnt=mono_digits(12), color=C.tertiaryLabelColor())))
                body.append((said + "\n", style(15, paragraph=para(line=1.3, spacing_after=8, head_indent=0 if doc.typed else 44))))
        elif not doc.said:
            body.append(("Nothing intelligible was heard.\n", style(15, color=C.secondaryLabelColor())))
        self._page(body)

    def _render_overview(self) -> None:
        if self.place == "folder":
            folders = [f.folder for f in self.filings.values()]
            counts = folder_counts(folders)
            children = [f for f in all_folders(folders) if len(f) == len(self.folder) + 1 and f[: len(self.folder)] == self.folder]
            body = [(SEP.join(self.folder[:-1]).upper() + "\n" if len(self.folder) > 1 else "\n",
                     style(11, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_after=6))),
                    (self.folder[-1] + "\n", style(paragraph=para(spacing_after=20), fnt=rounded(30, W_BOLD)))]
            ripe = self.ripeness.get(maturity.key(self.folder))
            if ripe is not None:
                stands = maturity.field(ripe.text, "where it stands")
                if stands:
                    body.append((stands + "\n", style(17, paragraph=para(line=1.3, spacing_after=18))))
                questions = [q.strip()[1:].strip() for q in ripe.text.split("Open questions", 1)[-1].splitlines()[1:]
                             if q.strip().startswith(("-", "•", "*"))] if "Open questions" in ripe.text else []
                if questions:
                    body.append(("Open questions\n", style(13, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_after=6))))
                    for q in questions[:4]:
                        body.append((f"?   {q}\n", style(15, paragraph=para(line=1.2, spacing_after=6, head_indent=26))))
                    body.append(("\n", style(8)))
            if children:
                body.append(("Folders inside\n", style(13, W_SEMIBOLD, C.secondaryLabelColor(), para(spacing_after=6))))
                for child in children:
                    badge = self.ripeness.get(maturity.key(child))
                    body.append((f"📁  {child[-1]}", style(15, W_MEDIUM)))
                    body.append((f"   {counts.get(child, 0)}{'  ' + badge.badge if badge else ''}\n",
                                 style(13, color=C.tertiaryLabelColor(), paragraph=para(spacing_after=6))))
            body.append(("\nPick a thought on the left, or just say one; it lands here.\n",
                         style(13, color=C.tertiaryLabelColor())))
        else:
            n = len(self.items)
            title = PLACE_TITLES.get(self.place, "All Thoughts")
            folders = len({f.folder[0] for f in self.filings.values()})
            waiting = sum(1 for r in self.rows.values() if r.stem not in self.filings and r.transcript is not None)
            if self.place == "inbox":
                lead = "Thoughts still being transcribed or filed."
            elif folders:
                lead = f"{n} thought{'s' * (n != 1)} across {folders} area{'s' * (folders != 1)} of your life."
            else:
                lead = f"{n} thought{'s' * (n != 1)}, none filed yet."
            if waiting:
                lead += f"  Say “file my inbox” to sort {'it' if waiting == 1 else f'all {waiting}'}."
            body = [(title + "\n", style(paragraph=para(spacing_after=10), fnt=rounded(30, W_BOLD))),
                    (lead + "\n\n", style(16, color=C.secondaryLabelColor())),
                    ("Tap your Omi and talk. Anything that isn't a command is kept as a thought, "
                     "transcribed on this Mac, filed into a folder 2 to 3 levels deep, and as a folder grows "
                     "you get a next step to act on.\n", style(15, paragraph=para(line=1.35)))]
        self._page(body)

    def _page(self, pieces: list) -> None:
        self.text.textStorage().setAttributedString_(attributed(pieces))
        self.text.scrollRangeToVisible_((0, 0))

    # --- next step card -------------------------------------------------------------------------

    def _ripeness_card(self) -> AppKit.NSView:
        self.ripe_stage = label("", 12, W_SEMIBOLD, C.systemGreenColor())
        self.ripe_action = label("", 14, W_SEMIBOLD, wrap=True, lines=4)
        self.ripe_why = label("", 12, color=C.secondaryLabelColor(), wrap=True, lines=3)
        self.mature_button = button("Think it through", self._mature, icon="leaf", size="small")
        self.act_button = button("Make it an action", self._to_action, icon="checkmark.circle", size="small")
        buttons = stack([self.mature_button, self.act_button], vertical=False, spacing=8)
        inner = stack([self.ripe_stage, self.ripe_action, self.ripe_why, buttons], spacing=5)
        for view in (self.ripe_action, self.ripe_why):
            fill_width(view, inner)
        inner.setCustomSpacing_afterView_(10, self.ripe_why)
        return card(inner, C.systemGreenColor().colorWithAlphaComponent_(0.10), radius=12, pad=12)

    def _fill_ripeness(self) -> None:
        if self.place != "folder":
            self.ripe_box.setHidden_(True)
            return
        self.ripe_box.setHidden_(False)
        ripe = self.ripeness.get(maturity.key(self.folder))
        count = sum(1 for f in self.filings.values() if f.folder[: len(self.folder)] == self.folder)
        if self.folder in self.hub.maturing:
            self.ripe_stage.setStringValue_("🌱  THINKING IT THROUGH…")
            self.ripe_action.setStringValue_("Reading every thought in this folder")
            self.ripe_why.setStringValue_("")
        elif ripe is None:
            more = maturity.MIN_THOUGHTS - count
            self.ripe_stage.setStringValue_("🌱  FROM THOUGHT TO ACTION")
            self.ripe_action.setStringValue_("What's the next step here?")
            self.ripe_why.setStringValue_(
                (f"After {more} more thought{'s' * (more != 1)} I'll suggest one on my own. " if more > 0 else "")
                + "Or say “what's next?”")
        else:
            fresh = count - ripe.count
            self.ripe_stage.setStringValue_(f"{ripe.badge}  {STAGE_NAMES.get(ripe.stage, ripe.stage).upper()}"
                                            + (f"  ·  {fresh} NEW SINCE" if fresh > 0 and not ripe.acted else ""))
            self.ripe_action.setStringValue_(f"✓ In Reminders: {ripe.acted}" if ripe.acted else ripe.next_action)
            self.ripe_why.setStringValue_(maturity.field(ripe.text, "why now"))
        self.act_button.setHidden_(ripe is None or bool(ripe.acted))
        self.ripe_why.setHidden_(not self.ripe_why.stringValue())

    def _mature(self) -> None:
        if self.place == "folder":
            self.hub.mature(self.folder)
            self._fill_ripeness()

    def _to_action(self) -> None:
        if self.place != "folder":
            return
        error = self.hub.to_action(self.folder)
        self.did(f"Couldn't add the reminder: {error}" if error else "✓ Added to Reminders")
        self.refresh()

    # --- app pages ----------------------------------------------------------------------------------

    def _page_frame(self, title: str, lead: str, content: list) -> AppKit.NSView:
        head = label(title, 30, W_BOLD)
        head.setFont_(rounded(30, W_BOLD))
        sub = label(lead, 15, color=C.secondaryLabelColor(), wrap=True)
        column = stack([head, sub, *content], spacing=10, insets=(34, 44, 120, 44))
        column.setCustomSpacing_afterView_(26, sub)
        fill_width(sub, column, 44)
        view = AppKit.NSView.alloc().init()
        pin(column, view, bottom=None)
        return view

    def _arcade_page(self) -> AppKit.NSView:
        from sideband.arcade import GAMES

        grid_rows, row = [], []
        for key, title, how, colors, _icon in GAMES:
            name = label(title.title(), 16, W_BOLD, C.whiteColor())
            blurb = label(how, 12, color=C.whiteColor().colorWithAlphaComponent_(0.85), wrap=True, lines=2)
            play = button("Play", lambda k=key: self.hub.open_game(k), icon="play.fill", size="small")
            inner = stack([name, blurb, play], spacing=6)
            fill_width(blurb, inner)
            tile = card(inner, _hex(colors[1]), radius=14, pad=14)
            width(tile, 230)
            row.append(tile)
            if len(row) == 3:
                grid_rows.append(stack(row, vertical=False, spacing=14, align="top"))
                row = []
        if row:
            grid_rows.append(stack(row, vertical=False, spacing=14, align="top"))
        return self._page_frame("Arcade", "Say “play sky ace”, “let's play corn maze”, or pick one. In a game, say “exit game” or “pause”.",
                                grid_rows)

    def _controls_page(self) -> AppKit.NSView:
        self.controls_list = label("", 15, wrap=True)
        edit = button("Edit controls…", lambda: self.hub.open("controls"), icon="slider.horizontal.3")
        return self._page_frame("Controls", "What a tap on your Omi does on this Mac.", [self.controls_list, edit])

    def _pendant_page(self) -> AppKit.NSView:
        self.omi_battery = label("—", 54, W_BOLD)
        self.omi_battery.setFont_(rounded(54, W_BOLD))
        self.omi_status = label("", 15, color=C.secondaryLabelColor(), wrap=True)
        again = button("Reconnect", self.hub.radio.reconnect, icon="arrow.clockwise")
        tools = button("Bluetooth tools…", lambda: self.hub.open("bluetooth"), icon="antenna.radiowaves.left.and.right")
        return self._page_frame("Omi", "Your pendant. Sideband keeps it connected in the background.",
                                [self.omi_battery, self.omi_status, stack([again, tools], vertical=False, spacing=8)])

    def _refresh_app_page(self) -> None:
        if self.place == "controls":
            lines = [f"{g.title()} tap  →  {m.action}{(' · ' + m.arg) if m.arg else ''}" for g, m in self.hub.map.gestures.items()]
            self.controls_list.setStringValue_("\n".join(lines))
        elif self.place == "pendant":
            level = self.hub.battery_level
            self.omi_battery.setStringValue_(f"{level}%" if level is not None else "—")
            rate = self.hub.stream_rate
            parts = [self.hub.status.get().capitalize(), self.hub.device.get()]
            if self.hub.charging:
                parts.append("charging")
            if rate is not None:
                parts.append(f"{rate:.0f} audio frames/s")
            self.omi_status.setStringValue_(" · ".join(p for p in parts if p))

    # --- data ----------------------------------------------------------------------------------------

    def refresh(self, select_newest: bool = False, select: str | None = None) -> None:
        self.rows, self.filings, self.docs = {}, {}, {}
        for rec in list_recordings(self.hub.app.recordings_dir):
            self.rows[rec.stem] = rec
            if rec.transcript is not None:
                try:
                    markdown = rec.transcript.read_text(encoding="utf-8")
                except OSError:
                    continue
                doc = parse_thought(markdown)
                self.docs[rec.stem] = doc
                if doc.folder:
                    self.filings[rec.stem] = Filed(doc.folder, doc.title)
        self.ripeness = self.hub.maturities()
        selected_key = None
        row = self.outline.selectedRow()
        if row >= 0:
            node = self.outline.itemAtRow_(row)
            selected_key = node.key if node is not None else None
        self._build_nodes()
        self.outline.reloadData()
        for node in self.roots:
            self.outline.expandItem_(node)
        if selected_key and selected_key in self.nodes and (selected_key in ("inbox", "all", "arcade", "controls", "pendant")
                                                            or self._node_live(selected_key)):
            self._select_node(selected_key)
        if select_newest and self.rows and not select:
            select = next(iter(self.rows))
        if self.place in self.app_pages:
            self._refresh_app_page()
            return
        self._fill_list(select)
        if select and self.shown != select:
            rec = self.rows.get(select)
            if rec is not None and rec in self.items:
                self.shown = select
                self._render(rec)
        elif self.shown in self.rows:
            self._render(self.rows[self.shown])  # it may have gained a summary or a folder

    def _node_live(self, key: str) -> bool:
        def walk(nodes):
            return any(n.key == key or walk(n.children) for n in nodes)
        return walk(self.roots)

    def drop_thought(self, stem: str, folder: Folder) -> bool:
        rec = self.rows.get(stem)
        if rec is None or rec.transcript is None:
            return False
        filed = self.filings.get(stem)
        self.hub.move_thought(rec.transcript, folder, filed.title if filed else "")
        self.did(f"Moved to {SEP.join(folder)}")
        self.refresh()
        return True

    # --- menus, sheets --------------------------------------------------------------------------------

    def _thought_menu(self) -> AppKit.NSMenu:
        menu = AppKit.NSMenu.alloc().init()
        for title, callback in (
            ("Read Aloud", self._speak), ("Summarize", self._summarize), (None, None),
            ("Move to…", self._move), ("File Again", self._refile), (None, None),
            ("Open in Editor", self._open), ("Play Audio", self._play), ("Show in Finder", self._reveal),
        ):
            if title is None:
                menu.addItem_(AppKit.NSMenuItem.separatorItem())
                continue
            target, action = target_for(callback)
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(target)
            menu.addItem_(item)
        return menu

    def _speak(self) -> None:
        rec = self._selected()
        if rec is not None and rec.transcript is not None:
            self.hub.speak_recording(rec.transcript)

    def _summarize(self) -> None:
        rec = self._selected()
        if rec is not None and rec.transcript is not None:
            self.hub.summarize(rec.transcript)
            self.did("Writing a summary…")

    def _refile(self) -> None:
        rec = self._selected()
        if rec is not None and rec.transcript is not None:
            self.hub.bucket(rec.transcript)
            self.did("Asking the AI where it goes…")

    def _open(self) -> None:
        rec = self._selected()
        if rec is not None and rec.transcript is not None:
            self.hub.app.open_path(rec.transcript)

    def _play(self) -> None:
        rec = self._selected()
        if rec is not None and rec.audio is not None:
            self.hub.app.open_path(rec.audio)

    def _reveal(self) -> None:
        rec = self._selected()
        if rec is not None:
            self.hub.app.open_path(rec.transcript or rec.audio, reveal=True)  # type: ignore[arg-type]

    def _move(self) -> None:
        rec = self._selected()
        if rec is None or rec.transcript is None:
            return
        filed = self.filings.get(rec.stem)
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Move this thought")
        alert.setInformativeText_("Pick a folder or type a new one, like Work / Clients / Acme. You can also drag thoughts onto folders.")
        where = AppKit.NSComboBox.alloc().initWithFrame_(NSMakeRect(0, 30, 320, 26))
        where.addItemsWithObjectValues_([" / ".join(f) for f in all_folders([f.folder for f in self.filings.values()])])
        where.setStringValue_(" / ".join(filed.folder) if filed else "")
        name = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 24))
        name.setPlaceholderString_("Title")
        name.setStringValue_(filed.title if filed else "")
        box = AppKit.NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 58))
        box.addSubview_(where)
        box.addSubview_(name)
        alert.setAccessoryView_(box)
        alert.addButtonWithTitle_("Move")
        alert.addButtonWithTitle_("Cancel")

        def done(code: int) -> None:
            folder = split_path(str(where.stringValue()))[:3]
            if code == AppKit.NSAlertFirstButtonReturn and folder:
                self.hub.move_thought(rec.transcript, folder, str(name.stringValue()).strip())  # type: ignore[arg-type]
                self.did(f"Moved to {SEP.join(folder)}")
                self.refresh(select=rec.stem)

        alert.beginSheetModalForWindow_completionHandler_(self.win, done)

    def _ai_settings(self) -> None:
        backend = self.hub.backend()
        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 520, 340), AppKit.NSWindowStyleMaskTitled, AppKit.NSBackingStoreBuffered, False)
        preset = AppKit.NSPopUpButton.alloc().init()
        preset.addItemsWithTitles_([p[0] for p in PRESETS] + ["Custom"])
        current = next((p[0] for p in PRESETS if p[1] == backend.kind and p[3] == backend.base_url), "Custom")
        preset.selectItemWithTitle_(current)
        runs = AppKit.NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            ["MLX on this Mac", "OpenAI-compatible server"], AppKit.NSSegmentSwitchTrackingSelectOne, None, None)
        runs.setSelectedSegment_(0 if backend.kind == "mlx" else 1)
        model = AppKit.NSTextField.alloc().init()
        model.setStringValue_(backend.model)
        base = AppKit.NSTextField.alloc().init()
        base.setStringValue_(backend.base_url)
        base.setPlaceholderString_("http://localhost:11434/v1")
        key = AppKit.NSSecureTextField.alloc().init()
        has_key = bool(self.hub.app.api_key())
        key.setPlaceholderString_("Saved in your Keychain; leave blank to keep" if has_key else "Only for hosted APIs")
        warning = label("", 12, color=C.systemOrangeColor(), wrap=True)
        for field in (model, base, key):
            width(field, 330)

        def update() -> None:
            kind = "mlx" if runs.selectedSegment() == 0 else "api"
            base.setEnabled_(kind == "api")
            key.setEnabled_(kind == "api")
            chosen = Backend(kind, str(model.stringValue()), str(base.stringValue()))
            host = str(base.stringValue()).split("://", 1)[-1].split("/", 1)[0]
            warning.setStringValue_("" if chosen.local else f"Your thoughts' text will be sent to {host}.")

        def use_preset() -> None:
            for title, kind, m, url in PRESETS:
                if title == preset.titleOfSelectedItem():
                    runs.setSelectedSegment_(0 if kind == "mlx" else 1)
                    model.setStringValue_(m)
                    base.setStringValue_(url)
            update()

        on(preset, use_preset)
        on(runs, update)
        on(base, update)
        grid = AppKit.NSGridView.gridViewWithViews_([
            [label("Preset", 13), preset], [label("Runs with", 13), runs], [label("Model", 13), model],
            [label("Server", 13), base], [label("API key", 13), key],
        ])
        grid.setRowSpacing_(10)
        grid.setColumnSpacing_(12)
        grid.columnAtIndex_(0).setXPlacement_(AppKit.NSGridCellPlacementTrailing)
        grid.setTranslatesAutoresizingMaskIntoConstraints_(False)
        title = label("Which AI thinks for you?", 17, W_BOLD)
        lead = label("It files your thoughts, suggests next steps and answers questions. "
                     "On this Mac nothing leaves your computer.", 12, color=C.secondaryLabelColor(), wrap=True)

        def close(save: bool, test: bool = False) -> None:
            if save:
                kind = "mlx" if runs.selectedSegment() == 0 else "api"
                new_key = str(key.stringValue()).strip() or None
                self.hub.set_backend(kind, str(model.stringValue()).strip(), str(base.stringValue()).strip(), new_key)
            self.win.endSheet_(panel)
            if test:
                self.stream_answer(self.hub.test_backend())

        buttons = stack([button("Cancel", lambda: close(False)), button("Save and Test", lambda: close(True, True)),
                         button("Save", lambda: close(True), style="prominent")], vertical=False, spacing=8)
        column = stack([title, lead, grid, warning, buttons], spacing=12, insets=(20, 24, 20, 24))
        column.setCustomSpacing_afterView_(18, lead)
        fill_width(lead, column, 24)
        fill_width(warning, column, 24)
        buttons.setAlignment_(AppKit.NSLayoutAttributeCenterY)
        pin(column, panel.contentView())
        update()
        self.win.beginSheet_completionHandler_(panel, None)
        self._panel = panel

    def _capture(self) -> None:
        text = str(self.capture.stringValue()).strip()
        if not text:
            return
        self.capture.setStringValue_("")
        if text.endswith("?"):
            self.stream_answer(self.hub.ask(text, None, self._scope()))
            self.caption.setStringValue_(f"“{text}”")
            self.caption.setTextColor_(C.labelColor())
            return
        path = self.hub.add_thought(text)
        if path is not None:
            self.did("Saved. Filing it…")
            self.refresh(select=path.stem)

    def _scope(self) -> list[Path] | None:
        if self.place == "folder":
            return [r.transcript for r in self.rows.values()
                    if r.transcript and (f := self.filings.get(r.stem)) and f.folder[: len(self.folder)] == self.folder]
        return None

    # --- Hub callbacks (same as the Tk Thought Map) ---------------------------------------------------

    def token(self, job_id: int, text: str) -> None:
        if job_id == self.answer_job:
            self.answer_text += text
            self.did(self.answer_text.strip())

    def job_done(self, job_id: int, text: str, error: str, transcript: Path | None) -> None:
        if job_id == self.answer_job:
            self.answer_job = None
            self.did(f"Couldn't answer: {error}" if error else text.strip())
        if transcript is not None:
            self.refresh()

    def show_summary_job(self, job_id: int | None) -> None:
        if job_id is not None:
            self.did("Writing a summary…")

    def transcript_ready(self, wav: Path, transcript: Path | None) -> None:
        self.refresh(select=wav.stem if self.place in ("all", "inbox") else None)

    def filed(self, transcript: Path, filed: Filed, fresh: Folder | None) -> None:
        name = f"“{filed.title}”" if filed.title else "Your thought"
        if fresh is not None:
            for depth in range(len(fresh), len(filed.folder) + 1):
                self.fresh.add(filed.folder[:depth])
            self.did(f"✨ New folder {SEP.join(fresh)} · {name} is in {SEP.join(filed.folder)}")
        else:
            self.did(f"📁 {name} is in {SEP.join(filed.folder)}")
        self.refresh()

    def matured(self, job_id: int, folder: Folder, entry, error: str) -> None:
        if entry is not None:
            self.did(f"{entry.badge} {SEP.join(folder)} · next step: {entry.next_action}")
        self.refresh()

    def on_tick(self) -> None:
        now = time.monotonic()
        if now - self.last_tick < 0.08:
            return
        self.last_tick = now
        if self.hub.rec_path is not None:
            span = int(now - self.hub.rec_started)
            subtitle = f"● Recording {span // 60}:{span % 60:02d}"
        else:
            queued = self.hub.transcriber.pending()
            subtitle = f"Transcribing {queued}…" if queued else self.hub.llm_status.get().removeprefix("assistant: ")
        if subtitle != self.subtitle:
            self.subtitle = subtitle
            self.win.setSubtitle_(subtitle)
        level, active = self.hub.talk_level()
        if abs(level - self.meter_level) > 0.02 or active != self.meter.active:
            self.meter_level = level
            self.meter.set_level(level, active)
        if self.place == "pendant" and int(now) != int(now - 0.08):
            self._refresh_app_page()

    def recording_changed(self, recording: bool) -> None:
        if hasattr(self, "record_item"):
            self.record_item.setImage_(_red(symbol("stop.circle.fill" if recording else "record.circle", 15, color=C.systemRedColor())))
            self.record_item.setLabel_("Stop" if recording else "Record")
        self.refresh(select_newest=recording)

    def close(self) -> None:
        self.win.close()

    def closed(self) -> None:
        if self.monitor is not None:
            AppKit.NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        self.hub.window_closed(self)

    def snapshot(self, path: Path) -> None:
        """Draw the window into a PNG (for agents checking the layout; vibrancy draws flat)."""
        view = self.win.contentView().superview() or self.win.contentView()
        rect = view.bounds()
        rep = view.bitmapImageRepForCachingDisplayInRect_(rect)
        view.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
        data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
        data.writeToFile_atomically_(str(path), True)

    def lift(self) -> None:
        self.win.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)


def _red(image: AppKit.NSImage | None) -> AppKit.NSImage | None:
    if image is not None:
        image.setTemplate_(False)  # toolbars tint template images grey
    return image


def _hex(value: str) -> AppKit.NSColor:
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return C.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0)
