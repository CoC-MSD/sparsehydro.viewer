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


#: Earlier generations drawn at most (evenly thinned beyond), to keep the scatter responsive.
MAX_HISTORY_LAYERS = 40
HISTORY_LABEL = "earlier generations"


def history_key(run_id: str, report: int) -> str:
    """Layer key of a run's report (see :func:`parse_history_key`)."""
    return f"{run_id}:h{report}"


def parse_history_key(key: str) -> tuple[str, int | None]:
    """``(run id, report)`` of a layer key; report is ``None`` for the run's final front."""
    run_id, sep, tail = key.rpartition(":h")
    if sep and tail.isdigit():
        return run_id, int(tail)
    return key, None


def history_layers(run, upto: int | None = None, color: str = "#888888"):
    """Scatter layers of the fronts a run reported before report *upto* (default: all), fainter the older.

    A report whose parameter sets are stored is clickable (its solutions can be selected and simulated);
    others are context only. The layers do not set the axes: early, poor solutions would squeeze the front.
    """
    import numpy as np

    from ..widgets import ParetoLayer

    n = len(run.history) if upto is None else min(upto, len(run.history))
    earlier = list(range(n))
    if len(earlier) > MAX_HISTORY_LAYERS:
        earlier = sorted(set(np.linspace(0, n - 1, MAX_HISTORY_LAYERS).round().astype(int).tolist()))
    flags = np.asarray(run.minimize_flags, dtype=bool)
    layers = []
    for m, g in enumerate(earlier):
        F = np.atleast_2d(run.history[g][2])
        if not F.size:
            continue
        age = (g + 1) / max(n, 1)  # 0 (oldest) .. 1 (newest)
        layers.append(ParetoLayer(history_key(run.id, g), HISTORY_LABEL, np.where(flags, F, -F),
                                  run.objective_names, color, size=6, alpha=int(20 + 120 * age),
                                  legend=m == len(earlier) - 1, clickable=run.history_X(g) is not None,
                                  in_range=False))
    return layers


def hbox(*widgets: QWidget, stretch_last: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        lay.addWidget(w)
    if not stretch_last:
        lay.addStretch(1)
    return lay
