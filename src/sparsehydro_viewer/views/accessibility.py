"""Accessible names for controls that were not given one explicitly.

Screen readers announce a control by its accessible name. Most controls get a
deliberate name where they are built; :func:`apply_accessible_defaults` fills
in the rest from what a sighted user would read: the control's own text, its
tooltip, its placeholder, the label of its form row, or the title of the group
box around it. It never overwrites a name that was set.

:func:`interactive_controls` and :func:`needs_tooltip` define what the tests
check: every interactive control has an accessible name, and every control
whose purpose is not written on it (combo boxes, edits, spin boxes, sliders,
icon-only buttons) has a tooltip.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSlider,
    QTabBar,
    QWidget,
)

INTERACTIVE = (QAbstractButton, QComboBox, QLineEdit, QAbstractSpinBox, QSlider, QAbstractItemView)


def _is_internal(w: QWidget) -> bool:
    """Parts Qt builds inside other controls (combo pop-ups, header views, a line edit's clear button, the
    line edit inside a spin box or editable combo, a tab bar's scroll arrows), which assistive technology
    reaches through their owner."""
    if isinstance(w, QHeaderView) or w.objectName().startswith("qt_"):
        return True
    parent = w.parentWidget()
    while parent is not None:
        if isinstance(parent, QComboBox | QAbstractSpinBox | QLineEdit | QTabBar):
            return True
        parent = parent.parentWidget()
    return type(w).__name__ in ("QToolBarExtension", "QScrollBar", "QCalendarWidget")


def interactive_controls(root: QWidget) -> list[QWidget]:
    """Interactive controls under *root* that a user reaches directly."""
    return [w for w in root.findChildren(QWidget) if isinstance(w, INTERACTIVE) and not _is_internal(w)]


def needs_tooltip(w: QWidget) -> bool:
    """Controls whose purpose is not written on them."""
    if isinstance(w, QAbstractItemView):
        return False
    if isinstance(w, QAbstractButton):
        return not w.text().strip() or w.text().strip() in ("↺", "…", "...")
    return True


def _form_label(w: QWidget) -> str:
    parent = w.parentWidget()
    lay = parent.layout() if parent is not None else None
    if isinstance(lay, QFormLayout):
        label = lay.labelForField(w)
        if isinstance(label, QLabel):
            return label.text()
    for label in (parent.findChildren(QLabel) if parent is not None else []):
        if label.buddy() is w:
            return label.text()
    return ""


def _group_title(w: QWidget) -> str:
    parent = w.parentWidget()
    while parent is not None:
        if isinstance(parent, QGroupBox) and parent.title():
            return parent.title()
        parent = parent.parentWidget()
    return ""


def default_name(w: QWidget) -> str:
    """The name a screen reader should use for *w*, from what is visible around it."""
    text = w.text() if isinstance(w, QAbstractButton) else ""  # a line edit's text is content, not a name
    candidates = [
        text,
        _form_label(w),
        w.toolTip().split("\n", 1)[0],
        w.placeholderText() if isinstance(w, QLineEdit) else "",
    ]
    for c in candidates:
        c = c.replace("&", "").strip().rstrip(":")
        if c:
            return c
    title = _group_title(w)
    if title:
        kind = "list" if isinstance(w, QAbstractItemView) else type(w).__name__.removeprefix("Q").lower()
        return f"{title} {kind}"
    return ""


def apply_accessible_defaults(root: QWidget) -> int:
    """Give every unnamed interactive control under *root* a name; returns how many were named."""
    n = 0
    for w in interactive_controls(root):
        if w.accessibleName().strip():
            continue
        name = default_name(w)
        if name:
            w.setAccessibleName(name)
            n += 1
    return n


__all__ = ["apply_accessible_defaults", "default_name", "interactive_controls", "needs_tooltip"]
