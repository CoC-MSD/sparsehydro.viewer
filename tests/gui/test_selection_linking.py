"""One selection across charts and pages: Explore and Compare write the session's selection and draw from it."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QRectF

from helpers import spec_for
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
    F = np.column_stack([-(0.2 + 0.6 * t), 30 * (1 - t)])  # NSE (stored negated), PBIAS: a trade-off
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
    s.add_run(_run("b", "B", 10, 2))
    return window


def _lines(page) -> list[str]:
    return sorted(k for k in page.ts._curves if k.startswith("sol:"))


def test_explore_click_ctrl_click_and_rubber_band(loaded, qtbot) -> None:
    window = loaded
    s = window.ctx.session
    explore = window.explore
    window.show_explore("a")
    run = s.run("a")
    knee = run.knee_index()
    qtbot.waitUntil(lambda: _lines(explore) == [f"sol:None:{knee}"], timeout=20000)
    # one solution selected: the band is the range of the whole Pareto set, with a legend entry
    assert "band" in explore.ts._bands and "band" in explore.ts._band_swatches
    assert "Pareto range (16 solutions)" in [lab.text for _s, lab in explore.ts.legend.items]

    # a click in the scatter selects that solution everywhere
    explore.pareto.pointPicked.emit("a", 3, False)
    assert s.selection.refs == (SolutionRef("a", 3),) and s.selected_solutions == [3]
    assert explore.parallel._highlight == [3] and explore.pareto.selection() == {"a": [3]}
    qtbot.waitUntil(lambda: _lines(explore) == ["sol:None:3"], timeout=20000)

    # Ctrl+click on a line of the parallel coordinates adds a second solution: two lines and their range
    explore.parallel.rowPicked.emit(5, True)
    assert s.selection.indices("a") == [5, 3]  # the last clicked is primary
    qtbot.waitUntil(lambda: _lines(explore) == ["sol:None:3", "sol:None:5"], timeout=20000)
    assert "Range of the 2 selected solutions" in [lab.text for _s, lab in explore.ts.legend.items]
    assert explore.selected.rowCount() == 2 and explore.detail_tabs.tabText(1) == "Selected (2)"
    explore.selected.selectRow(1)  # choosing a row of the table makes it primary
    assert s.selection.primary == SolutionRef("a", 3)
    explore.parallel.rowPicked.emit(5, True)  # Ctrl+click again removes it
    assert s.selection.indices("a") == [3]

    # Shift-drag rectangle over the whole scatter selects every solution: band and at most 12 lines
    explore.pareto.rangeSelected.emit(explore.pareto.points_in(QRectF(-1e9, -1e9, 2e9, 2e9)), False)
    assert len(s.selection.of_run("a")) == 16
    qtbot.waitUntil(lambda: len(_lines(explore)) == 12, timeout=20000)
    assert "16 solutions selected" in explore.selection_info.text()
    explore.pareto.selectionCleared.emit()  # Esc: nothing selected, the page shows the knee by default
    assert s.selection.of_run("a") == []
    qtbot.waitUntil(lambda: _lines(explore) == [f"sol:None:{knee}"], timeout=20000)
    assert "band" in explore.ts._bands  # the Pareto range stays


def test_brush_selects_and_filters_across_charts(loaded, qtbot) -> None:
    window = loaded
    s = window.ctx.session
    explore = window.explore
    window.show_explore("a")
    run = s.run("a")
    # brush the upper half of the first axis (NSE, better is up)
    explore.parallel._set_brush(0, 0.5, 1.0, final=True)
    rows = explore.parallel.selected_rows()
    assert 0 < len(rows) < run.n_solutions
    assert s.filter_rows["a"] == rows and s.selection.indices("a") and set(s.selection.indices("a")) == set(rows)
    assert [layer.key for layer in explore.pareto._layers] == ["a", "a:out"]  # scatter shows the filter
    assert sum(len(v) for v in explore.pareto.selection().values()) == len(rows)
    primary = s.selection.primary
    explore.parallel._clear_brush(0)  # clearing the brush leaves the primary solution alone
    assert "a" not in s.filter_rows and s.selection.of_run("a") == [primary]


def test_selection_is_shared_between_explore_and_compare(loaded, qtbot) -> None:
    window = loaded
    s = window.ctx.session
    compare = next(p for p in window.pages if p.title == "Compare")
    window.nav.setCurrentRow(window.pages.index(compare))
    qtbot.waitUntil(lambda: {"run:a", "run:b"} <= set(compare.ts._curves), timeout=30000)
    assert {"band:a", "band:b"} <= set(compare.ts._bands)  # each run's Pareto range

    # a click in Compare's scatter selects the solution and makes it that run's chosen one
    compare.pareto.pointPicked.emit("b", 4, False)
    assert s.selection.indices("b") == [4] and compare.choice(s.run("b")) == "index:4"
    row = compare._row_index.index(("b", 4))
    assert compare.parallel._highlight == [row] and compare.pareto.selection() == {"b": [4]}
    # Ctrl+click in the parallel coordinates adds a solution of the other run; it is drawn as an extra line
    compare.parallel.rowPicked.emit(compare._row_index.index(("a", 2)), True)
    assert s.selection.indices("a") == [2] and s.selection.indices("b") == [4]
    chosen_a = compare._solution_index(s.run("a"))
    if chosen_a != 2:
        qtbot.waitUntil(lambda: "sel:a:2" in compare.ts._curves, timeout=30000)

    # the same selection is what Explore shows for that run
    window.show_explore("a")
    assert window.explore.parallel._highlight == [2]
    qtbot.waitUntil(lambda: _lines(window.explore) == ["sol:None:2"], timeout=20000)
    # ... and a selection made on Explore appears on Compare
    window.explore.pareto.pointPicked.emit("a", 9, True)
    assert set(compare.pareto.selection()["a"]) == {2, 9}

    # a brush on Compare filters each run and selects what passes
    compare.parallel._set_brush(1, 0.6, 1.0, final=True)  # axis 1: the first objective
    assert set(s.filter_rows) == {"a", "b"}
    assert set(s.selection.indices("a")) == set(s.filter_rows["a"])
    s.remove_runs(["b"])  # removing a run prunes its selection and filter
    assert "b" not in s.filter_rows and s.selection.indices("b") == []
