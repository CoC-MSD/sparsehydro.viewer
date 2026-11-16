"""Legend entries switch series on and off, and the hidden state survives redraws."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QMenu

from sparsehydro_viewer.widgets import ParallelCoordinates, ParetoLayer, ParetoPlot, TimeseriesPlot
from sparsehydro_viewer.widgets.parallel_coords import AxisSpec


def _click(plot_legend, name: str) -> None:
    """Click the legend sample of *name*, as the mouse would (pyqtgraph toggles the item, then reports it)."""
    for sample, label in plot_legend.items:
        if label.text == name:
            sample.item.setVisible(not sample.item.isVisible())
            sample.sigClicked.emit(sample.item)
            return
    raise AssertionError(f"no legend entry {name!r}: {[lab.text for _s, lab in plot_legend.items]}")


def test_timeseries_legend_hides_curves_bands_and_stacks_across_redraws(qtbot) -> None:
    plot = TimeseriesPlot()
    qtbot.addWidget(plot)
    t = np.arange(50.0)
    y = np.sin(t / 5) + 2

    def draw() -> None:  # what a page does on every update
        plot.set_data(t, np.zeros(50), y, "Observed")
        plot.remove_curve("sim")
        plot.set_curve("sim", t, y * 0.9, color="#D55E00", name="Simulated")
        plot.set_band("band", t, y * 0.8, y * 1.1, "#D55E00", name="Pareto range")
        plot.set_stack("parts", t, [("UH 1", y * 0.5, "#0072B2"), ("UH 2", y * 0.4, "#009E73")])

    draw()
    toggle = plot.legend_toggle
    assert set(toggle.names()) == {"Observed", "Simulated", "Pareto range", "UH 1", "UH 2"}
    with qtbot.waitSignal(toggle.visibilityChanged) as sig:
        _click(plot.legend, "Pareto range")
    assert sig.args == ["Pareto range", False] and not plot._bands["band"].isVisible()  # the fill, not only the swatch
    _click(plot.legend, "Simulated")
    _click(plot.legend, "UH 1")
    assert not plot._curves["sim"].isVisible()
    assert [i.isVisible() for i in plot._stacks["parts"]] == [False, False, True, True]  # fill and edge of UH 1

    draw()  # a redraw (slider move, new selection) keeps them hidden
    assert not plot._curves["sim"].isVisible() and not plot._bands["band"].isVisible()
    assert plot._obs_item.isVisible() and toggle.hidden == {"Pareto range", "Simulated", "UH 1"}

    _click(plot.legend, "Simulated")  # click again: shown
    assert plot._curves["sim"].isVisible() and "Simulated" not in toggle.hidden

    # the keyboard route: a menu of checkable actions with the same state
    menu = QMenu()
    toggle.fill_menu(menu)
    actions = {a.text(): a for a in menu.actions() if a.text()}
    assert not actions["Pareto range"].isChecked() and actions["Observed"].isChecked()
    actions["Pareto range"].setChecked(True)
    assert plot._bands["band"].isVisible()
    toggle.show_only("Observed")
    assert toggle.hidden == {"Simulated", "Pareto range", "UH 1", "UH 2"}
    actions["Show all"].trigger()
    assert not toggle.hidden and plot._curves["sim"].isVisible()


def test_panel_legends_toggle_and_survive_a_rebuild(qtbot) -> None:
    plot = TimeseriesPlot()
    qtbot.addWidget(plot)
    t = np.arange(20.0)
    plot.set_data(t, np.zeros(20), t)
    panels = [("in", "Depth [in]", [("IA left", t * 0.1, "#0072B2", False), ("Storage", t * 0.2, "#009E73", False)])]
    plot.set_panels(panels, t)
    panel, curves = plot._panels["in"]
    _click(panel.legend, "Storage")
    assert not curves["Storage"].isVisible()
    plot.set_panels([*panels, ("degC", "Temperature [degC]", [("Temperature", t, "#D55E00", True)])], t)  # rebuilt
    assert not plot._panels["in"][1]["Storage"].isVisible() and plot._panels["in"][1]["IA left"].isVisible()


def test_pareto_and_parallel_legends_keep_hidden_layers(qtbot) -> None:
    pareto = ParetoPlot()
    qtbot.addWidget(pareto)
    F = np.random.default_rng(0).random((8, 2))
    layers = [ParetoLayer("a", "Run A", F, ["f1", "f2"], "#0072B2", knee=2),
              ParetoLayer("h0", "earlier generations", F + 1, ["f1", "f2"], "#888888", alpha=40, legend=False),
              ParetoLayer("h1", "earlier generations", F + 0.5, ["f1", "f2"], "#888888", alpha=90)]
    pareto.set_layers(layers)
    pareto.set_marker({"f1": 0.5, "f2": 0.5}, "sliders")
    assert set(pareto.legend_toggle.names()) == {"Run A", "earlier generations", "sliders"}
    _click(pareto.legend, "earlier generations")  # both history layers go together
    pareto.set_selection("a", [1, 3])  # a redraw
    scatters = [i for i in pareto.plot.getPlotItem().items if hasattr(i, "points")]
    hidden = [s for s in scatters if not s.isVisible()]
    assert len(hidden) == 2 and pareto.legend_toggle.hidden == {"earlier generations"}

    pc = ParallelCoordinates()
    qtbot.addWidget(pc)
    axes = [AxisSpec("f1"), AxisSpec("f2"), AxisSpec("p")]
    data = np.random.default_rng(1).random((10, 3))
    pc.set_data(axes, data, groups=np.r_[np.zeros(5, int), np.ones(5, int)], group_labels=["Run A", "Run B"],
                group_colors=["#0072B2", "#E69F00"])
    _click(pc.legend, "Run B")
    pc.set_highlight([1, 2])  # redraws everything
    assert pc.legend_toggle.hidden == {"Run B"}
    names = {lab.text: s.item.isVisible() for s, lab in pc.legend.items}
    assert names["Run B"] is False and names["Run A"] is True and names["primary"] is True


def test_series_button_on_the_toolbar_lists_the_active_charts_series(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    from sparsehydro_viewer.widgets.chart_actions import ChartActions

    host = QWidget()
    qtbot.addWidget(host)
    actions = ChartActions(host)
    plot = TimeseriesPlot()
    qtbot.addWidget(plot)
    t = np.arange(10.0)
    plot.set_data(t, None, t, "Observed")
    plot.set_curve("sim", t, t * 2, color="#D55E00", name="Simulated")
    assert not actions.series.isEnabled()
    actions.bind(plot)
    assert actions.series.isEnabled() and actions.series in actions.actions()
    actions._fill_series_menu()
    entries = {a.text(): a for a in actions._series_menu.actions() if a.text()}
    assert {"Observed", "Simulated", "Show all"} <= set(entries)
    entries["Simulated"].setChecked(False)
    assert not plot._curves["sim"].isVisible()
