"""Small helpers shared by the pages."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from ..core.objectives import OBJECTIVES


def page_header(title: str, hint: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    t = QLabel(title)
    t.setObjectName("pageTitle")
    h = QLabel(hint)
    h.setObjectName("hint")
    h.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(h)
    return w


def objective_labels(names: Iterable[str] | None = None) -> dict[str, str]:
    out = {e.name: e.label for e in OBJECTIVES.entries()}
    for n in names or []:
        out.setdefault(n, n)
    return out


def objective_better(names: Iterable[str] | None = None) -> dict[str, str]:
    out = {e.name: ("min" if e.minimize else "max") for e in OBJECTIVES.entries()}
    for n in names or []:
        out.setdefault(n, "")
    return out


def num_item(value: float | int | None, fmt: str = "{:.4g}") -> QTableWidgetItem:
    """Right-aligned numeric table item that sorts numerically."""
    it = QTableWidgetItem()
    if value is None or (isinstance(value, float) and value != value):
        it.setText("")
    else:
        it.setData(Qt.ItemDataRole.EditRole, float(value) if isinstance(value, float) else value)
        it.setText(fmt.format(value) if isinstance(value, float) else str(value))
    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return it


def text_item(text: str, data: object = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    return it


def with_toolbar(plot) -> QWidget:
    """A TimeseriesPlot with its navigation toolbar (pan, zoom box, fit, auto Y, export) above it."""
    from ..widgets.chart_toolbar import ChartToolbar

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(ChartToolbar(plot))
    lay.addWidget(plot, 1)
    return w


def hbox(*widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        lay.addWidget(w)
    if not stretch_last:
        lay.addStretch(1)
    return lay
