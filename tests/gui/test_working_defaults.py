"""A solved solution, selected in a chart, applied as the working model's defaults."""

from __future__ import annotations

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec
from sparsehydro_viewer.core.data import DatasetSpec, Period
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.runs import RunRecord
from sparsehydro_viewer.core.selection import SolutionRef


@pytest.fixture
def window(qtbot):
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    win = MainWindow()
    win.show()
    yield win
    win.ctx.jobs.wait(20000)
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()


def _run(run_id: str, label: str, n: int, seed: int) -> RunRecord:
    rng = np.random.default_rng(seed)
    names = ["alpha", "theta", "A"]
    X = np.column_stack([rng.uniform(1.5, 4, n), rng.uniform(0.5, 3, n), rng.uniform(20, 120, n)])
    t = np.sort(rng.random(n))
    F = np.column_stack([-(0.2 + 0.6 * t), 30 * (1 - t)])
    return RunRecord(run_id, label, "sample", spec_for("gamma-uh"),
                     [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")], None, status="finished",
                     param_names=names, objective_names=["nash_sutcliffe", "pbias"], minimize_flags=[False, True],
                     pareto_X=X, pareto_F=F)


@pytest.fixture
def loaded(window, qtbot, short_frame, sample_csv):
    s = window.ctx.session
    spec = DatasetSpec("sample", path=str(sample_csv), calibration=Period("2022-05-01", "2022-05-05"))
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.add_dataset(spec, short_frame)
    s.add_run(_run("a", "A", 16, 1))
    return window


def test_panel_names_the_selection_and_applies_it(loaded, qtbot) -> None:
    window = loaded
    s, panel = window.ctx.session, window.params
    run = s.run("a")
    assert not panel.use_selected.isEnabled() and "no solution" in panel.selected.text()
    assert "library values" in panel.selected.text() and not panel.restore_defaults.isEnabled()
    assert [a.text() for a in panel._choice_menu.actions()][0] == "Knee (balanced) of A"

    s.set_selection([SolutionRef("a", 3)])  # what a click in any chart does
    assert panel.use_selected.isEnabled() and "A, solution #4" in panel.selected.text()
    with qtbot.waitSignal(s.defaultsChanged):
        panel.use_selected.click()
    want = run.solution_values(3)
    assert s.model_spec.root.type == "gamma-uh"  # the run's model became the working model
    assert s.values == pytest.approx(want)
    assert s.model_spec.defaults == pytest.approx(want)
    assert s.model_spec.defaults_source["run_id"] == "a" and s.model_spec.defaults_source["index"] == 3
    assert "Defaults:</b> A, solution #4" in panel.selected.text() and panel.restore_defaults.isEnabled()
    assert s.dirty

    # Reset (one parameter, then all) returns to the solution, not to the library's value.
    s.set_values({"alpha": 3.9, "theta": 2.9})
    panel.rows["alpha"].reset.click()
    qtbot.waitUntil(lambda: s.values["alpha"] == pytest.approx(want["alpha"], abs=5e-3))  # spin box rounding
    s.reset_parameters()
    assert s.values == pytest.approx(want)

    # The menu applies the knee of the same run without clicking it in a chart.
    panel.useChoiceRequested.emit("knee")
    assert s.model_spec.defaults == pytest.approx(run.solution_values(run.knee_index()))

    # Library defaults again: the values stay, reset goes back to the library's.
    panel.restore_defaults.click()
    assert not s.model_spec.defaults and s.model_spec.defaults_source is None
    assert s.values == pytest.approx(run.solution_values(run.knee_index()))
    s.reset_parameters()
    assert s.values == pytest.approx(CATALOG.defaults(s.model_spec))


def test_defaults_are_saved_and_survive_a_structure_edit(loaded, tmp_path) -> None:
    window = loaded
    s = window.ctx.session
    s.use_solution_as_defaults(SolutionRef("a", 5))
    want = s.run("a").solution_values(5)

    again = ModelSpec.from_dict(s.working_spec().to_dict())
    assert again.defaults == pytest.approx(want) and again.defaults_source["text"] == "A, solution #6"
    assert "defaults" not in spec_for("gamma-uh").to_dict()  # nothing written when there are none

    path = tmp_path / "p.shproj"
    s.save_project(str(path))
    window.open_project(str(path), confirm=False)
    assert s.model_spec.defaults == pytest.approx(want) and s.values == pytest.approx(want)

    # A structure edit keeps the defaults of the parameters that remain (here: all of them, renamed).
    model = next(p for p in window.pages if p.title == "Model")
    model._structure_edited(s.model_spec.root, {"alpha": "alpha2"})
    assert "alpha2" not in s.model_spec.defaults  # not a parameter of this structure: dropped by prune
    assert s.model_spec.defaults == pytest.approx({k: v for k, v in want.items() if k != "alpha"})


def test_no_selection_or_no_parameter_sets_is_refused(loaded) -> None:
    s = loaded.ctx.session
    with pytest.raises(ValueError, match="Select a solution"):
        s.use_solution_as_defaults()
    run = s.run("a")
    run.add_report(1, 16, run.pareto_F)  # a report without parameter sets
    with pytest.raises(ValueError, match="no stored parameter sets"):
        s.use_solution_as_defaults(SolutionRef("a", 0, 0))


def test_working_model_is_drawn_on_the_views_and_follows_the_sliders(loaded, qtbot) -> None:
    window = loaded
    s = window.ctx.session
    explore = window.explore
    calibrate = next(p for p in window.pages if p.title == "Calibrate")
    s.set_model(s.run("a").model)  # scored with the run's objectives, on its parameters
    window.show_explore("a")
    name = f"Working model: {s.model_spec.display_label}"
    qtbot.waitUntil(lambda: "working-model" in explore.ts._curves, timeout=20000)
    assert name in explore.ts.legend_toggle.names()
    assert explore.pareto._marker_label == name and explore.parallel._extra_label == name

    # A slider move redraws the page in view at once ...
    y0 = explore.ts._curves["working-model"].getData()[1].copy()
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_values({"A": s.values["A"] * 0.5})
    y1 = explore.ts._curves["working-model"].getData()[1]
    assert not np.allclose(np.nan_to_num(y0), np.nan_to_num(y1))
    assert explore.pareto._marker == pytest.approx(window.ctx.controller.last.calibration.objectives)
    # ... hiding it in the legend survives the redraw ...
    explore.ts.legend_toggle.set_visible(name, False)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_values({"A": s.values["A"] * 1.5})
    assert not explore.ts._curves["working-model"].isVisible()
    # ... and a page that was hidden catches up when it is shown.
    assert calibrate._working_stale
    window.nav.setCurrentRow(window.pages.index(calibrate))
    qtbot.waitUntil(lambda: not calibrate._working_stale)
    calibrate._monitor_id = "a"
    calibrate._draw_monitor()
    assert calibrate.front._marker == pytest.approx(window.ctx.controller.last.calibration.objectives)
    assert calibrate.front._marker_label == name

    # Renaming the model renames its entries.
    window.show_explore("a")
    s.set_model_label("Renamed")
    assert "Working model: Renamed" in explore.ts.legend_toggle.names()
