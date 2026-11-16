"""Calibrate monitor: which run is shown, overlay of running runs, front history and front statistics."""

from __future__ import annotations

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.runs import RunRecord, new_id
from sparsehydro_viewer.core.solvers import SolverSpec


@pytest.fixture
def window(qtbot):
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    win = MainWindow()
    win.show()
    yield win
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()


def _run(label: str, n_reports: int, seed: int) -> RunRecord:
    """A finished two-objective run whose reported fronts move towards the origin."""
    rng = np.random.default_rng(seed)
    history = []
    t = np.sort(rng.random(6))
    for g in range(1, n_reports + 1):
        shift = 1.0 / g
        history.append((g, 10 * g, np.column_stack([t + shift, 1 - t + shift])))
    final = history[-1][2]
    return RunRecord(new_id(), label, "sample", spec_for("gamma-uh"),
                     [ObjectiveSpec("rmse"), ObjectiveSpec("pbias")], SolverSpec("nsga2"), status="finished",
                     param_names=["alpha", "theta"], objective_names=["rmse", "pbias"], minimize_flags=[True, True],
                     pareto_X=rng.random((len(final), 2)), pareto_F=final, history=history)


def test_monitor_shows_a_chosen_run_with_its_history(window) -> None:
    s = window.ctx.session
    page = next(p for p in window.pages if p.title == "Calibrate")
    a, b = _run("A", 12, 1), _run("B", 5, 2)
    s.add_run(a)
    s.add_run(b)
    assert [page.monitor_box.itemData(i) for i in range(page.monitor_box.count())] == \
        [page.SELECTED, page.ACTIVE, b.id, a.id]

    page.monitor_box.setCurrentIndex(page.monitor_box.findData(a.id))
    assert [r.id for r in page._monitored()] == [a.id]
    assert page.generation.maximum() == 12 and page.generation.value() == 12
    assert page.front_box.title() == "Final front"

    # earlier generations, faded and not clickable, behind the final front
    page.history.setChecked(True)
    layers = page.front._layers
    assert len(layers) == 12 and layers[-1].key == a.id
    assert all(not layer.clickable and not layer.in_range and layer.alpha is not None for layer in layers[:-1])
    assert layers[0].alpha < layers[-2].alpha  # older is fainter
    assert sum(layer.legend for layer in layers[:-1]) == 1

    # replay: drag back to report 4
    page.generation.setValue(4)
    assert page.front_box.title() == "Front at report 4 of 12" and len(page.front._layers) == 4
    np.testing.assert_allclose(page.front._layers[-1].values, a.history[3][2])

    # front statistics as convergence measures
    page.conv_obj.setCurrentIndex(page.conv_obj.findData(page.HV))
    curve = page.conv.getPlotItem().listDataItems()[0]
    x, y = curve.getData()
    assert list(x) == [10 * g for g in range(1, 13)] and np.all(np.diff(y) >= -1e-12)
    page.conv_obj.setCurrentIndex(page.conv_obj.findData(page.SIZE))
    assert set(page.conv.getPlotItem().listDataItems()[0].getData()[1]) == {6}


def test_monitor_overlays_running_runs(window, monkeypatch) -> None:
    s = window.ctx.session
    page = next(p for p in window.pages if p.title == "Calibrate")
    a, b, c = _run("A", 6, 1), _run("B", 4, 2), _run("C", 3, 3)
    for r in (a, b, c):
        s.add_run(r)
    running = {a.id, c.id}
    monkeypatch.setattr(window.ctx.calibration, "is_active", lambda rid: rid in running)
    page.monitor_box.setCurrentIndex(page.monitor_box.findData(page.ACTIVE))
    assert [r.id for r in page._monitored()] == [a.id, c.id]
    assert [layer.key for layer in page.front._layers] == [a.id, c.id]
    assert len(page.conv.getPlotItem().listDataItems()) == 2
    assert not page.history.isEnabled() and page.front_box.title() == "Current fronts"
    # nothing running: falls back to the selected run
    running.clear()
    page._monitor_id = b.id
    page._draw_monitor()
    assert [r.id for r in page._monitored()] == [b.id]
