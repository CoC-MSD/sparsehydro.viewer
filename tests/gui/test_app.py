"""End-to-end tests of the main window (offscreen)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import Qt

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
    frame = sample_frame.assign(temperature_c=np.linspace(5.0, 20.0, len(sample_frame)))  # a model input
    _load(window, qtbot, frame, sample_csv)
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
    page.components_action.trigger()
    assert not live.trace_enabled and page.plot.stack_labels("components") == []

    # The picker lists the dataset's inputs and the model's states, before any trace runs; nothing is ticked
    assert {"inputs.temperature_c", "wet.ia.ia_available"} <= set(page.states.fields)
    assert page.states.selected() == [] and page.plot.panel_keys() == []
    # An input needs no model trace; it appears in a panel under the flow
    page.states.set_selected(["inputs.temperature_c"])
    assert not live.trace_enabled and page.plot.panel_keys() == ["units:°C"]
    # A model state turns the trace on; it gets its own panel (one per unit)
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        page.states.set_selected(["inputs.temperature_c", "wet.ia.ia_available"])
    assert live.trace_enabled and page.plot.panel_keys() == ["units:°C", "units:in"]
    assert page.plot.panel_series("units:in") == ["wet › ia › remaining abstraction"]
    # The panels share the flow's time axis and axis width: zooming the flow zooms them
    flow = page.plot.flow_plot
    panels = [p for p, _ in page.plot._panels.values()]
    assert all(p.getViewBox().linkedView(0) is flow.getViewBox() for p in panels)
    assert {p.getAxis("left").width() for p in panels} == {flow.getAxis("left").width()}
    t0 = page.plot.data_range()[0]
    page.plot.zoom_to(t0 + 86400, t0 + 2 * 86400)
    for p in panels:
        x0, x1 = p.viewRange()[0]
        assert x0 == pytest.approx(flow.viewRange()[0][0]) and x1 == pytest.approx(flow.viewRange()[0][1])
    assert not flow.getAxis("bottom").isVisible() and panels[-1].getAxis("bottom").isVisible()
    with qtbot.waitSignal(window.ctx.controller.result, timeout=5000):
        window.params.rows["wet_ia_max"].slider.setValue(800)
    assert page.plot.panel_keys() == ["units:°C", "units:in"]

    # Unticking removes the panels and stops computing the trace; a hidden page needs nothing
    page.states.set_selected([])
    assert not live.trace_enabled and page.plot.panel_keys() == []
    assert flow.getAxis("bottom").isVisible()
    page.states.set_selected(["wet.ia.ia_available"])
    window.nav.setCurrentRow(0)
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
    window.nav.setCurrentRow(5)
    compare.refresh()

    def row_of(key) -> int:
        return next(r for r in range(compare.table.rowCount())
                    if compare.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == key)

    head = [compare.table.horizontalHeaderItem(c).text() for c in range(compare.table.columnCount())]
    # ... and the working model, scored like a run at its slider values: a row, a star, a line, a hydrograph.
    assert compare.table.rowCount() == 3
    w = row_of("working-model")
    name = f"Working model: {s.model_spec.display_label}"
    assert name in compare.table.item(w, 0).text()
    live = window.ctx.controller.last
    assert float(compare.table.item(w, head.index("cal NSE")).text()) == pytest.approx(live.stats_cal["NSE"], abs=1e-3)
    assert compare.table.item(w, head.index("MSDGC grade")).text() == ""  # graded with Score runs
    assert compare.pareto._marker == pytest.approx(live.calibration.objectives) and compare.pareto._marker_label == name
    assert compare.parallel._extra["__n_params__"] == live.n_calibrated == 3
    assert len(compare._working_star) == 2
    compare._score()
    window.ctx.jobs.wait(20000)
    qtbot.waitUntil(lambda: len(compare._scores) == 2, timeout=20000)
    assert all(np.isfinite(sc.cal["AIC"]) for sc in compare._scores.values())
    assert compare.parallel.s.data.shape[0] == runs[0].n_solutions + runs[1].n_solutions
    # ... and each run's MSDGC grade, as a column and as the marker shape on the complexity plot
    grades = [sc.grade for sc in compare._scores.values()]
    assert all(g in ("pass", "conditional", "fail") for g in grades)
    col = [compare.table.horizontalHeaderItem(c).text() for c in range(compare.table.columnCount())].index("MSDGC grade")
    assert all(compare.table.item(row_of(r.id), col).text() for r in runs)
    assert compare._working_grade.grade in ("pass", "conditional", "fail")
    assert compare.table.item(row_of("working-model"), col).text()
    compare.grade_filter.setCurrentIndex(1)  # pass only
    shown = [r for r in compare._selected_runs() if compare._passes_filter(r)]
    assert len(shown) == sum(g == "pass" for g in grades)
    compare.grade_filter.setCurrentIndex(0)

    # Chosen solutions: drawn without scoring, over the whole record, one per ticked run, each with its own choice.
    qtbot.waitUntil(lambda: len([k for k in compare.ts._curves if k.startswith("run:")]) == 2, timeout=30000)
    assert compare.choices.rowCount() == 2 and compare.ts.minimumHeight() >= 260
    assert "working-model" in compare.ts._curves and name in compare.ts.legend_toggle.names()
    # A slider move re-scores the working model on the page in view at once, and its grade is withdrawn.
    before = compare.table.item(row_of("working-model"), head.index("cal NSE")).text()
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_values({"A": s.values["A"] * 0.5})
    assert compare.table.item(row_of("working-model"), head.index("cal NSE")).text() != before
    assert compare._working_grade is None and compare.table.item(row_of("working-model"), col).text() == ""
    assert compare.pareto._marker == pytest.approx(window.ctx.controller.last.calibration.objectives)
    t0, t1 = compare.ts.data_range()
    assert t1 - t0 > 0.95 * (sample_frame["datetime"].iloc[-1] - sample_frame["datetime"].iloc[0]).total_seconds()
    r0 = runs[0]
    box = compare.choices.cellWidget(0, 1)
    best = f"best:{r0.objective_names[0]}"
    box.setCurrentIndex(box.findData(best))
    assert compare.choice(r0) == best and compare._solution_index(r0) == r0.best_index(r0.objective_names[0])
    assert compare.choice(runs[1]) == "knee"  # the other run keeps its own choice
    last = r0.n_solutions - 1
    compare._row_clicked([i for i, (rid, k) in enumerate(compare._row_index) if rid == r0.id][last])
    assert compare.choice(r0) == f"index:{last}"
    qtbot.waitUntil(lambda: (r0.id, last) in compare._hydrographs, timeout=30000)
    assert "Picked" in compare.choices.cellWidget(0, 1).currentText()

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
    from sparsehydro_viewer.core.events import EventConfig

    page = window.pages[2]
    window.nav.setCurrentRow(2)
    page.set_configs([EventConfig.for_uh("gamma-uh", pooled=True)])
    page._add_working_model()
    page.configs.item(1, 1).setCheckState(Qt.CheckState.Unchecked)  # working model: pooled only
    page.configs.item(1, 2).setCheckState(Qt.CheckState.Checked)
    assert [(c.per_event, c.pooled) for c in page.event_configs] == [(True, True), (False, True)]
    assert len(window.ctx.session.ui("event_configs")) == 2
    page.run_analysis()
    qtbot.waitUntil(lambda: page.analysis is not None, timeout=120000)
    a = page.analysis
    assert [f.error for f in a.fits] == ["", ""]
    n = len(a.global_events)
    assert page.events.count() == n > 0
    # whole record shown, with one overlay per configuration and mode
    d0, d1 = page.fit_plot.data_range()
    qtbot.waitUntil(lambda: page.fit_plot.x_range()[1] - page.fit_plot.x_range()[0] > 0.9 * (d1 - d0))
    t0, t1 = page.fit_plot.x_range()
    labels = [c.label for c in page.event_configs]
    assert {k for k in page.fit_plot._curves if k.startswith("fit:")} == {
        f"fit:{labels[0]}:per_event", f"fit:{labels[0]}:pooled", f"fit:{labels[1]}:pooled"}
    assert page.compare.rowCount() == n + 1 and page.compare.columnCount() == 4
    for tab in range(4):
        page.tabs.setCurrentIndex(tab)
    page.tabs.setCurrentIndex(0)
    page._step(1)
    gid = page._current_id()
    w0, w1 = a.window(gid)
    z0, z1 = page.fit_plot.x_range()
    assert z1 - z0 < 0.5 * (t1 - t0) and "event #" in page.status_text()
    page._show_all()
    assert page.fit_plot.x_range()[1] - page.fit_plot.x_range()[0] > 0.9 * (t1 - t0)
    page.compare.selectRow(0)
    assert page._current_id() == int(page.compare.item(0, 0).data(Qt.ItemDataRole.UserRole))
    # Unit hydrographs: every curve names its model and fit, in the model's colour; hidden ones stay hidden.
    page.tabs.setCurrentIndex(1)
    names = page.uh_toggle.names()
    assert f"{labels[0]} (per event)" in names and f"{labels[0]} (pooled)" in names
    assert any(n.startswith(f"{labels[1]} (pooled)") for n in names)
    assert not any("(per event)" in n and n.startswith(labels[1]) for n in names)  # fitted pooled only
    assert page.uh_stats.rowCount() == len(names) and page.uh_stats.item(0, 0).text() == labels[0]
    assert not page.configs.item(0, 0).icon().isNull() and not page.compare.horizontalHeaderItem(1).icon().isNull()
    page.uh_toggle.set_visible(f"{labels[0]} (pooled)", False)
    page._step(1)
    assert f"{labels[0]} (pooled)" in page.uh_toggle.hidden and f"{labels[0]} (per event)" in page.uh_toggle.names()
    page.uh_toggle.show_all()
    page.uh_model.setCurrentIndex(page.uh_model.findText(labels[1]))
    assert page.uh_toggle.names() and all(n.startswith(labels[1]) for n in page.uh_toggle.names())
    page.uh_model.setCurrentIndex(0)
    page.tabs.setCurrentIndex(0)
    page.configs.selectRow(0)
    page._send_to_working_model()
    pooled = a.fits[0].parameters("pooled")
    sent = {k: window.ctx.session.values[k] for k in pooled if k in window.ctx.session.values}
    assert sent and sent == pytest.approx({k: pooled[k] for k in sent})
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


def test_export_trace_and_explore_components(window, qtbot, sample_frame, sample_csv, tmp_path) -> None:
    import pandas as pd

    from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec
    from sparsehydro_viewer.core.processes import ProcessDesign, to_tree
    from sparsehydro_viewer.core.runs import RunRecord
    from sparsehydro_viewer.views.explore_page import simulate_selection

    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    spec = ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh"], sanitary=True)))
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.set_model(spec)
    page = window.pages[1]
    path = tmp_path / "trace.csv"
    with qtbot.waitSignal(window.ctx.jobs.jobChanged, timeout=30000,
                          check_params_cb=lambda job_id: window.ctx.jobs.info(job_id).state == "finished"):
        page.export_trace(str(path))
    table = pd.read_csv(path)
    assert len(table) == len(sample_frame)
    assert {"datetime", "rain", "observed", "wet.rdii_component_1 [CFS]", "wet.ia.ia_available [in]"} <= set(table)
    meta = pd.read_csv(tmp_path / "trace.fields.csv")
    assert set(meta["role"]) >= {"component", "state"}

    # Explore: a solution's hydrograph split into its parts (sanitary + two unit hydrographs)
    model = CATALOG.instantiate(spec)
    names = [n for n in model.scalar_parameter_names if model.get_scalar_parameter(n).calibrate]
    x = np.array([[s.values.get(n, model.read_flat_parameter(n)) for n in names]])
    run = RunRecord("r1", "run", "sample", spec, list(s.objectives), None, status="finished", param_names=names,
                    objective_names=["nash_sutcliffe"], minimize_flags=[False], pareto_X=x,
                    pareto_F=np.array([[-0.5]]))
    ds = s.dataset
    sim = simulate_selection(run, sample_frame, ds.calibration, ds.validation, 0, [], components=True)
    assert len(sim.parts) == 3
    np.testing.assert_allclose(np.sum([y for _, y in sim.parts], axis=0), sim.predicted, rtol=1e-8, atol=1e-10)
    assert simulate_selection(run, sample_frame, ds.calibration, ds.validation, 0, []).parts is None


def test_assess_page_grades_the_working_model(window, qtbot, sample_frame, sample_csv) -> None:
    s = window.ctx.session
    _load(window, qtbot, sample_frame, sample_csv)
    site = s.dataset.site_iri
    s.set_attribute(site, "shv:odwf_a", 0.4)
    s.set_attribute(site, "shv:sewer_system", "sanitary")
    page = next(p for p in window.pages if p.title == "Assess")
    window.nav.setCurrentRow(window.pages.index(page))
    assert window.toolbar.run_action.text() == "Assess"
    page.form.set_values({"period": "whole"})
    with qtbot.waitSignal(window.ctx.jobs.jobChanged, timeout=60000,
                          check_params_cb=lambda job_id: window.ctx.jobs.info(job_id).state == "finished"):
        window.toolbar.run_action.trigger()
    qtbot.waitUntil(lambda: page.last is not None, timeout=10000)
    res = page.last.result
    assert res.grade in ("pass", "conditional", "fail")
    from sparsehydro_viewer.views.assess_page import GRADE_STYLE

    text, symbol, _ = GRADE_STYLE[res.grade]
    assert f"{symbol} {text}" in page.grade.text()  # shape and words, not only colour
    assert text in page.grade.accessibleDescription()
    assert page.criteria.rowCount() == 6 and page.summary.rowCount() == 3 and page.qcrit.rowCount() == 4
    assert page.events.rowCount() == len(res.events) >= 3
    assert "rc =" in page.scatter.plots["conveyance"].titleLabel.text
    # a point in a scatter selects its event and zooms the hydrograph to it
    first = int(res.events.loc[res.events["included"], "event_id"].iloc[0])
    page.scatter.eventClicked.emit(first)
    assert page.tabs.currentIndex() == 2 and page.selected_event() == first
    assert window.toolbar.chart.plot is page.plot
    assert "MSDGC" in page.status_text()
