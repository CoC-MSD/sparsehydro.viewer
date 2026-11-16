"""Process builder: grow a model by adding hydrological processes.

Three steps, top to bottom, mirroring how water moves through the model:

1. rainfall losses (none, initial abstraction with optional snowmelt, tanks);
2. runoff routing: a list of unit hydrographs - add, change, reorder, remove;
3. other flow components: sanitary pattern (groundwater when available).

Every edit emits :attr:`ProcessBuilder.changed` with the new component tree
and the parameter renames that keep tuned values attached to their process.
Trees built in the advanced editor that do not correspond to a process
design are shown as read-only here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.components import COMPONENTS, ComponentSpec
from ..core.processes import (
    LOSS_KEYS,
    NEEDS_LOSSES,
    ROUTING_KEYS,
    UNAVAILABLE,
    ProcessDesign,
    from_tree,
    renames,
    to_tree,
)
from ..resources import icon

LOSS_LABELS = {
    None: "None - all rain becomes runoff",
    "initial-abstraction": "Initial abstraction",
    "tank-constant": "Tank, constant drain",
    "tank-linear": "Tank, linear drain",
    "tank-sqrt": "Tank, square-root drain",
}


def _tool(icon_name: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(icon_name))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    return b


class ProcessBuilder(QWidget):
    #: New root ComponentSpec and parameter renames.
    changed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.design = ProcessDesign()
        self._editable = True

        # -- 1. losses ---------------------------------------------------------
        self.losses = QComboBox()
        for key, label in LOSS_LABELS.items():
            self.losses.addItem(label, key)
        self.losses.setToolTip("How rainfall becomes runoff-producing excess")
        self.losses.activated.connect(self._losses_changed)
        self.snow = QCheckBox("Snowmelt (degree-day; needs a temperature column)")
        self.snow.toggled.connect(self._snow_changed)
        losses_box = QGroupBox("1   Rainfall losses")
        ll = QVBoxLayout(losses_box)
        ll.addWidget(self.losses)
        ll.addWidget(self.snow)

        # -- 2. routing ----------------------------------------------------------
        self.uh_grid = QGridLayout()
        self.uh_grid.setHorizontalSpacing(4)
        self.add_uh = QToolButton()
        self.add_uh.setText("Add unit hydrograph")
        self.add_uh.setIcon(icon("new"))
        self.add_uh.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_uh.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.routing_hint = QLabel()
        self.routing_hint.setObjectName("hint")
        self.routing_hint.setWordWrap(True)
        routing_box = QGroupBox("2   Runoff routing (unit hydrographs)")
        rl = QVBoxLayout(routing_box)
        rl.addLayout(self.uh_grid)
        row = QHBoxLayout()
        row.addWidget(self.add_uh)
        row.addStretch(1)
        rl.addLayout(row)
        rl.addWidget(self.routing_hint)

        # -- 3. other components ------------------------------------------------
        self.sanitary = QCheckBox("Sanitary (dry-weather) pattern")
        self.sanitary.setToolTip("Adds baseline x hour-of-day, day-of-week and month factors to the flow")
        self.sanitary.toggled.connect(self._sanitary_changed)
        self.san_opts = {k: QCheckBox(lbl) for k, lbl in (("hour", "hour"), ("day_of_week", "day of week"),
                                                         ("month", "month"))}
        for cb in self.san_opts.values():
            cb.toggled.connect(self._sanitary_options_changed)
        san_row = QHBoxLayout()
        san_row.setContentsMargins(22, 0, 0, 0)
        san_row.addWidget(QLabel("factors by"))
        for cb in self.san_opts.values():
            san_row.addWidget(cb)
        san_row.addStretch(1)
        self.groundwater = QCheckBox("Groundwater infiltration")
        self.groundwater.setEnabled(False)
        self.groundwater.setToolTip(UNAVAILABLE["groundwater"])
        other_box = QGroupBox("3   Other flow components")
        ol = QVBoxLayout(other_box)
        ol.addWidget(self.sanitary)
        ol.addLayout(san_row)
        ol.addWidget(self.groundwater)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #cf222e;")
        self.readonly = QLabel("This model was built in the Advanced tab and has no process view. Edit it there, "
                               "or start a new design by choosing any option below.")
        self.readonly.setObjectName("banner")
        self.readonly.setWordWrap(True)
        self.readonly.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.readonly)
        lay.addWidget(losses_box)
        lay.addWidget(routing_box)
        lay.addWidget(other_box)
        lay.addWidget(self.summary)
        lay.addWidget(self.message)
        lay.addStretch(1)
        self._uh_rows: list[list[QWidget]] = []
        self._refresh()

    # ------------------------------------------------------------------ public

    def set_root(self, root: ComponentSpec) -> None:
        """Show the design behind *root* (read-only notice when there is none)."""
        design = from_tree(root)
        self.readonly.setVisible(design is None)
        if design is not None:
            self.design = design
        self.message.clear()
        self._refresh()

    # ------------------------------------------------------------------ view

    def _refresh(self) -> None:
        d = self.design
        self.losses.blockSignals(True)
        self.losses.setCurrentIndex(max(0, self.losses.findData(d.losses)))
        self.losses.blockSignals(False)
        # "None" is unavailable while an excess-routing hydrograph is in the list.
        model = self.losses.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(self.losses.findData(None))
            needs = any(k in NEEDS_LOSSES for k in d.routing)
            item.setEnabled(not needs)
            item.setToolTip("Remove RTK triangles first: they route rainfall excess" if needs else "")
        self.snow.blockSignals(True)
        self.snow.setChecked(d.snow)
        self.snow.setEnabled(d.losses == "initial-abstraction")
        self.snow.blockSignals(False)
        self._fill_uh_rows()
        menu = QMenu(self.add_uh)
        for key in ROUTING_KEYS:
            a = menu.addAction(COMPONENTS[key].label)
            a.setToolTip(COMPONENTS[key].description)
            a.setEnabled(d.losses is not None or key not in NEEDS_LOSSES)
            a.triggered.connect(lambda _=False, k=key: self._add(k))
        self.add_uh.setMenu(menu)
        self.routing_hint.setText(
            "The rainfall excess is split between the hydrographs by fractions R_i and scaled by a contributing "
            "area: add a fast and a slow hydrograph to capture both responses." if d.losses is not None else
            "Without a losses process each hydrograph is applied to rainfall with its own amplitude A; their "
            "flows add up. RTK triangles need a losses process.")
        self.sanitary.blockSignals(True)
        self.sanitary.setChecked(d.sanitary)
        self.sanitary.blockSignals(False)
        for k, cb in self.san_opts.items():
            cb.blockSignals(True)
            cb.setChecked(bool(d.sanitary_options.get(k, True)))
            cb.setEnabled(d.sanitary)
            cb.blockSignals(False)
        self.summary.setText(f"<b>Model:</b> {d.describe()}")

    def _fill_uh_rows(self) -> None:
        for widgets in self._uh_rows:
            for w in widgets:
                self.uh_grid.removeWidget(w)
                w.deleteLater()
        self._uh_rows = []
        d = self.design
        n = len(d.routing)
        for i, key in enumerate(d.routing):
            label = QLabel(f"UH {i + 1}")
            combo = QComboBox()
            for k in ROUTING_KEYS:
                combo.addItem(COMPONENTS[k].label, k)
                if d.losses is None and k in NEEDS_LOSSES:
                    model = combo.model()
                    if isinstance(model, QStandardItemModel):
                        model.item(combo.count() - 1).setEnabled(False)
            combo.setCurrentIndex(combo.findData(key))
            combo.setToolTip(COMPONENTS[key].description)
            combo.activated.connect(lambda _=0, i=i, c=combo: self._retype(i, c.currentData()))
            up, down = QToolButton(), QToolButton()
            for b, arrow, tip in ((up, Qt.ArrowType.UpArrow, "Move up"), (down, Qt.ArrowType.DownArrow, "Move down")):
                b.setArrowType(arrow)
                b.setAutoRaise(True)
                b.setToolTip(tip)
            up.setEnabled(i > 0)
            down.setEnabled(i < n - 1)
            up.clicked.connect(lambda _=False, i=i: self._move(i, -1))
            down.clicked.connect(lambda _=False, i=i: self._move(i, 1))
            remove = _tool("delete", "Remove this unit hydrograph")
            remove.setEnabled(n > 1)
            remove.clicked.connect(lambda _=False, i=i: self._remove(i))
            widgets = [label, combo, up, down, remove]
            for c, w in enumerate(widgets):
                self.uh_grid.addWidget(w, i, c)
            self.uh_grid.setColumnStretch(1, 1)
            self._uh_rows.append(widgets)

    # ------------------------------------------------------------------ edits

    def _commit(self, new: ProcessDesign, uh_map: dict[int, int] | None = None) -> None:
        problems = new.problems()
        if problems:
            self.message.setText(" ".join(problems))
            self._refresh()  # put the controls back to the current design
            return
        old = self.design
        self.message.clear()
        self.readonly.hide()
        self.design = new
        self._refresh()
        self.changed.emit(to_tree(new), renames(old, new, uh_map))

    def _losses_changed(self) -> None:
        new = self.design.copy()
        new.losses = self.losses.currentData()
        new.snow = new.snow and new.losses == "initial-abstraction"
        new.loss_options = {}
        self._commit(new)

    def _snow_changed(self, on: bool) -> None:
        new = self.design.copy()
        new.snow = on
        self._commit(new)

    def _add(self, key: str) -> None:
        new = self.design.copy()
        new.routing.append(key)
        self._commit(new)

    def _retype(self, i: int, key: str) -> None:
        if key == self.design.routing[i]:
            return
        new = self.design.copy()
        new.routing[i] = key
        self._commit(new)

    def _move(self, i: int, d: int) -> None:
        j = i + d
        new = self.design.copy()
        new.routing[i], new.routing[j] = new.routing[j], new.routing[i]
        mapping = {k: k for k in range(len(new.routing))}
        mapping[i], mapping[j] = j, i
        self._commit(new, mapping)

    def _remove(self, i: int) -> None:
        new = self.design.copy()
        del new.routing[i]
        mapping = {k: (k if k < i else k - 1) for k in range(len(self.design.routing)) if k != i}
        self._commit(new, mapping)

    def _sanitary_changed(self, on: bool) -> None:
        new = self.design.copy()
        new.sanitary = on
        self._commit(new)

    def _sanitary_options_changed(self) -> None:
        opts = {k: cb.isChecked() for k, cb in self.san_opts.items()}
        if not any(opts.values()):  # the pattern needs at least one factor
            self._refresh()
            return
        new = self.design.copy()
        new.sanitary_options = opts
        self._commit(new)


__all__ = ["LOSS_KEYS", "ProcessBuilder"]
