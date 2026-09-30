"""Small AppKit helpers for the native windows (PyObjC): labels, SF Symbols, buttons, layout.

Only the `mac_*` modules import this. It keeps the window code short and reads like the Tk code did.
"""

from __future__ import annotations

from typing import Callable

import AppKit
import objc
from Foundation import NSObject

W_REGULAR = AppKit.NSFontWeightRegular
W_MEDIUM = AppKit.NSFontWeightMedium
W_SEMIBOLD = AppKit.NSFontWeightSemibold
W_BOLD = AppKit.NSFontWeightBold


def font(size: float, weight: float = W_REGULAR) -> AppKit.NSFont:
    return AppKit.NSFont.systemFontOfSize_weight_(size, weight)


def rounded(size: float, weight: float = W_SEMIBOLD) -> AppKit.NSFont:
    """SF Pro Rounded, for big friendly numbers and titles."""
    base = font(size, weight)
    desc = base.fontDescriptor().fontDescriptorWithDesign_(AppKit.NSFontDescriptorSystemDesignRounded)
    return AppKit.NSFont.fontWithDescriptor_size_(desc, size) if desc else base


def mono_digits(size: float, weight: float = W_REGULAR) -> AppKit.NSFont:
    return AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)


def symbol(name: str, size: float = 15, weight: float = W_REGULAR, color: AppKit.NSColor | None = None) -> AppKit.NSImage | None:
    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if image is None:
        return None
    config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, weight)
    if color is not None:
        config = config.configurationByApplyingConfiguration_(AppKit.NSImageSymbolConfiguration.configurationWithHierarchicalColor_(color))
    return image.imageWithSymbolConfiguration_(config)


def label(text: str = "", size: float = 13, weight: float = W_REGULAR, color: AppKit.NSColor | None = None,
          wrap: bool = False, lines: int = 0) -> AppKit.NSTextField:
    field = AppKit.NSTextField.wrappingLabelWithString_(text) if wrap else AppKit.NSTextField.labelWithString_(text)
    field.setFont_(font(size, weight))
    field.setTextColor_(color or AppKit.NSColor.labelColor())
    field.setTranslatesAutoresizingMaskIntoConstraints_(False)
    if wrap:
        field.setMaximumNumberOfLines_(lines)
        field.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        field.cell().setTruncatesLastVisibleLine_(True)
        field.setContentCompressionResistancePriority_forOrientation_(250, AppKit.NSLayoutConstraintOrientationHorizontal)
    else:
        field.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    return field


class _Target(NSObject):
    """Holds a Python callback for a control's target/action."""

    def fire_(self, sender: object) -> None:
        self.callback()


_targets: list[_Target] = []  # AppKit does not retain targets


def on(control: AppKit.NSControl, callback: Callable[[], None]) -> AppKit.NSControl:
    target = _Target.alloc().init()
    target.callback = callback
    _targets.append(target)
    control.setTarget_(target)
    control.setAction_(objc.selector(target.fire_, signature=b"v@:@"))
    return control


def target_for(callback: Callable[[], None]) -> tuple[_Target, str]:
    target = _Target.alloc().init()
    target.callback = callback
    _targets.append(target)
    return target, "fire:"


def button(title: str, callback: Callable[[], None], icon: str | None = None, style: str = "rounded",
           size: str = "regular") -> AppKit.NSButton:
    b = AppKit.NSButton.buttonWithTitle_target_action_(title, None, None)
    on(b, callback)
    if icon:
        image = symbol(icon, 13)
        if image is not None:
            b.setImage_(image)
            b.setImagePosition_(AppKit.NSImageLeading if title else AppKit.NSImageOnly)
    if style == "prominent":
        b.setBezelStyle_(AppKit.NSBezelStyleRounded)
        b.setKeyEquivalent_("\r")
    elif style == "plain":
        b.setBordered_(False)
    elif style == "pill":
        b.setBezelStyle_(AppKit.NSBezelStyleInline if hasattr(AppKit, "NSBezelStyleInline") else 15)
    b.setControlSize_({"small": AppKit.NSControlSizeSmall, "large": AppKit.NSControlSizeLarge}.get(size, AppKit.NSControlSizeRegular))
    b.setTranslatesAutoresizingMaskIntoConstraints_(False)
    return b


def stack(views: list, vertical: bool = True, spacing: float = 8, align: str = "leading",
          insets: tuple[float, float, float, float] | None = None) -> AppKit.NSStackView:
    s = AppKit.NSStackView.stackViewWithViews_(views)
    s.setOrientation_(AppKit.NSUserInterfaceLayoutOrientationVertical if vertical else AppKit.NSUserInterfaceLayoutOrientationHorizontal)
    s.setSpacing_(spacing)
    aligns = {
        "leading": AppKit.NSLayoutAttributeLeading if vertical else AppKit.NSLayoutAttributeCenterY,
        "center": AppKit.NSLayoutAttributeCenterX if vertical else AppKit.NSLayoutAttributeCenterY,
        "top": AppKit.NSLayoutAttributeTop,
        "fill": AppKit.NSLayoutAttributeWidth if vertical else AppKit.NSLayoutAttributeHeight,
    }
    s.setAlignment_(aligns.get(align, aligns["leading"]))
    if insets:
        s.setEdgeInsets_(AppKit.NSEdgeInsets(*insets))
    s.setTranslatesAutoresizingMaskIntoConstraints_(False)
    return s


def pin(view: AppKit.NSView, parent: AppKit.NSView, top: float | None = 0, left: float | None = 0,
        bottom: float | None = 0, right: float | None = 0, safe: bool = False) -> None:
    """Add `view` to `parent` and pin the given edges (None leaves an edge free)."""
    if view.superview() is not parent:
        parent.addSubview_(view)
    view.setTranslatesAutoresizingMaskIntoConstraints_(False)
    guide = parent.safeAreaLayoutGuide() if safe else parent
    if top is not None:
        view.topAnchor().constraintEqualToAnchor_constant_(guide.topAnchor(), top).setActive_(True)
    if left is not None:
        view.leadingAnchor().constraintEqualToAnchor_constant_(guide.leadingAnchor(), left).setActive_(True)
    if bottom is not None:
        view.bottomAnchor().constraintEqualToAnchor_constant_(guide.bottomAnchor(), -bottom).setActive_(True)
    if right is not None:
        view.trailingAnchor().constraintEqualToAnchor_constant_(guide.trailingAnchor(), -right).setActive_(True)


def width(view: AppKit.NSView, points: float) -> None:
    view.widthAnchor().constraintEqualToConstant_(points).setActive_(True)


def height(view: AppKit.NSView, points: float) -> None:
    view.heightAnchor().constraintEqualToConstant_(points).setActive_(True)


def fill_width(view: AppKit.NSView, of: AppKit.NSView, inset: float = 0) -> None:
    view.widthAnchor().constraintEqualToAnchor_constant_(of.widthAnchor(), -2 * inset).setActive_(True)


def card(content: AppKit.NSView, color: AppKit.NSColor | None = None, radius: float = 12, pad: float = 14) -> AppKit.NSBox:
    """A rounded, softly tinted panel around `content`."""
    box = AppKit.NSBox.alloc().init()
    box.setBoxType_(AppKit.NSBoxCustom)
    box.setBorderWidth_(0)
    box.setCornerRadius_(radius)
    box.setFillColor_(color or AppKit.NSColor.quaternaryLabelColor().colorWithAlphaComponent_(0.08))
    box.setContentViewMargins_(AppKit.NSMakeSize(0, 0))
    box.setTitlePosition_(AppKit.NSNoTitle)
    box.setTranslatesAutoresizingMaskIntoConstraints_(False)
    pin(content, box.contentView(), pad, pad, pad, pad)
    return box


def separator() -> AppKit.NSBox:
    line = AppKit.NSBox.alloc().init()
    line.setBoxType_(AppKit.NSBoxSeparator)
    line.setTranslatesAutoresizingMaskIntoConstraints_(False)
    return line


def attributed(pieces: list[tuple[str, dict]]) -> AppKit.NSAttributedString:
    out = AppKit.NSMutableAttributedString.alloc().init()
    for text, attrs in pieces:
        out.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_(text, attrs))
    return out


def para(spacing_before: float = 0, spacing_after: float = 0, line: float = 1.15, indent: float = 0,
         head_indent: float | None = None) -> AppKit.NSParagraphStyle:
    p = AppKit.NSMutableParagraphStyle.alloc().init()
    p.setParagraphSpacingBefore_(spacing_before)
    p.setParagraphSpacing_(spacing_after)
    p.setLineHeightMultiple_(line)
    p.setFirstLineHeadIndent_(indent)
    p.setHeadIndent_(indent if head_indent is None else head_indent)
    return p


def style(size: float = 14, weight: float = W_REGULAR, color: AppKit.NSColor | None = None,
          paragraph: AppKit.NSParagraphStyle | None = None, fnt: AppKit.NSFont | None = None) -> dict:
    attrs = {
        AppKit.NSFontAttributeName: fnt or font(size, weight),
        AppKit.NSForegroundColorAttributeName: color or AppKit.NSColor.labelColor(),
    }
    if paragraph is not None:
        attrs[AppKit.NSParagraphStyleAttributeName] = paragraph
    return attrs
