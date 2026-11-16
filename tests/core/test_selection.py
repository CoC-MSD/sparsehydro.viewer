"""The cross-chart solution selection and the simulation of selected solutions."""

from __future__ import annotations

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.data import Period
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.runs import RunRecord
from sparsehydro_viewer.core.selection import SolutionRef, SolutionSelection
from sparsehydro_viewer.core.simulate import MAX_LINES, SimulationCache, simulate_solutions

A0, A1, A2, B0 = SolutionRef("a", 0), SolutionRef("a", 1), SolutionRef("a", 2), SolutionRef("b", 0)


def test_selection_is_ordered_unique_with_a_primary() -> None:
    sel = SolutionSelection((A0, A1, A0, B0))
    assert sel.refs == (A0, A1, B0) and sel.primary == B0 and len(sel) == 3 and A1 in sel
    assert SolutionSelection((A0, A1), A0).of_run("a") == [A0, A1]
    assert SolutionSelection((A0, A1), A1).indices("a") == [1, 0]  # primary first
    assert not SolutionSelection() and SolutionSelection().primary is None
    assert SolutionSelection((A0,), B0).primary == A0  # a primary outside the selection is replaced


def test_toggle_replace_and_per_run_edits() -> None:
    sel = SolutionSelection((A0,)).toggled(A1)
    assert sel.refs == (A0, A1) and sel.primary == A1
    sel = sel.toggled(A1)  # Ctrl+click on a selected solution removes it
    assert sel.refs == (A0,) and sel.primary == A0
    both = SolutionSelection((A0, B0), B0)
    replaced = both.with_run("a", [A1, A2])  # other runs keep their selection
    assert replaced.refs == (B0, A1, A2) and replaced.primary == A1
    assert both.with_run("a", [A1], add=True).refs == (A0, B0, A1)
    assert both.with_run("a", []).refs == (B0,) and both.with_run("a", []).primary == B0
    assert both.pruned(["b"]).refs == (B0,) and both.run_ids() == ["a", "b"]
    assert SolutionRef("a", 3, generation=4).label() == "#3 (report 5)" and not SolutionRef("a", 3, 4).is_final


@pytest.fixture
def run(short_frame) -> RunRecord:
    rng = np.random.default_rng(0)
    spec = spec_for("gamma-uh")
    names = ["alpha", "theta", "A"]
    X = np.column_stack([rng.uniform(1.5, 4, 30), rng.uniform(0.5, 3, 30), rng.uniform(20, 120, 30)])
    return RunRecord("r", "run", "sample", spec, [ObjectiveSpec("nash_sutcliffe")], None, status="finished",
                     param_names=names, objective_names=["nash_sutcliffe"], minimize_flags=[False], pareto_X=X,
                     pareto_F=-rng.random((30, 1)))


def test_simulate_solutions_lines_band_and_cache(run, short_frame) -> None:
    refs = [SolutionRef("r", i) for i in (3, 7, 11)]
    cache = SimulationCache()
    out = simulate_solutions(run, short_frame, refs, Period(), primary=refs[1], band_rows=[3, 7, 11],
                             band_label="selection", cache=cache)
    assert list(out.lines) == [refs[1], refs[0], refs[2]] and out.primary == refs[1]  # primary first
    assert out.n_selected == 3 and len(out.t) == len(short_frame) == len(out.predicted)
    stack = np.vstack(list(out.lines.values()))
    np.testing.assert_allclose(out.band[0], stack.min(axis=0))  # the band is the envelope of the same solutions
    np.testing.assert_allclose(out.band[1], stack.max(axis=0))
    assert out.curves and out.band_label == "selection"
    # each line equals simulating that solution alone
    alone = simulate_solutions(run, short_frame, [refs[2]], Period())
    np.testing.assert_allclose(alone.predicted, out.lines[refs[2]])
    # a repeat is served from the cache
    hits = cache.hits
    again = simulate_solutions(run, short_frame, refs, Period(), primary=refs[1], band_rows=[3, 7, 11], cache=cache)
    assert cache.hits >= hits + 4 and np.array_equal(again.lines[refs[0]], out.lines[refs[0]])
    cache.drop_run("r")
    assert len(cache) == 0


def test_more_than_the_line_limit_keeps_the_primary_and_the_band(run, short_frame) -> None:
    refs = [SolutionRef("r", i) for i in range(20)]
    out = simulate_solutions(run, short_frame, refs, Period(), primary=refs[19], band_rows=list(range(20)))
    assert len(out.lines) == MAX_LINES and next(iter(out.lines)) == refs[19] and out.n_selected == 20
    assert out.band is not None and np.all(out.band[1] >= out.band[0])
    # with nothing selected there are no lines, only the band (the Pareto range)
    none = simulate_solutions(run, short_frame, [], Period(), band_rows=list(range(30)))
    assert not none.lines and none.primary is None and none.predicted is None and none.band is not None
