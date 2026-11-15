"""Working-model parameter panel: sliders, bounds and calibrate flags, grouped by component."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.catalog import ParameterInfo

STEPS = 1000
COLLAPSE_ABOVE = 12  # sections with more parameters than this start collapsed


def use_log_scale(lower: float, upper: float) -> bool:
    """Log sliders for strictly positive ranges spanning two decades or more."""
    return lower > 0 and upper / lower >= 100.0


def to_slider(value: float, lower: float, upper: float, log: bool) -> int:
    if upper <= lower:
        return 0
    v = min(max(value, lower), upper)
    f = (math.log(v / lower) / math.log(upper / lower)) if log else (v - lower) / (upper - lower)
    return int(round(f * STEPS))


def from_slider(pos: int, lower: float, upper: float, log: bool) -> float:
    f = pos / STEPS
    return lower * (upper / lower) ** f if log else lower + f * (upper - lower)


def _decimals(lower: float, upper: float) -> int:
    span = abs(upper - lower) or 1.0
    return max(2, min(8, 3 - int(math.floor(math.log10(span))) + 1))


class ParameterRow:
    """Widgets for one parameter (a row in a section grid)."""

    def __init__(self, panel: ParameterPanel, info: ParameterInfo) -> None:
        self.panel = panel
        self.info = info
        self.name = info.name
        self.lower, self.upper = info.lower, info.upper
        self.log = use_log_scale(self.lower, self.upper)
        self.check = QCheckBox()
        self.check.setChecked(info.calibrate)
        self.check.setToolTip("Calibrate this parameter (unchecked = held fixed)"
                              + ("; applies to the whole vector" if info.vector else ""))
        unit = f" [{info.units}]" if info.units else ""
        self.label = QLabel(f"{info.name}{unit}")
        tip = info.description or info.name
        self.label.setToolTip(f"{info.name}\n{tip}\ndefault {info.default:.4g}" + ("\nlog-scaled slider" if self.log else ""))
        validator = QDoubleValidator()
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation)
        self.lo_edit, self.hi_edit = QLineEdit(f"{self.lower:.4g}"), QLineEdit(f"{self.upper:.4g}")
        for e in (self.lo_edit, self.hi_edit):
            e.setValidator(validator)
            e.setFixedWidth(60)
            e.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lo_edit.setToolTip("Lower bound")
        self.hi_edit.setToolTip("Upper bound")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, STEPS)
        self.slider.setMinimumWidth(90)
        self.spin = QDoubleSpinBox()
        self.spin.setKeyboardTracking(False)
        self.spin.setFixedWidth(88)
        self.reset = QToolButton()
        self.reset.setText("↺")
        self.reset.setToolTip(f"Reset to default ({info.default:.4g})")
        self._configure_range()
        self.set_value(info.value)
        self.slider.valueChanged.connect(self._slider_moved)
        self.spin.valueChanged.connect(self._spin_changed)
        self.check.toggled.connect(lambda on: panel._calibrate_toggled(self, on))
        self.lo_edit.editingFinished.connect(self._bounds_edited)
        self.hi_edit.editingFinished.connect(self._bounds_edited)
        self.reset.clicked.connect(lambda: self._user_value(self.info.default))

    def widgets(self) -> list[QWidget]:
        return [self.check, self.label, self.lo_edit, self.slider, self.hi_edit, self.spin, self.reset]

    def set_visible(self, on: bool) -> None:
        for w in self.widgets():
            w.setVisible(on)

    def _configure_range(self) -> None:
        self.spin.blockSignals(True)
        self.spin.setDecimals(_decimals(self.lower, self.upper))
        self.spin.setRange(self.lower, self.upper)
        self.spin.setSingleStep((self.upper - self.lower) / 100.0 or 0.01)
        self.spin.blockSignals(False)

    def value(self) -> float:
        return float(self.spin.value())

    def set_value(self, value: float) -> None:
        for w in (self.slider, self.spin):
            w.blockSignals(True)
        self.spin.setValue(value)
        self.slider.setValue(to_slider(value, self.lower, self.upper, self.log))
        for w in (self.slider, self.spin):
            w.blockSignals(False)

    def _user_value(self, value: float) -> None:
        self.set_value(value)
        self.panel._value_edited(self.name, self.value())

    def _slider_moved(self, pos: int) -> None:
        v = from_slider(pos, self.lower, self.upper, self.log)
        self.spin.blockSignals(True)
        self.spin.setValue(v)
        self.spin.blockSignals(False)
        self.panel._value_edited(self.name, v)

    def _spin_changed(self, v: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(to_slider(v, self.lower, self.upper, self.log))
        self.slider.blockSignals(False)
        self.panel._value_edited(self.name, v)

    def _bounds_edited(self) -> None:
        try:
            lo, hi = float(self.lo_edit.text()), float(self.hi_edit.text())
        except ValueError:
            lo, hi = self.lower, self.upper
        if hi <= lo:
            self.lo_edit.setText(f"{self.lower:.4g}")
            self.hi_edit.setText(f"{self.upper:.4g}")
            return
        if (lo, hi) == (self.lower, self.upper):
            return
        value = self.value()
        self.lower, self.upper = lo, hi
        self.log = use_log_scale(lo, hi)
        self._configure_range()
        self.set_value(min(max(value, lo), hi))
        self.panel.boundsEdited.emit(self.name, lo, hi)
        if self.value() != value:
            self.panel._value_edited(self.name, self.value())


class _Section(QWidget):
    """Collapsible group of rows for one model component."""

    def __init__(self, title: str, n: int) -> None:
        super().__init__()
        self.title = title
        self.header = QToolButton()
        self.header.setText(f"{title}   ({n})")
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setStyleSheet("QToolButton { border: none; font-weight: 600; text-align: left; }")
        self.header.toggled.connect(self.set_expanded)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(14, 0, 0, 6)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnStretch(3, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.rows: list[ParameterRow] = []

    def set_expanded(self, on: bool) -> None:
        self.header.blockSignals(True)
        self.header.setChecked(on)
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)

    def add(self, row: ParameterRow) -> None:
        r = len(self.rows)
        for c, w in enumerate(row.widgets()):
            self.grid.addWidget(w, r, c)
        self.rows.append(row)


class ParameterPanel(QWidget):
    """Sections of :class:`ParameterRow`, one per model component.

    Slider moves are batched every 30 ms into one :attr:`valuesEdited`
    emission so a drag produces a steady stream of updates.
    """

    valuesEdited = Signal(dict)
    boundsEdited = Signal(str, float, float)
    calibrateToggled = Signal(str, bool)
    resetRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: dict[str, ParameterRow] = {}
        self.sections: dict[str, _Section] = {}
        self._pending: dict[str, float] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._flush)
        self.calibrateToggled.connect(lambda *_: self.update_summary())

        self.context = QLabel()
        self.context.setObjectName("banner")
        self.context.setWordWrap(True)
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter parameters...")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        expand = QToolButton()
        expand.setText("Expand all")
        expand.clicked.connect(lambda: self._expand_all(True))
        collapse = QToolButton()
        collapse.setText("Collapse all")
        collapse.clicked.connect(lambda: self._expand_all(False))
        reset = QPushButton("Reset all")
        reset.setToolTip("Restore default values, bounds and calibrate flags")
        reset.clicked.connect(self.resetRequested)
        top = QHBoxLayout()
        top.addWidget(self.summary, 1)
        top.addWidget(reset)
        tools = QHBoxLayout()
        tools.addWidget(self.filter, 1)
        tools.addWidget(expand)
        tools.addWidget(collapse)
        header = QHBoxLayout()
        for text, width in (("cal", 22), ("parameter", 0), ("min", 60), ("", 0), ("max", 60), ("value", 88)):
            h = QLabel(text)
            h.setObjectName("hint")
            if width:
                h.setFixedWidth(width)
            header.addWidget(h, 0 if width else 1)
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._host)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.context)
        lay.addLayout(top)
        lay.addLayout(tools)
        lay.addLayout(header)
        lay.addWidget(scroll, 1)

    # ------------------------------------------------------------------ content

    def set_context(self, html: str) -> None:
        """Explain what the sliders drive (shown above the parameters)."""
        self.context.setText(html)

    def set_parameters(self, infos: list[ParameterInfo]) -> None:
        expanded = {t: s.body.isVisible() for t, s in self.sections.items()}
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows.clear()
        self.sections.clear()
        order: list[str] = []
        by_group: dict[str, list[ParameterInfo]] = {}
        for info in infos:
            if info.group not in by_group:
                order.append(info.group)
            by_group.setdefault(info.group, []).append(info)
        for title in order:
            members = by_group[title]
            sec = _Section(title, len(members))
            for info in members:
                row = ParameterRow(self, info)
                self.rows[info.name] = row
                sec.add(row)
            sec.set_expanded(expanded.get(title, len(members) <= COLLAPSE_ABOVE))
            self.sections[title] = sec
            self._host_layout.addWidget(sec)
        self._host_layout.addStretch(1)
        self._apply_filter(self.filter.text())
        self.update_summary()

    def set_values(self, values: dict[str, float]) -> None:
        for name, v in values.items():
            row = self.rows.get(name)
            if row is not None and row.value() != v:
                row.set_value(v)

    def set_calibrate_flags(self, flags: dict[str, bool]) -> None:
        for name, on in flags.items():
            row = self.rows.get(name)
            if row is not None and row.check.isChecked() != on:
                row.check.blockSignals(True)
                row.check.setChecked(on)
                row.check.blockSignals(False)
        self.update_summary()

    def values(self) -> dict[str, float]:
        return {n: r.value() for n, r in self.rows.items()}

    def update_summary(self) -> None:
        n = len(self.rows)
        k = sum(r.check.isChecked() for r in self.rows.values())
        self.summary.setText(f"{n} parameters in {len(self.sections)} components, {k} calibrated")

    # ------------------------------------------------------------------ interaction

    def _apply_filter(self, text: str) -> None:
        text = text.strip().lower()
        for sec in self.sections.values():
            hit_title = bool(text) and text in sec.title.lower()
            visible = 0
            for row in sec.rows:
                show = not text or hit_title or text in row.name.lower()
                row.set_visible(show)
                visible += show
            sec.setVisible(visible > 0)
            if text and visible:
                sec.set_expanded(True)

    def _expand_all(self, on: bool) -> None:
        for sec in self.sections.values():
            sec.set_expanded(on)

    def _calibrate_toggled(self, row: ParameterRow, on: bool) -> None:
        names = [row.name]
        if row.info.vector:  # calibrate applies to the whole vector: keep its rows in step
            names = [n for n, r in self.rows.items() if r.info.vector == row.info.vector]
            for n in names:
                other = self.rows[n]
                if other is not row:
                    other.check.blockSignals(True)
                    other.check.setChecked(on)
                    other.check.blockSignals(False)
        for n in names:
            self.calibrateToggled.emit(n, on)

    def _value_edited(self, name: str, value: float) -> None:
        self._pending[name] = value
        if not self._timer.isActive():
            self._timer.start()

    def _flush(self) -> None:
        if self._pending:
            pending, self._pending = self._pending, {}
            self.valuesEdited.emit(pending)
