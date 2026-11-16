"""The analysis dataset, shown (and switchable) on the standard toolbar of every page.

Every analysis (model, events, calibration, exploration, comparison) runs on
the session's current dataset; this widget keeps it in view so it is always
clear which data a result belongs to.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from ...resources import icon


class DatasetSelector(QWidget):
    def __init__(self, session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(4)
        self.icon = QLabel()
        self.icon.setPixmap(icon("nav-data").pixmap(18, 18))
        self.label = QLabel("Dataset")
        self.label.setObjectName("hint")
        self.combo = QComboBox()
        self.combo.setObjectName("datasetSelector")
        self.combo.setMinimumWidth(220)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.icon)
        lay.addWidget(self.label)
        lay.addWidget(self.combo)
        self._syncing = False
        self.combo.currentIndexChanged.connect(self._picked)
        for sig in (session.datasetChanged, session.projectChanged, session.nodesStructureChanged,
                    session.periodsChanged):
            sig.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        s = self.session
        self._syncing = True
        self.combo.clear()
        for d in s.project.datasets:
            self.combo.addItem(d.name, d.name)
            self.combo.setItemData(self.combo.count() - 1, self._tip(d), Qt.ItemDataRole.ToolTipRole)
        if not s.project.datasets:
            self.combo.addItem("No dataset — import data on the Sites page", None)
        idx = self.combo.findData(s.dataset_name) if s.dataset_name else 0
        self.combo.setCurrentIndex(max(0, idx))
        self.combo.setEnabled(bool(s.project.datasets))
        ds = s.dataset
        self.combo.setToolTip(self._tip(ds) if ds is not None else "The dataset every analysis page uses")
        self._syncing = False

    def _tip(self, d) -> str:
        st = self.session.store
        site = st.node(d.site_iri) if d.site_iri else None

        def period(p) -> str:
            return "whole record" if p.is_open else f"{(p.start or '')[:10]} → {(p.end or '')[:10]}"

        lines = [f"<b>{d.name}</b>"]
        if site is not None:
            lines.append(f"Site: {site.label}")
        lines.append(f"Calibration: {period(d.calibration)}")
        if not d.validation.is_open:
            lines.append(f"Validation: {period(d.validation)}")
        inputs = self.session.inputs_text(d.name)
        if inputs:
            lines.append(f"Inputs - {inputs}")
        lines.append("Used by every analysis page.")
        return "<br>".join(lines)

    def _picked(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        name = self.combo.itemData(index)
        if name:
            self.session.select_dataset(name)


__all__ = ["DatasetSelector"]
