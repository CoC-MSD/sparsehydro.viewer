from __future__ import annotations

import numpy as np
import pytest

from sparsehydro_viewer.core.catalog import ParameterInfo
from sparsehydro_viewer.core.options import OptionSpec
from sparsehydro_viewer.widgets import (
    AxisSpec,
    OptionForm,
    ParallelCoordinates,
    ParameterPanel,
    ParetoLayer,
    ParetoPlot,
)
from sparsehydro_viewer.widgets.parameter_panel import from_slider, to_slider, use_log_scale


@pytest.mark.parametrize("lo,hi,v", [(0.0, 1.0, 0.37), (0.01, 500.0, 3.2), (-5.0, 5.0, -1.0)])
def test_slider_mapping_round_trips(lo, hi, v) -> None:
    log = use_log_scale(lo, hi)
    assert from_slider(to_slider(v, lo, hi, log), lo, hi, log) == pytest.approx(v, rel=0.01, abs=(hi - lo) / 500)


def test_log_scale_rule() -> None:
    assert use_log_scale(0.01, 500.0) and not use_log_scale(0.0, 500.0) and not use_log_scale(1.0, 10.0)


def _infos() -> list[ParameterInfo]:
    return [ParameterInfo("A", 100.0, 0.0, 1e4, "", "amplitude", True, 100.0),
            ParameterInfo("tp", 5.0, 0.01, 500.0, "steps", "", True, 5.0)]


def test_parameter_panel_batches_slider_moves(qtbot) -> None:
    panel = ParameterPanel()
    qtbot.addWidget(panel)
    panel.set_parameters(_infos())
    with qtbot.waitSignal(panel.valuesEdited, timeout=1000) as blocker:
        panel.rows["A"].slider.setValue(500)
        panel.rows["tp"].spin.setValue(12.0)
    vals = blocker.args[0]
    assert vals["A"] == pytest.approx(5000.0) and vals["tp"] == pytest.approx(12.0)


def test_parameter_panel_bounds_and_calibrate(qtbot) -> None:
    panel = ParameterPanel()
    qtbot.addWidget(panel)
    panel.set_parameters(_infos())
    with qtbot.waitSignal(panel.boundsEdited) as b:
        row = panel.rows["A"]
        row.lo_edit.setText("10")
        row.hi_edit.setText("50")
        row._bounds_edited()
    assert b.args == ["A", 10.0, 50.0]
    assert panel.rows["A"].value() == 50.0  # clamped into the new range
    with qtbot.waitSignal(panel.calibrateToggled) as c:
        panel.rows["tp"].check.setChecked(False)
    assert c.args == ["tp", False]
    assert "1 calibrated" in panel.summary.text()


def test_set_values_does_not_echo(qtbot) -> None:
    panel = ParameterPanel()
    qtbot.addWidget(panel)
    panel.set_parameters(_infos())
    with qtbot.assertNotEmitted(panel.valuesEdited, wait=100):
        panel.set_values({"A": 42.0})
    assert panel.rows["A"].value() == 42.0


def test_option_form_round_trip(qtbot) -> None:
    form = OptionForm()
    qtbot.addWidget(form)
    specs = (OptionSpec("n", "int", 3, minimum=1), OptionSpec("x", "float", 0.5),
             OptionSpec("flag", "bool", True), OptionSpec("kind", "choice", "a", choices=("a", "b")))
    form.set_specs(specs, {"n": 7, "kind": "b"})
    assert form.values() == {"n": 7, "x": 0.5, "flag": True, "kind": "b"}


def _pc(qtbot) -> ParallelCoordinates:
    pc = ParallelCoordinates()
    qtbot.addWidget(pc)
    data = np.array([[0.9, 10.0, 1.0], [0.5, 2.0, 2.0], [0.7, 6.0, 3.0], [0.2, 1.0, 4.0]])
    axes = [AxisSpec("nse", "NSE", "max", kind="objective"), AxisSpec("rmse", "RMSE", "min", kind="objective"),
            AxisSpec("k", "k")]
    pc.set_data(axes, data)
    return pc


def test_parallel_brushing_filters_rows(qtbot) -> None:
    pc = _pc(qtbot)
    assert pc.selected_rows() == [0, 1, 2, 3]
    # NSE axis is "max", so normalised value is (v - 0.2) / 0.7; keep the top half.
    with qtbot.waitSignal(pc.selectionChanged) as sig:
        pc._set_brush(0, 0.5, 1.0, final=True)
    assert sig.args[0] == [0, 2]
    # RMSE is "min", so it is flipped: normalised = 1 - (v - 1) / 9 -> rows 0.0, 0.89, 0.44, 1.0.
    pc._set_brush(1, 0.8, 1.0, final=True)
    assert pc.selected_rows() == []  # rows 1 and 3 have low RMSE but were removed by the NSE brush
    pc._set_brush(1, 0.4, 0.5, final=True)
    assert pc.selected_rows() == [2]
    pc._clear_brush(1)
    assert pc.selected_rows() == [0, 2]


def test_parallel_brush_survives_data_refresh(qtbot) -> None:
    pc = _pc(qtbot)
    pc._set_brush(2, 0.0, 0.4, final=True)
    before = pc.selected_rows()
    pc.set_data([AxisSpec("nse", "NSE", "max"), AxisSpec("rmse", "RMSE", "min"), AxisSpec("k", "k")],
                pc.s.data.copy(), keep_brushes=True)
    assert pc.selected_rows() == before


def test_parallel_pick_line(qtbot) -> None:
    from PySide6.QtCore import QPointF

    pc = _pc(qtbot)
    norm = pc._normalised()
    with qtbot.waitSignal(pc.rowClicked) as sig:
        pc._pick_line(QPointF(0.0, float(norm[2, 0])))
    assert sig.args == [2]


def test_pareto_plot_axes_and_click(qtbot) -> None:
    pp = ParetoPlot(labels={"nse": "NSE"}, better={"nse": "max", "pbias": "min"})
    qtbot.addWidget(pp)
    pp.set_layers([ParetoLayer("r1", "run", np.array([[0.5, 3.0], [0.8, 9.0]]), ["nse", "pbias"], "#0072B2",
                               knee=0)])
    assert pp.x_combo.currentData() == "nse" and pp.y_combo.currentData() == "pbias"
    assert "higher is better" in pp.x_combo.currentText()
    pp.set_selection("r1", [1])
    pp.set_marker({"nse": 0.6, "pbias": 4.0})
    with qtbot.waitSignal(pp.pointClicked) as sig:
        class _P:
            def data(self):
                return 1
        pp._clicked("r1", [_P()])
    assert sig.args == ["r1", 1]


def test_pareto_click_through_scatter_signal(qtbot) -> None:
    """Regression: sigClicked passes a mouse event as a third argument, which must not replace the key."""
    import pyqtgraph as pg

    pp = ParetoPlot()
    qtbot.addWidget(pp)
    pp.set_layers([ParetoLayer("run-a", "run", np.array([[0.5, 3.0], [0.8, 9.0]]), ["nse", "pbias"], "#0072B2")])
    scatter = next(i for i in pp.plot.listDataItems() if isinstance(i, pg.ScatterPlotItem))
    with qtbot.waitSignal(pp.pointClicked) as sig:
        scatter.sigClicked.emit(scatter, scatter.points()[1:2], object())
    assert sig.args == ["run-a", 1]
