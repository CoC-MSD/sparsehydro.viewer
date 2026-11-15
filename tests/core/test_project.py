from __future__ import annotations

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.calibration import CalibrationPayload, run_calibration
from sparsehydro_viewer.core.catalog import ParameterState
from sparsehydro_viewer.core.data import DatasetSpec, Period, guess_columns, load_dataset, summarize
from sparsehydro_viewer.core.events import EventOverrides
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.project import Project
from sparsehydro_viewer.core.runs import RunRecord, new_id
from sparsehydro_viewer.core.solvers import SolverSpec


def test_load_csv_with_mapping_and_units(tmp_path, sample_frame) -> None:
    src = sample_frame.rename(columns={"datetime": "Date_Time", "rain": "Rain_in", "stormflow": "Flow_MGD"})
    path = tmp_path / "x.csv"
    src.to_csv(path, index=False)
    cols = guess_columns(list(src.columns))
    assert cols["datetime"] == "Date_Time" and cols["rain"] == "Rain_in" and cols["stormflow"] == "Flow_MGD"
    df = load_dataset(DatasetSpec("x", path=str(path), columns=cols, flow_units="MGD"))
    np.testing.assert_allclose(df["stormflow"], sample_frame["stormflow"] * 1.5472286)
    s = summarize(df)
    assert s.dt_minutes == 5.0 and s.irregular_steps == 0


def test_missing_column_is_reported(tmp_path, sample_frame) -> None:
    path = tmp_path / "x.csv"
    sample_frame[["datetime", "rain"]].to_csv(path, index=False)
    with pytest.raises(ValueError, match="stormflow"):
        load_dataset(DatasetSpec("x", path=str(path)))


def _record() -> RunRecord:
    rng = np.random.default_rng(0)
    rec = RunRecord(new_id(), "r", "site", spec_for("gamma-uh", parameters={"A": ParameterState(calibrate=False)}),
                    [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")], SolverSpec("nsga2", {"n_gen": 3}),
                    status="finished", param_names=["tt", "tp"], objective_names=["nash_sutcliffe", "pbias"],
                    minimize_flags=[False, True], fixed_values={"A": 100.0}, n_params_total=3)
    rec.pareto_X = rng.random((6, 2))
    rec.pareto_F = rng.random((6, 2))
    rec.history = [(1, 10, rng.random((4, 2))), (2, 20, rng.random((5, 2)))]
    return rec


def test_project_round_trip(tmp_path, sample_csv) -> None:
    proj = Project("site", datasets=[DatasetSpec("d", path=str(sample_csv), calibration=Period("2022-05-01", None))])
    proj.models.append(spec_for("rdii", {"n_triangles": 2}))
    proj.runs.append(_record())
    proj.ui_state["overrides"] = {"d": EventOverrides(deleted_global_ids=[3]).to_dict()}
    proj.save(tmp_path / "p")
    back = Project.load(tmp_path / "p")
    assert back.to_dict() == proj.to_dict()
    r0, r1 = proj.runs[0], back.runs[0]
    np.testing.assert_array_equal(r0.pareto_X, r1.pareto_X)
    assert [h[0] for h in r1.history] == [1, 2] and r1.history[1][2].shape == (5, 2)
    assert back.datasets[0].path == str(sample_csv)


def test_run_record_helpers() -> None:
    rec = _record()
    d = rec.display_F()
    np.testing.assert_allclose(d[:, 0], -rec.pareto_F[:, 0])
    assert rec.solution_values(0)["A"] == 100.0 and "tt" in rec.solution_values(0)
    assert 0 <= rec.knee_index() < rec.n_solutions


@pytest.mark.slow
@pytest.mark.parametrize("solver", [SolverSpec("nsga2", {"pop_size": 8, "n_gen": 3}),
                                    SolverSpec("scipy", {"method": "Nelder-Mead", "maxiter": 20})])
def test_run_calibration_inline(short_frame, solver) -> None:
    messages: list[tuple[str, dict]] = []
    spec = spec_for("gamma-uh")
    payload = CalibrationPayload("x", spec.to_dict(), [ObjectiveSpec("nash_sutcliffe").to_dict(),
                                                       ObjectiveSpec("pbias").to_dict()],
                                 solver.to_dict(), short_frame, {})
    out = run_calibration(payload, lambda kind, data: messages.append((kind, data)))
    assert out["pareto_X"].shape[1] == len(out["param_names"]) == 3
    assert out["pareto_F"].shape[1] == 2
    if solver.name == "nsga2":
        assert [m[1]["generation"] for m in messages if m[0] == "progress"] == [1, 2, 3]


@pytest.mark.slow
def test_event_analysis_reports_progress_and_cancels(sample_frame) -> None:
    from sparsehydro_viewer.core.events import run_event_analysis

    calls: list[tuple[int, int, str]] = []
    a = run_event_analysis(sample_frame, {"uh": "gamma-uh"}, progress=lambda i, n, t: calls.append((i, n, t)))
    n = len(a.global_events)
    assert calls[0] == (0, 0, "detecting events")
    assert [c[0] for c in calls[1:-1]] == list(range(n)) and calls[-1] == (n, n, "done")
    stop_after = {"left": 2}

    def should_stop() -> bool:
        stop_after["left"] -= 1
        return stop_after["left"] < 0

    with pytest.raises(InterruptedError):
        run_event_analysis(sample_frame, {"uh": "gamma-uh"}, should_stop=should_stop)


def test_run_calibration_cancels(short_frame) -> None:
    from sparsehydro_viewer.core.calibration import CalibrationCancelled

    payload = CalibrationPayload("x", spec_for("gamma-uh").to_dict(), [ObjectiveSpec("rmse").to_dict()],
                                 SolverSpec("nsga2", {"pop_size": 6, "n_gen": 50}).to_dict(), short_frame, {})
    with pytest.raises(CalibrationCancelled):
        run_calibration(payload, lambda *_: None, should_stop=lambda: True)
