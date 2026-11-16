"""Picker for the series shown in panels under the hydrograph: dataset inputs and the model's states and fluxes.

The ticked series are drawn by the time-series chart itself
(:meth:`~sparsehydro_viewer.widgets.timeseries_plot.TimeseriesPlot.set_panels`), so they share its time axis:
panning, zooming and range selection move rain, flow and these panels together.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .. import theme
from ..core.trace import TraceField, state_fields

ROLE_LABELS = {"state": "state (storage)", "flux": "flux", "input": "dataset input"}


class StatesPanel(QWidget):
    """Tree of plottable series grouped by model part, with checkboxes.

    :attr:`selectionChanged` carries the ticked field names. The selection is
    kept per model structure (see :meth:`set_fields`); ticked dataset inputs
    carry over to a new structure because they do not depend on the model.
    """

    selectionChanged = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Series", "Units", "Kind"])
        self.tree.setColumnWidth(0, 280)
        self.tree.setAccessibleName("Series to plot under the hydrograph")
        self.tree.itemChanged.connect(self._item_changed)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.hint)
        self.fields: dict[str, TraceField] = {}
        self._selection: dict[str, list[str]] = {}
        self._key = ""
        self._syncing = False
        self._set_hint()

    def set_fields(self, fields: list, structure_key: str = "", inputs: list | None = None) -> None:
        """List *inputs* (dataset columns) and the model's states and fluxes from *fields*."""
        listed = list(inputs or []) + state_fields(fields)
        names = [f.name for f in listed]
        if structure_key == self._key and names == list(self.fields):
            return
        previous = self._selection.get(self._key, [])
        self._key = structure_key
        self.fields = {f.name: f for f in listed}
        if structure_key in self._selection:
            chosen = self._selection[structure_key]
        else:  # a new model: keep the inputs that were ticked
            chosen = [n for n in previous if n.startswith("inputs.")]
        chosen = [n for n in chosen if n in self.fields]
        self._syncing = True
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for f in listed:
            parent = groups.get(f.group)
            if parent is None:
                title = "Dataset inputs" if f.group == "inputs" else \
                    (" › ".join(p for p in f.group.split(".") if p) or "Model")
                parent = QTreeWidgetItem([title, "", ""])
                parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                self.tree.addTopLevelItem(parent)
                groups[f.group] = parent
            item = QTreeWidgetItem([f.label.rsplit(" › ", 1)[-1], f.units, ROLE_LABELS.get(f.role, f.role)])
            item.setData(0, Qt.ItemDataRole.UserRole, f.name)
            item.setToolTip(0, f"{f.name}\n{f.description}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if f.name in chosen else Qt.CheckState.Unchecked)
            if f.role == "flux":
                item.setForeground(0, theme_brush(theme.current().muted))
            parent.addChild(item)
        self.tree.expandAll()
        self._syncing = False
        self._selection[structure_key] = chosen
        self._set_hint()

    def selected(self) -> list[str]:
        return [n for n in self._selection.get(self._key, []) if n in self.fields]

    def set_selected(self, names: list[str]) -> None:
        self._syncing = True
        for item in self._items():
            name = item.data(0, Qt.ItemDataRole.UserRole)
            item.setCheckState(0, Qt.CheckState.Checked if name in names else Qt.CheckState.Unchecked)
        self._syncing = False
        self._item_changed()

    def needs_trace(self) -> bool:
        """Whether a ticked series comes from the model (inputs do not need a model trace)."""
        return any(not n.startswith("inputs.") for n in self.selected())

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent.child(j)

    def _item_changed(self, *_args) -> None:
        if self._syncing:
            return
        names = [item.data(0, Qt.ItemDataRole.UserRole) for item in self._items()
                 if item.checkState(0) == Qt.CheckState.Checked]
        self._selection[self._key] = names
        self.selectionChanged.emit(names)

    def _set_hint(self) -> None:
        self.hint.setText(
            "Nothing to plot: the dataset has no other inputs and the model reports no internal states."
            if not self.fields else
            "Tick series to plot them in panels under the hydrograph, one per unit; they share its time axis, "
            "so pan and zoom move them together. Fluxes are dashed.")


def theme_brush(color: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(color))


__all__ = ["StatesPanel"]
