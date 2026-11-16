"""Earlier generations keep their parameter sets: storage, old files, thinning, and a real calibration."""

from __future__ import annotations

import io

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core import runs as runs_mod
from sparsehydro_viewer.core.calibration import CalibrationPayload, run_calibration
from sparsehydro_viewer.core.data import Period
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.runs import RunRecord
from sparsehydro_viewer.core.selection import SolutionRef
from sparsehydro_viewer.core.simulate import simulate_solutions, solution_vector
from sparsehydro_viewer.core.solvers import SOLVERS, SolverSpec


def _run(n_reports: int = 4, with_x: bool = True) -> RunRecord:
    rng = np.random.default_rng(0)
    run = RunRecord("r", "run", "sample", spec_for("gamma-uh"),
                    [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")], None, status="finished",
                    param_names=["alpha", "theta", "A"], objective_names=["nash_sutcliffe", "pbias"],
                    minimize_flags=[False, True], fixed_values={"x": 1.0})
    for g in range(n_reports):
        m = 3 + g % 3
        X = np.column_stack([rng.uniform(1.5, 4, m), rng.uniform(0.5, 3, m), rng.uniform(20, 120, m)])
        run.add_report(g + 1, 10 * (g + 1), rng.random((m, 2)), X if with_x else None)
    run.pareto_X, run.pareto_F = run.history_X(n_reports - 1) if with_x else rng.random((3, 3)), run.history[-1][2]
    return run


def test_reports_keep_parameter_sets_and_round_trip() -> None:
    run = _run()
    assert len(run.history) == len(run.history_params) == 4
    assert run.history_X(1).shape == (len(run.history[1][2]), 3) and run.history_X(9) is None
    vals = run.solution_values(2, generation=1)
    assert vals["x"] == 1.0 and vals["alpha"] == pytest.approx(run.history_X(1)[2, 0])
    np.testing.assert_array_equal(solution_vector(run, SolutionRef("r", 2, 1)), run.history_X(1)[2])

    back = RunRecord.from_meta(run.meta_dict(), run.arrays_blob())
    assert [h[:2] for h in back.history] == [h[:2] for h in run.history]
    for g in range(4):
        np.testing.assert_array_equal(back.history_X(g), run.history_X(g))
        np.testing.assert_array_equal(back.history[g][2], run.history[g][2])


def test_reports_without_parameter_sets_and_files_saved_before_them() -> None:
    run = _run(with_x=False)
    run.add_report(5, 50, np.random.default_rng(1).random((2, 2)), np.ones((2, 3)))  # mixed: only the last has X
    back = RunRecord.from_meta(run.meta_dict(), run.arrays_blob())
    assert [x is None for x in back.history_params] == [True, True, True, True, False]
    with pytest.raises(ValueError, match="no stored parameter sets"):
        back.solution_values(0, generation=0)
    # history appended the old way (a list of tuples) still works
    run.history.append((6, 60, np.zeros((1, 2))))
    assert run.history_X(5) is None
    run.add_report(7, 70, np.zeros((1, 2)), np.zeros((1, 3)))
    assert len(run.history_params) == len(run.history) == 7
    # a file written before parameter sets were kept: no hist_X arrays
    old = io.BytesIO()
    np.savez_compressed(old, pareto_X=run.pareto_X, pareto_F=run.pareto_F, hist_gen=np.array([1, 2]),
                        hist_evals=np.array([10, 20]), hist_sizes=np.array([1, 2]), hist_F=np.zeros((3, 2)))
    loaded = RunRecord.from_meta(run.meta_dict(), old.getvalue())
    assert len(loaded.history) == 2 and loaded.history_params == [None, None]


def test_long_histories_are_thinned_on_save_keeping_first_and_last(monkeypatch) -> None:
    monkeypatch.setattr(runs_mod, "MAX_STORED_REPORTS", 10)
    run = _run(n_reports=57)
    keep = run.stored_reports()
    assert len(keep) == 10 and keep[0] == 0 and keep[-1] == 56
    back = RunRecord.from_meta(run.meta_dict(), run.arrays_blob())
    assert [h[0] for h in back.history] == [k + 1 for k in keep]
    np.testing.assert_array_equal(back.history_X(9), run.history_X(56))
    assert len(run.history) == 57  # the run in memory is not thinned


@pytest.mark.slow
def test_a_calibration_reports_parameter_sets_that_reproduce_their_objectives(short_frame) -> None:
    solver = SOLVERS.default()
    options = ({"n_evaluations": 120, "record_frequency": 1} if solver.name.startswith("platypus")
               else {"pop_size": 12, "n_gen": 4})
    spec = spec_for("gamma-uh")
    objectives = [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")]
    run = RunRecord("r", "run", "sample", spec, objectives, SolverSpec(solver.name, options), status="running")

    def emit(kind: str, d: dict) -> None:
        if kind == "progress":
            run.add_report(d["generation"], d["n_evals"], d["pareto_F"], d["pareto_X"])

    out = run_calibration(CalibrationPayload("r", spec.to_dict(), [o.to_dict() for o in objectives],
                                             SolverSpec(solver.name, options).to_dict(), short_frame, {}), emit)
    for k in ("param_names", "objective_names", "minimize_flags", "pareto_X", "pareto_F", "fixed_values"):
        setattr(run, k, out[k])
    assert len(run.history) >= 2 and all(x is not None for x in run.history_params)
    g = 0
    assert run.history_X(g).shape == (len(run.history[g][2]), len(run.param_names))
    # a solution of the first report can be simulated like one of the final front
    ref = SolutionRef("r", 0, g)
    sim = simulate_solutions(run, short_frame, [ref], Period())
    assert sim.primary == ref and np.all(np.isfinite(sim.predicted)) and sim.curves
