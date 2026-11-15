"""Form generated from :class:`~sparsehydro_viewer.core.options.OptionSpec` descriptors."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit, QSpinBox, QWidget

from ..core.options import OptionSpec

_INT_MAX = 2_000_000_000


class OptionForm(QWidget):
    """Editable form; :attr:`changed` fires on any edit."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, choice_labels: dict[Any, str] | None = None) -> None:
        super().__init__(parent)
        self.layout_ = QFormLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.choice_labels = choice_labels or {}
        self._specs: list[OptionSpec] = []
        self._editors: dict[str, QWidget] = {}

    def set_specs(self, specs: tuple[OptionSpec, ...] | list[OptionSpec], values: dict[str, Any] | None = None) -> None:
        while self.layout_.rowCount():
            self.layout_.removeRow(0)
        self._specs = list(specs)
        self._editors = {}
        for s in self._specs:
            w = self._editor(s)
            w.setToolTip(s.doc)
            self._editors[s.name] = w
            self.layout_.addRow(s.display_label, w)
        self.set_values(values or {})

    def _editor(self, s: OptionSpec) -> QWidget:
        if s.kind == "int":
            w = QSpinBox()
            w.setRange(int(s.minimum) if s.minimum is not None else -_INT_MAX,
                       int(s.maximum) if s.maximum is not None else _INT_MAX)
            w.valueChanged.connect(self.changed)
            return w
        if s.kind == "float":
            d = QDoubleSpinBox()
            d.setDecimals(4)
            d.setRange(s.minimum if s.minimum is not None else -1e12, s.maximum if s.maximum is not None else 1e12)
            d.valueChanged.connect(self.changed)
            return d
        if s.kind == "bool":
            c = QCheckBox()
            c.toggled.connect(self.changed)
            return c
        if s.kind == "choice":
            cb = QComboBox()
            for ch in s.choices:
                cb.addItem(self.choice_labels.get(ch, str(ch)), ch)
            cb.currentIndexChanged.connect(self.changed)
            return cb
        e = QLineEdit()
        e.editingFinished.connect(self.changed)
        return e

    def set_values(self, values: dict[str, Any]) -> None:
        for s in self._specs:
            w = self._editors[s.name]
            v = values.get(s.name, s.default)
            w.blockSignals(True)
            if isinstance(w, QSpinBox):
                w.setValue(int(v))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(v))
            elif isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                i = w.findData(v)
                w.setCurrentIndex(max(i, 0))
            elif isinstance(w, QLineEdit):
                w.setText(str(v))
            w.blockSignals(False)

    def values(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for s in self._specs:
            w = self._editors[s.name]
            if isinstance(w, QSpinBox):
                out[s.name] = int(w.value())
            elif isinstance(w, QDoubleSpinBox):
                out[s.name] = float(w.value())
            elif isinstance(w, QCheckBox):
                out[s.name] = bool(w.isChecked())
            elif isinstance(w, QComboBox):
                out[s.name] = w.currentData()
            elif isinstance(w, QLineEdit):
                out[s.name] = w.text()
        return out
