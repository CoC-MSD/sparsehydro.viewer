from __future__ import annotations

import time

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec
from sparsehydro_viewer.core.data import Period
from sparsehydro_viewer.core.diagnostics import (
    ComplexityPoint,
    complexity_front,
    fit_statistics,
    nondominated,
)
from sparsehydro_viewer.core.evaluation import Evaluator
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.uh import kernel_curves

OBJS = [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias"), ObjectiveSpec("rmse")]


@pytest.mark.parametrize("kind", ["abstraction-uh", "rdii", "nash-uh"])
def test_evaluator_matches_calibration_problem(kind: str, short_frame) -> None:
    ev = Evaluator(spec_for(kind), short_frame, OBJS)
    x = np.array([ev.model.read_flat_parameter(n) for n in ev.calibrated_names])
    x2 = x * 1.1
    lo, hi = ev.problem.bounds
    x2 = np.clip(x2, lo, hi)
    res = ev.evaluate_vector(ev.calibrated_names, x2)
    np.testing.assert_allclose(res.F, ev.problem.evaluate(x2, penalty_weight=0.0))
    assert res.predicted.shape == ev.observed.shape
    # display form: NSE is maximised, so its display value is -F
    assert res.objectives["nash_sutcliffe"] == pytest.approx(-res.F[0])
    assert res.objectives["pbias"] == pytest.approx(res.F[1])


def test_undefined_objectives_count_as_worst(short_frame) -> None:
    """A constant (all-zero) prediction makes KGE undefined: the optimiser must see the worst value.

    (Lin's CCC stays defined, at 0, because the observed series still varies.)
    """
    ev = Evaluator(spec_for("gamma-uh"), short_frame, [ObjectiveSpec("kge"), ObjectiveSpec("ccc"),
                                                       ObjectiveSpec("rmse")])
    res = ev.evaluate({"A": 0.0})
    assert not res.predicted.any()
    assert res.F[0] == 1e12 and res.F[1] == pytest.approx(0.0) and 0 < res.F[2] < 1e12
    assert np.isnan(res.objectives["kge"]) and np.isfinite(res.objectives["rmse"])
    copy = ev.problem.make_copy()
    assert type(copy) is type(ev.problem)


def test_fixed_parameter_changes_simulation(short_frame) -> None:
    ev = Evaluator(spec_for("nash-uh"), short_frame, OBJS)
    a = ev.evaluate({"A": 100.0}).predicted
    b = ev.evaluate({"A": 200.0}).predicted
    np.testing.assert_allclose(b, 2 * a, rtol=1e-9, atol=1e-12)


def test_period_slicing(sample_frame) -> None:
    p = Period("2022-05-08", "2022-05-15")
    ev = Evaluator(spec_for("gamma-uh"), sample_frame, OBJS, p)
    assert ev.datetime[0] >= np.datetime64("2022-05-08") and ev.datetime[-1] <= np.datetime64("2022-05-15")


def test_simulate_many_restores_state(short_frame) -> None:
    ev = Evaluator(spec_for("gamma-uh"), short_frame, OBJS)
    before = ev.current_values()
    lo, hi = ev.problem.bounds
    X = np.vstack([lo + 0.25 * (hi - lo), lo + 0.75 * (hi - lo)])
    sims = ev.simulate_many(ev.calibrated_names, X)
    assert sims.shape == (2, len(ev.datetime))
    assert ev.current_values() == before


def test_live_evaluation_is_fast(sample_frame) -> None:
    ev = Evaluator(spec_for("abstraction-uh"), sample_frame, OBJS)
    ev.evaluate()
    t0 = time.perf_counter()
    for i in range(20):
        ev.evaluate({"uh_w": 0.3 + 0.01 * i})
    per_call_ms = (time.perf_counter() - t0) / 20 * 1000
    assert per_call_ms < 50, per_call_ms


@pytest.mark.parametrize("kind,n_curves", [("gamma-uh", 1), ("abstraction-uh", 1), ("rdii", 4)])
def test_kernel_curves_unit_area(kind: str, n_curves: int) -> None:
    built = CATALOG.build(spec_for(kind))
    curves = kernel_curves(built, 1 / 12)
    assert len(curves) == n_curves
    for c in curves:
        assert c.ordinates.sum() * c.dt == pytest.approx(1.0, rel=1e-6)
        assert c.time_to_peak > 0


def test_kernel_curves_follow_parent_parameters() -> None:
    built = CATALOG.build(spec_for("abstraction-uh", {"uh": "nash-uh"}))
    fast = kernel_curves(built, 1 / 12)[0].centroid
    built.model.apply_flat_parameter("uh_K", 4 * built.model.read_flat_parameter("uh_K"))
    assert kernel_curves(built, 1 / 12)[0].centroid > 2 * fast


def test_kernel_curves_in_nested_composition() -> None:
    from test_catalog import example_tree


    built = CATALOG.build(ModelSpec(example_tree()))
    curves = kernel_curves(built, 1 / 12)
    assert [c.label.split(":")[0] for c in curves][-1] == "wet"  # combined curve of the RDII term
    assert len(curves) == 4
    # the RTK triangle follows its prefixed parent parameter wet_uh3_T
    before = curves[2].time_to_peak
    built.model.apply_flat_parameter("wet_uh3_T", 6.0)
    assert kernel_curves(built, 1 / 12)[2].time_to_peak > before


def test_example_composition_evaluates(sample_frame) -> None:
    from test_catalog import example_tree


    ev = Evaluator(ModelSpec(example_tree()), sample_frame, OBJS)
    res = ev.evaluate({"san_baseline": 0.2, "wet_area_acres": 5.0})
    assert np.isfinite(res.predicted).all() and res.predicted.min() >= 0.19
    assert len(ev.calibrated_names) == 64 and "san_pf_hour[0]" in ev.calibrated_names


def test_nondominated_and_complexity_front() -> None:
    F = np.array([[1, 5], [2, 3], [3, 4], [4, 1], [np.nan, 0]])
    assert nondominated(F).tolist() == [True, True, False, True, False]
    pts = [ComplexityPoint("a", "a", 3, -0.6), ComplexityPoint("b", "b", 7, -0.8),
           ComplexityPoint("c", "c", 14, -0.79), ComplexityPoint("d", "d", 3, -0.5)]
    assert [p.key for p in complexity_front(pts)] == ["a", "b"]


def test_fit_statistics_penalise_parameters() -> None:
    o = np.sin(np.linspace(0, 10, 500))
    p = o + 0.05
    s3, s10 = fit_statistics(o, p, 3), fit_statistics(o, p, 10)
    assert s3["NSE"] == s10["NSE"] and s10["AIC"] - s3["AIC"] == pytest.approx(14.0)


def test_slow_unit_hydrograph_bounds_are_reported_by_process_and_slider(short_frame) -> None:
    import warnings

    from sparsehydro_viewer.core.catalog import ParameterState
    from sparsehydro_viewer.core.processes import ProcessDesign, to_tree

    spec = ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh"])))
    with warnings.catch_warnings(record=True) as caught:  # what would reach the console, with the app's filters
        ev = Evaluator(spec, short_frame, OBJS[:1], Period())
    assert not [w for w in caught if "deliver half its volume" in str(w.message)]
    slow = {r.label: r for r in ev.slow_responses}
    assert slow, "the default bounds allow responses slower than a one-week record"
    r = next(iter(slow.values()))
    assert r.record_hours == pytest.approx(7 * 24, rel=0.01) and r.median_hours > r.record_hours / 2
    assert set(r.parameters) <= set(ev.parameter_names) and "UH" in r.label and "h to deliver" in r.message()
    # tighter upper bounds on the flagged sliders clear the note
    tight = ModelSpec(spec.root, {p: ParameterState(upper=2.0 if p.endswith(("_K", "_alpha")) else 6.0)
                                  for r in ev.slow_responses for p in r.parameters})
    assert Evaluator(tight, short_frame, OBJS[:1], Period()).slow_responses == []
