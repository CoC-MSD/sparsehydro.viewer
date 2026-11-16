"""Observed-vs-model scatter plots of event volumes, one per MSDGC zone (Guidelines Figure 7-2)."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal

from .. import theme

PANELS = (("conveyance", "Conveyance"), ("storage", "Overflow/storage"), ("treatment", "Treatment"),
          ("event", "Whole event"))


class AssessScatter(pg.GraphicsLayoutWidget):
    """2 x 2 scatter grid with 1:1 line and ±10 % / ±20 % bands; click a point to pick its event.

    Critical-month events are triangles, others circles (shape, not only colour, tells them apart);
    the Con15 events are ringed.
    """

    eventClicked = Signal(object)  # event_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackground(theme.current().plot_bg)
        self.setAccessibleName("Observed versus model event volumes by zone")
        self.plots: dict[str, pg.PlotItem] = {}
        for i, (key, title) in enumerate(PANELS):
            p = self.addPlot(row=i // 2, col=i % 2, title=title)
            theme.plain_axes(p)
            p.setLabel("bottom", "Observed [MG]")
            p.setLabel("left", "Model [MG]")
            p.showGrid(x=True, y=True, alpha=0.15)
            p.setAspectLocked(False)
            self.plots[key] = p
        self.result = None

    def set_result(self, result) -> None:
        """Draw an :class:`~sparsehydro.studies.msdgc.scorecard.MSDGCScorecardResult`."""
        self.result = result
        th = theme.current()
        ev = result.events[result.events["included"]] if len(result.events) else result.events
        summary = result.summary.set_index("group").loc["all"] if len(result.summary) else None
        band_pass = result.criteria.pass_percent / 100.0
        band_fail = result.criteria.fail_percent / 100.0
        for key, title in PANELS:
            p = self.plots[key]
            p.clear()
            if ev is None or not len(ev):
                p.setTitle(f"{title}: no events")
                continue
            x = ev[f"observed_{key}_mg"].to_numpy(float)
            y = ev[f"modeled_{key}_mg"].to_numpy(float)
            top = float(np.nanmax(np.concatenate([x, y]))) * 1.08 if np.isfinite(x).any() else 1.0
            line = np.array([0.0, top])
            p.plot(line, line, pen=_pen(th.plot_fg, 1.2))
            for f, style in ((band_pass, Qt.PenStyle.DashLine), (band_fail, Qt.PenStyle.DotLine)):
                for s in (1 + f, 1 - f):
                    p.plot(line, s * line, pen=_pen(th.muted, 1.0, style))
            crit = ev["critical"].to_numpy(bool)
            ids = ev["event_id"].to_list()
            for mask, symbol, color, name in ((crit, "t", theme.series_color(1), "critical months (Apr-Jul)"),
                                              (~crit, "o", theme.series_color(0), "other months")):
                if mask.any():
                    item = pg.ScatterPlotItem(x[mask], y[mask], symbol=symbol, size=10, brush=pg.mkBrush(color),
                                              pen=pg.mkPen(th.plot_bg), data=[i for i, m in zip(ids, mask) if m],
                                              name=name, hoverable=True,
                                              tip=lambda x_, y_, d: f"event {d}\nobserved {x_:.4g} MG\nmodel {y_:.4g} MG")
                    item.sigClicked.connect(lambda _item, points, *_: self._clicked(points))
                    p.addItem(item)
            if key == "conveyance" and "con15" in ev:
                sel = ev["con15"].to_numpy(bool)
                if sel.any():
                    p.addItem(pg.ScatterPlotItem(x[sel], y[sel], symbol="o", size=18, brush=None,
                                                 pen=pg.mkPen(th.selection, width=2)))
            ccc = summary[f"{key}_ccc"] if summary is not None and f"{key}_ccc" in summary else None
            label = title if ccc is None else f"{title}: rc = {ccc:.3f}" if not math.isnan(ccc) else f"{title}: rc —"
            p.setTitle(label)
            p.setXRange(0, top, padding=0)
            p.setYRange(0, top, padding=0)

    def _clicked(self, points) -> None:
        if len(points):
            self.eventClicked.emit(points[0].data())


def _pen(color: str, width: float, style: Qt.PenStyle = Qt.PenStyle.SolidLine):
    p = pg.mkPen(color, width=width)
    p.setStyle(style)
    p.setCosmetic(True)
    return p


__all__ = ["PANELS", "AssessScatter"]
