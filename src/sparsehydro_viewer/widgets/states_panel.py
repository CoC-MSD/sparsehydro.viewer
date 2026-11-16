"""Internal states panel: pick traced states and fluxes, plot them on the hydrograph's time axis."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .. import theme
from ..core.trace import TraceField, state_fields

ROLE_LABELS = {"state": "state", "flux": "flux"}


class StatesPanel(QWidget):
    """Tree of traced states/fluxes (grouped by model part) and linked plots, one per unit.

    :attr:`selectionChanged` carries the checked field names; the selection
    for each model structure is kept (see :meth:`set_fields`).
    """

    selectionChanged = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["State or flux", "Units"])
        self.tree.setColumnWidth(0, 230)
        self.tree.itemChanged.connect(self._item_changed)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        self.plots = pg.GraphicsLayoutWidget()
        self.plots.setBackground(theme.current().plot_bg)
        self.plots.ci.setSpacing(0)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.tree, 1)
        ll.addWidget(self.hint)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.plots)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 700])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        self.fields: dict[str, TraceField] = {}
        self._selection: dict[str, list[str]] = {}
        self._key = ""
        self._link: pg.ViewBox | None = None
        self._t: np.ndarray | None = None
        self._arrays: dict[str, np.ndarray] = {}
        self._syncing = False
        self._set_hint()

    # ------------------------------------------------------------------ fields

    def set_fields(self, fields: list, structure_key: str = "") -> None:
        """List the model's states and fluxes; the selection is remembered per *structure_key*."""
        listed = state_fields(fields)
        names = [f.name for f in listed]
        if structure_key == self._key and names == list(self.fields):
            return
        self._key = structure_key
        self.fields = {f.name: f for f in listed}
        chosen = [n for n in self._selection.get(structure_key, self._default(listed)) if n in self.fields]
        self._syncing = True
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for f in listed:
            parent = groups.get(f.group)
            if parent is None:
                parent = QTreeWidgetItem([" › ".join(p for p in f.group.split(".") if p) or "Model", ""])
                parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.tree.addTopLevelItem(parent)
                groups[f.group] = parent
            item = QTreeWidgetItem([f.label.rsplit(" › ", 1)[-1], f.units])
            item.setData(0, Qt.ItemDataRole.UserRole, f.name)
            item.setToolTip(0, f"{f.name} ({ROLE_LABELS.get(f.role, f.role)})\n{f.description}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if f.name in chosen else Qt.CheckState.Unchecked)
            if f.role == "flux":
                item.setForeground(0, pg.mkColor(theme.current().muted))
            parent.addChild(item)
        self.tree.expandAll()
        self._syncing = False
        self._selection[structure_key] = chosen
        self._set_hint()
        self._redraw()

    @staticmethod
    def _default(fields: list[TraceField]) -> list[str]:
        """Start with the storages (states), not the fluxes."""
        return [f.name for f in fields if f.role == "state"][:4]

    def selected(self) -> list[str]:
        return list(self._selection.get(self._key, []))

    def set_selected(self, names: list[str]) -> None:
        self._syncing = True
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                name = item.data(0, Qt.ItemDataRole.UserRole)
                item.setCheckState(0, Qt.CheckState.Checked if name in names else Qt.CheckState.Unchecked)
        self._syncing = False
        self._item_changed()

    def _item_changed(self, *_args) -> None:
        if self._syncing:
            return
        names = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                if item.checkState(0) == Qt.CheckState.Checked:
                    names.append(item.data(0, Qt.ItemDataRole.UserRole))
        self._selection[self._key] = names
        self.selectionChanged.emit(names)
        self._redraw()

    def _set_hint(self) -> None:
        self.hint.setText("This model reports no internal states." if not self.fields else
                          "Tick states (storages) or fluxes to plot them under the hydrograph's time axis.")

    # ------------------------------------------------------------------ data

    def link_x(self, viewbox: pg.ViewBox) -> None:
        """Share the time axis with the hydrograph."""
        self._link = viewbox
        self._redraw()

    def set_trace(self, t: np.ndarray, arrays: dict[str, np.ndarray]) -> None:
        self._t = np.asarray(t, float)
        self._arrays = arrays
        self._redraw()

    def plotted(self) -> list[str]:
        return [n for n in self.selected() if n in self._arrays]

    def _redraw(self) -> None:
        self.plots.clear()
        names = self.plotted()
        if self._t is None or not names:
            return
        th = theme.current()
        by_units: dict[str, list[str]] = {}
        for n in names:
            by_units.setdefault(self.fields[n].units if n in self.fields else "", []).append(n)
        colors = {n: theme.series_color(i) for i, n in enumerate(self.fields)}
        last = None
        for row, (units, members) in enumerate(by_units.items()):
            p = self.plots.addPlot(row=row, col=0, axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
            theme.plain_axes(p)
            p.setLabel("left", units or "-")
            p.getAxis("left").setWidth(60)
            p.showGrid(x=True, y=True, alpha=0.15)
            p.setMouseEnabled(x=True, y=False)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            p.addLegend(offset=(-10, 6), labelTextColor=th.plot_fg)
            for n in members:
                pen = pg.mkPen(colors.get(n, th.accent), width=1.4)
                pen.setCosmetic(True)
                if self.fields[n].role == "flux":
                    pen.setStyle(Qt.PenStyle.DashLine)
                p.plot(self._t, np.asarray(self._arrays[n], float), pen=pen, name=self.fields[n].label)
            if self._link is not None:
                p.setXLink(self._link)
            if last is not None:
                last.hideAxis("bottom")
            last = p


__all__ = ["StatesPanel"]
