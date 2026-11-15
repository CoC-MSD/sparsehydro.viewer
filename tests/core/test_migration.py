"""Step-based unit hydrograph parameters are converted to the hours-based library."""

from __future__ import annotations

import math

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec, ParameterState
from sparsehydro_viewer.core.data import DatasetSpec
from sparsehydro_viewer.core.migration import (
    dt_hours_of,
    migrate_model_spec,
    migrate_run,
    migrate_values,
    renames_for,
)
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.processes import ProcessDesign, to_tree
from sparsehydro_viewer.core.project import Project
from sparsehydro_viewer.core.runs import RunRecord, new_id
from sparsehydro_viewer.core.store import ProjectStore
from sparsehydro_viewer.core.uh import kernel_curves

DT = 5 / 60


def _old_gamma(tt: float, tp: float, dt: float, n: int = 4000) -> tuple[np.ndarray, np.ndarray]:
    """The step-based library's gamma kernel: ``(t/tp)^tt exp(-t/tp)`` at t = 1, 2, ... steps."""
    t = np.arange(1, n + 1, dtype=float)
    raw = (t / tp) ** tt * np.exp(-t / tp)
    return t * dt, raw / (raw.sum() * dt)


def test_gamma_conversion_reproduces_the_old_shape() -> None:
    spec = spec_for("gamma-uh", parameters={"tt": ParameterState(2.0), "tp": ParameterState(30.0),
                                            "A": ParameterState(100.0)})
    new = migrate_model_spec(spec, DT)
    assert new.parameters["alpha"].value == 3.0 and new.parameters["theta"].value == pytest.approx(2.5)
    assert new.parameters["A"].value == pytest.approx(100.0 * DT)
    assert "tt" not in new.parameters and "tp" not in new.parameters
    built = CATALOG.build(new)
    built.model.initialize()
    for name, state in new.parameters.items():
        built.model.apply_flat_parameter(name, state.value)
    curve = kernel_curves(built, DT)[0]
    t_old, k_old = _old_gamma(2.0, 30.0, DT)
    centroid_old = float(np.sum((t_old - DT / 2) * k_old) / np.sum(k_old))
    assert curve.centroid == pytest.approx(centroid_old, abs=DT)
    assert curve.time_to_peak == pytest.approx(t_old[np.argmax(k_old)], abs=DT)


def test_other_shapes_and_amplitude_rules() -> None:
    nash = migrate_values(spec_for("nash-uh"), {"n": 3.0, "k": 12.0, "A": 50.0}, DT)
    assert nash == {"n": 3.0, "K": pytest.approx(1.0), "A": pytest.approx(50 * DT)}
    tri = migrate_values(spec_for("triangle-uh"), {"tp": 12.0, "tt": 36.0}, DT)
    assert tri == {"Tp": pytest.approx(1.0), "Tb": pytest.approx(3.0)}
    decay = migrate_values(spec_for("decay-uh"), {"alpha": math.exp(-DT / 2.0)}, DT)
    assert decay["K"] == pytest.approx(2.0)
    pt = migrate_values(spec_for("abstraction-uh"), {"uh_peak_tp": 12.0, "uh_tail_tt": 1.0, "uh_w": 0.3,
                                                      "uh_td": 6.0}, DT)
    assert pt == {"uh_peak_Tp": pytest.approx(1.0), "uh_tail_alpha": 2.0, "uh_w": 0.3, "uh_td": pytest.approx(0.5)}
    # excess -> UH: the UH's amplitude uh_A scales the flow, so it is rescaled too
    assert migrate_values(spec_for("abstraction-uh", {"uh": "gamma-uh"}), {"uh_A": 60.0, "ia_max": 0.2}, DT) == \
        {"uh_A": pytest.approx(60 * DT), "ia_max": 0.2}
    # inside an RDII component the amplitude is R_i, which is not rescaled; RTK triangles were already in hours
    rdii = ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh"])))
    table = renames_for(rdii)
    assert set(table) == {"uh2_tt", "uh2_tp"}
    assert migrate_values(rdii, {"R_1": 0.04, "uh1_T": 2.0, "uh2_tp": 24.0}, DT) == \
        {"R_1": 0.04, "uh1_T": 2.0, "uh2_theta": pytest.approx(2.0)}


def test_run_pareto_columns_are_converted() -> None:
    spec = spec_for("gamma-uh", parameters={"A": ParameterState(80.0, calibrate=False)})
    run = RunRecord(new_id(), "old", "site", spec, [ObjectiveSpec("nash_sutcliffe")], None, status="finished",
                    param_names=["tt", "tp"], objective_names=["nash_sutcliffe"], minimize_flags=[False],
                    fixed_values={"A": 80.0}, pareto_X=np.array([[1.0, 12.0], [2.0, 24.0]]),
                    pareto_F=np.array([[-0.5], [-0.6]]))
    assert migrate_run(run, DT)
    assert run.param_names == ["alpha", "theta"]
    np.testing.assert_allclose(run.pareto_X, [[2.0, 1.0], [3.0, 2.0]])
    assert run.fixed_values == {"A": pytest.approx(80 * DT)}
    assert run.model.parameters["A"].value == pytest.approx(80 * DT)
    assert "step-based" in run.message  # (a run is converted once: projects are marked when saved)


def test_dt_from_frame(sample_frame) -> None:
    assert dt_hours_of(sample_frame) == pytest.approx(DT)
    assert dt_hours_of(sample_frame.iloc[:1]) is None


def test_old_project_file_is_converted_once(tmp_path, sample_frame, sample_csv) -> None:
    project = Project("old")
    spec = DatasetSpec("site", path=str(sample_csv))
    project.add_dataset(spec, sample_frame)
    working = spec_for("gamma-uh", parameters={"tt": ParameterState(2.0, 0.5, 10.0), "tp": ParameterState(24.0)})
    project.models = [working]
    project.ui_state["model"] = working.to_dict()
    project.runs = [RunRecord(new_id(), "r", "site", working, [ObjectiveSpec("pbias")], None, status="finished",
                              param_names=["tp"], objective_names=["pbias"], minimize_flags=[True],
                              pareto_X=np.array([[12.0]]), pareto_F=np.array([[3.0]]))]
    path = project.save(tmp_path / "old.shproj")
    st = ProjectStore.open(path)  # pretend the file was written before the hours-based library
    st.set_setting("uh_schema", 1)
    st.save_to(path)

    back = Project.load(path)
    assert back.migrated and not back.import_warnings
    assert back.models[0].parameters["alpha"].value == 3.0
    assert (back.models[0].parameters["alpha"].lower, back.models[0].parameters["alpha"].upper) == (1.5, 11.0)
    assert back.models[0].parameters["theta"].value == pytest.approx(2.0)
    assert ModelSpec.from_dict(back.ui_state["model"]).parameters["theta"].value == pytest.approx(2.0)
    assert back.runs[0].param_names == ["theta"] and back.runs[0].pareto_X[0, 0] == pytest.approx(1.0)

    back.save()  # saved files are marked: opening again converts nothing
    again = Project.load(path)
    assert not again.migrated and again.models[0].parameters["theta"].value == pytest.approx(2.0)
