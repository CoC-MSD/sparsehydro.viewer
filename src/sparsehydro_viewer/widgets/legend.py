"""Legends whose entries switch series on and off, and stay that way.

pyqtgraph toggles the one item a legend sample points at when the sample is
clicked, but the charts here rebuild their items on every redraw (a slider
move, a new selection), which would bring a hidden series back, and a series
is often several items (a band's fill and its legend swatch, a stacked layer's
fill and edge). :class:`ToggleLegend` keeps the *names* of the hidden series
and applies them to every item registered under a name, each time it is
registered - so a hidden series stays hidden until it is clicked again.

The same state is offered as a menu of checkable actions
(:meth:`ToggleLegend.fill_menu`), which makes it reachable from the keyboard:
legend samples cannot take focus.
"""

from __future__ import annotations

import weakref

import pyqtgraph as pg
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMenu

TIP = "Click a legend symbol to hide or show its series"


class ToggleLegend(QObject):
    """Visibility of a chart's named series, driven by its legend.

    :attr:`visibilityChanged` emits ``(name, visible)`` after a click or a menu choice.
    """

    visibilityChanged = Signal(str, bool)

    def __init__(self, legend: pg.LegendItem, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.legend = legend
        self.hidden: set[str] = set()
        self._items: dict[str, list[weakref.ref]] = {}
        legend.sigSampleClicked.connect(self._sample_clicked)
        legend.setToolTip(TIP)

    # -- registration (called by the chart whenever it creates the items of a series) -------------

    def register(self, name: str | None, item, *others) -> None:
        """Declare that series *name* is drawn by *item* (the one in the legend) and *others*; a series hidden
        earlier is hidden again."""
        if not name:
            return
        self._items[name] = [weakref.ref(i) for i in (item, *others) if i is not None]
        if name in self.hidden:
            self._apply(name)

    def forget(self, name: str | None) -> None:
        """The series is gone from the chart (its hidden state is kept for when it returns)."""
        if name:
            self._items.pop(name, None)

    def clear(self) -> None:
        """Forget every series' items (before a full redraw); hidden names are kept."""
        self._items.clear()

    def names(self) -> list[str]:
        return [n for n, refs in self._items.items() if any(r() is not None for r in refs)]

    # -- state --------------------------------------------------------------------------------------

    def is_visible(self, name: str) -> bool:
        return name not in self.hidden

    def set_visible(self, name: str, visible: bool) -> None:
        if visible == (name not in self.hidden):
            return
        if visible:
            self.hidden.discard(name)
        else:
            self.hidden.add(name)
        self._apply(name)
        self.visibilityChanged.emit(name, visible)

    def show_only(self, name: str) -> None:
        for other in self.names():
            self.set_visible(other, other == name)

    def show_all(self) -> None:
        for name in list(self.hidden):
            self.set_visible(name, True)

    def _apply(self, name: str) -> None:
        visible = name not in self.hidden
        for ref in self._items.get(name, []):
            item = ref()
            if item is not None:
                item.setVisible(visible)
        self.legend.update()

    def _sample_clicked(self, item) -> None:
        """pyqtgraph has just toggled *item*; record it and bring the series' other items along."""
        for name, refs in self._items.items():
            if refs and refs[0]() is item:
                visible = bool(item.isVisible())
                if visible:
                    self.hidden.discard(name)
                else:
                    self.hidden.add(name)
                self._apply(name)
                self.visibilityChanged.emit(name, visible)
                return

    # -- keyboard-accessible equivalent --------------------------------------------------------------

    def fill_menu(self, menu: QMenu) -> None:
        """Checkable actions for every series, then "Show all"."""
        for name in self.names():
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name not in self.hidden)
            act.toggled.connect(lambda on, n=name: self.set_visible(n, on))
        if self.names():
            menu.addSeparator()
            menu.addAction("Show all").triggered.connect(lambda *_: self.show_all())


__all__ = ["TIP", "ToggleLegend"]
