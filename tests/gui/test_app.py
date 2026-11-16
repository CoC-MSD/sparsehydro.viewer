"""End-to-end tests of the main window (offscreen)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.data import DatasetSpec, Period
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.project import Project
from sparsehydro_viewer.core.solvers import SolverSpec


@pytest.fixture
def window(qtbot):
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    win = MainWindow()  # not registered with qtbot: it would close() before this teardown and prompt to save
    win.show()
    yield win
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    win.deleteLater()


def _load(win, qtbot, frame, sample_csv, period: Period | None = None) -> None:
    spec = DatasetSpec("sample", path=str(sample_csv), calibration=period or Period("2022-05-01", "2022-05-14"),
                       validation=Period("2022-05-14 00:05", "2022-05-21 23:55"))
    with qtbot.waitSignal(win.ctx.controller.result, timeout=15000):
        win.ctx.session.add_dataset(spec, frame)


def test_components_and_states_on_the_model_page(window, qtbot, sample_frame, sample_csv) -> None:
    from sparsehydro_viewer.core.catalog import ModelSpec
    from sparsehydro_viewer.core.processes import ProcessDesign, to_tree

    s = window.ctx.session
    live = window.ctx.controller.live
    _load(window, qtbot, sample_frame, sample_csv)
    window.nav.setCurrentRow(1)
    page = window.pages[1]
    assert not live.trace_enabled  # nothing on screen needs it: sliders stay as fast as before
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_model(ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh"], sanitary=True))))

    # Components: the simulation as the sum of its individual hydrographs
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000) as sig:
        page.components_action.trigger()
    assert live.trace_enabled and sig.args[0].trace is not None
    labels = page.plot.stack_labels("components")
    assert len(labels) == 3 and any("UH 1" in x for x in labels) and any("san" in x for x in labels)

    # Internal states tab: the losses' state is listed and plotted by default
    page.lower_tabs.setCurrentWidget(page.states)
    assert "wet.ia.ia_available" in page.states.fields
    assert page.states.plotted() == ["wet.ia.ia_available"]
    with qtbot.waitSignal(window.ctx.controller.result, timeout=5000):
        window.params.rows["wet_ia_max"].slider.setValue(800)
    assert page.states.plotted() == ["wet.ia.ia_available"]

    # Turning both off stops computing the trace and removes the layer
    page.components_action.trigger()
    page.lower_tabs.setCurrentWidget(page.uh)
    assert not live.trace_enabled and page.plot.stack_labels("components") == []
    window.nav.setCurrentRow(0)
    page.lower_tabs.setCurrentWidget(page.states)
    assert not live.trace_enabled  # the page is hidden


def test_sliders_drive_live_evaluation(window, qtbot, sample_frame, sample_csv) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_model(spec_for("abstraction-uh"))
    first = window.ctx.controller.last
    assert first is not None and first.validation is not None
    assert set(first.calibration.objectives) == {"nash_sutcliffe", "pbias"}
    # A slider move: the panel batches it into one session update -> one evaluation.
    with qtbot.waitSignal(window.ctx.controller.result, timeout=5000) as sig:
        window.params.rows["uh_w"].slider.setValue(900)
    res = sig.args[0]
    assert res.calibration.values["uh_w"] == pytest.approx(0.9, abs=1e-3)
    assert not np.allclose(res.calibration.predicted, first.calibration.predicted)
    assert s.values["uh_w"] == pytest.approx(0.9, abs=1e-3)
    # Model page picked up the series and the UH preview.
    page = window.pages[1]
    assert page.metrics.rowCount() == 2
    assert page.uh._current


def test_model_switch_rebuilds_panel(window, qtbot, sample_frame, sample_csv) -> None:
    _load(window, qtbot, sample_frame, sample_csv)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000) as sig:
        window.ctx.session.set_model(spec_for("rdii", {"n_triangles": 2}))
    assert set(window.params.rows) == set(window.ctx.session.values)
    assert len(sig.args[0].kernels) == 3  # two triangles + combined
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        window.params.rows["uh1_T"].check.setChecked(False)
    assert window.ctx.session.model_spec.parameters["uh1_T"].calibrate is False


def test_composer_edits_cascade_and_keep_values(window, qtbot, sample_frame, sample_csv) -> None:
    """MVC: a structure edit in the composer rebuilds the session model, the dock and the evaluation;
    values the user set survive renames (wrap into a sum, reorder unit hydrographs)."""
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_model(spec_for("rdii", {"n_triangles": 2}))
    s.set_values({"uh2_T": 33.0, "area_acres": 12.0})
    composer = window.pages[1].composer

    # Add a sanitary term alongside: everything moves under the 'wet_' prefix.
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000) as sig:
        composer._wrap("sanitary")
    assert s.model_spec.root.type == "sum"
    assert s.values["wet_uh2_T"] == pytest.approx(33.0) and s.values["wet_area_acres"] == pytest.approx(12.0)
    assert "san_baseline" in window.params.rows and "san (Sanitary pattern)" in window.params.sections
    assert np.isfinite(sig.args[0].calibration.predicted).all()

    # Swap the two unit hydrographs: the 33 h triangle becomes UH 1 and keeps its value.
    composer._select((("terms", 0), ("uhs", 1)))
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        composer._move(-1)
    assert s.values["wet_uh1_T"] == pytest.approx(33.0)

    # Add a Nash UH to the RDII term: one more section in the dock, R_i renormalised for the new one.
    composer._select((("terms", 0),))
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        composer._add_child("uhs", "nash-uh")
    assert "wet_uh3_n" in window.params.rows
    assert "san (Sanitary pattern)" in window.params.context.text() or "sanitary" in window.params.context.text()


def test_process_builder_grows_a_model(window, qtbot, sample_frame, sample_csv) -> None:
    """Start from IA -> one RTK triangle, add a gamma UH, a sanitary pattern, switch losses; values follow."""
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    builder = window.pages[1].builder
    assert builder.design.routing == ["rtk-triangle"] and builder.design.losses == "initial-abstraction"
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_values({"uh1_T": 4.0, "area_acres": 30.0})

    builder._add("gamma-uh")
    assert "uh2_alpha" in window.params.rows and s.values["uh1_T"] == pytest.approx(4.0)
    # two hydrographs + their combined curve once the rebuilt model has been evaluated
    qtbot.waitUntil(lambda: len(window.ctx.controller.last.kernels) == 3, timeout=15000)

    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        builder.sanitary.setChecked(True)
    assert s.values["wet_uh1_T"] == pytest.approx(4.0) and s.values["wet_area_acres"] == pytest.approx(30.0)
    assert "san_baseline" in window.params.rows

    # RTK triangles route rainfall excess: "None" losses is refused with a message and nothing changes
    before = s.model_spec.structure_key
    builder.losses.setCurrentIndex(builder.losses.findData(None))
    builder._losses_changed()
    assert "losses" in builder.message.text() and s.model_spec.structure_key == before

    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        builder._remove(0)
    assert builder.design.routing == ["gamma-uh"] and "wet_uh2_tt" not in window.params.rows
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        builder.losses.setCurrentIndex(builder.losses.findData(None))
        builder._losses_changed()
    assert builder.design.losses is None and "wet_A" in window.params.rows


def test_periods_from_chart_cascade(window, qtbot, sample_frame, sample_csv) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    page = window.pages[0]
    a, b = (pd.Timestamp("2022-05-03 00:02"), pd.Timestamp("2022-05-09 12:00"))
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000) as sig:
        page.periods.periodEdited.emit("calibration", a.timestamp(), b.timestamp())
    # snapped to the 5-minute record and stored in the session...
    assert s.dataset.calibration.start == "2022-05-03 00:05:00"
    # ...mirrored in the date editors and the draggable region, and re-evaluated on the new period
    assert page.cal.period().start == "2022-05-03 00:05:00"
    assert page.plot.period("calibration") is not None
    assert str(sig.args[0].datetime[0])[:16] == "2022-05-03T00:05"
    with qtbot.waitSignal(s.periodsChanged):
        page.periods.periodCleared.emit("validation")
    assert s.dataset.validation.is_open and page.plot.period("validation") is None


def test_dock_follows_pages(window) -> None:
    window.nav.setCurrentRow(0)  # Data
    assert not window.param_dock.isVisible()
    window.nav.setCurrentRow(1)  # Model
    assert window.param_dock.isVisible()
    window.nav.setCurrentRow(2)  # Events
    assert not window.param_dock.isVisible()


@pytest.mark.slow
def test_calibrate_explore_compare_save_reload(window, qtbot, sample_frame, sample_csv, tmp_path) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv, Period("2022-05-01", "2022-05-08"))
    s.set_objectives([ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")])
    s.set_solver(SolverSpec("nsga2", {"pop_size": 8, "n_gen": 3, "seed": 1}))
    cal_page = window.pages[3]
    cal_page._load_from_session()
    labels = []
    for kind in ("gamma-uh", "abstraction-uh"):
        with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
            s.set_model(spec_for(kind))
        with qtbot.waitSignal(window.ctx.calibration.finished, timeout=120000):
            cal_page._run()
        labels.append(s.project.runs[-1].label)
    runs = s.project.runs
    assert [r.status for r in runs] == ["finished", "finished"], [r.message for r in runs]
    assert runs[0].n_params_calibrated == 3 and runs[1].n_params_calibrated == 14
    assert [h[0] for h in runs[0].history] == [1, 2, 3]

    # Explore: knee selected, simulation job fills hydrograph and UH preview.
    explore = window.explore
    window.show_explore(runs[0].id)
    explore._select_knee()
    qtbot.waitUntil(lambda: bool(explore.uh._current) and explore.params.rowCount() > 0, timeout=20000)
    assert explore._run.id == runs[0].id
    assert s.selected_run == runs[0].id and s.selected_solutions == [runs[0].knee_index()]
    assert explore.params.rowCount() == 3

    # Load the solution into the sliders: the working model becomes gamma-uh with those values.
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        explore._load()
    expected = runs[0].solution_values(runs[0].knee_index())
    assert s.model_spec.root.type == "gamma-uh"
    for k, v in expected.items():
        assert s.values[k] == pytest.approx(v)

    # Compare: both runs ticked; scoring fills information criteria.
    compare = window.pages[5]
    compare.refresh()
    assert compare.table.rowCount() == 2
    compare._score()
    window.ctx.jobs.wait(20000)
    qtbot.waitUntil(lambda: len(compare._scores) == 2, timeout=20000)
    assert all(np.isfinite(sc.cal["AIC"]) for sc in compare._scores.values())
    assert compare.parallel.s.data.shape[0] == runs[0].n_solutions + runs[1].n_solutions

    # Save, reload, identical results.
    s.save_project(str(tmp_path / "proj.shproj"))
    back = Project.load(tmp_path / "proj.shproj")
    assert [r.label for r in back.runs] == labels
    np.testing.assert_array_equal(back.runs[1].pareto_F, runs[1].pareto_F)


@pytest.mark.slow
def test_cancel_running_calibration(window, qtbot, sample_frame, sample_csv) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    s.set_solver(SolverSpec("nsga2", {"pop_size": 20, "n_gen": 100000}))
    window.pages[3]._load_from_session()
    window.pages[3]._run()
    rid = s.project.runs[-1].id
    qtbot.waitUntil(lambda: len(s.run(rid).history) > 0, timeout=60000)
    with qtbot.waitSignal(window.ctx.calibration.finished, timeout=15000):
        window.ctx.calibration.cancel(rid)
    assert s.run(rid).status == "cancelled"


@pytest.mark.slow
def test_events_page(window, qtbot, sample_frame, sample_csv) -> None:
    _load(window, qtbot, sample_frame, sample_csv)
    page = window.pages[2]
    page.options.set_values({"uh": "gamma-uh"})
    page.run_analysis()
    qtbot.waitUntil(lambda: page.analysis is not None, timeout=60000)
    assert page.events.count() == len(page.analysis.global_events) > 0
    for tab in range(4):
        page.tabs.setCurrentIndex(tab)
    page._step(1)
    gid = page._current_id()
    page._exclude()
    qtbot.waitUntil(lambda: page.analysis is not None and gid not in
                    [int(g.global_id) for g in page.analysis.global_events], timeout=60000)
    assert window.ctx.session.ui("event_overrides")["sample"]["deleted_global_ids"] == [gid]


def test_views_and_widgets_do_not_import_sparsehydro() -> None:
    """Layering rule: only core/ and services/ talk to the library."""
    from pathlib import Path

    import sparsehydro_viewer

    root = Path(sparsehydro_viewer.__file__).parent
    offenders = []
    for sub in ("views", "widgets"):
        for f in (root / sub).glob("*.py"):
            text = f.read_text(encoding="utf-8")
            if "import sparsehydro\n" in text or "from sparsehydro." in text or "from sparsehydro import" in text:
                offenders.append(f.name)
    assert offenders == []
