"""MSDGC assessment of viewer models (core/assess.py)."""

from __future__ import annotations

import numpy as np
import pytest

from sparsehydro_viewer.core.assess import ASSESS_OPTIONS, detect_events, run_assessment, site_inputs
from sparsehydro_viewer.core.catalog import ModelSpec
from sparsehydro_viewer.core.data import DatasetSpec, Period
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.options import resolve_options
from sparsehydro_viewer.core.processes import ProcessDesign, to_tree

OPTS = resolve_options(ASSESS_OPTIONS, {"period": "whole"})


def test_events_are_detected_on_the_sample(sample_frame) -> None:
    ev = detect_events(sample_frame, OPTS)
    assert len(ev) >= 3
    assert {"event_id", "start_idx", "end_idx", "duration_hours"} <= set(ev.columns)
    assert (ev["end_idx"] > ev["start_idx"]).all() and ev["end_idx"].max() < len(sample_frame)


def test_site_inputs() -> None:
    assert site_inputs({"shv:odwf_a": 2.0, "shv:sewer_system": "combined"}, "storm") == (2.0, "combined", [])
    odwf, system, notes = site_inputs({"shv:capacity_flow": 3.0}, "storm")
    assert odwf == pytest.approx(6.0) and system == "sanitary" and len(notes) == 2  # 3.0 / 0.5 (storm, sanitary)
    assert site_inputs({}, "total")[0] is None


def test_assessment_of_a_model(sample_frame) -> None:
    ds = DatasetSpec("s", calibration=Period("2022-05-01", "2022-05-14"))
    spec = ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh"])))
    run = run_assessment(spec, {}, sample_frame, ds, {"shv:odwf_a": 0.5}, OPTS, [ObjectiveSpec("nash_sutcliffe")])
    res = run.result
    assert res.grade in ("pass", "conditional", "fail") and run.period == "Whole record"
    assert len(run.simulated) == len(sample_frame) == len(run.observed)
    assert set(res.summary["group"]) == {"all", "critical", "non_critical"}
    assert res.events["included"].sum() >= 2 and np.isfinite(res.con15["percent"])
    assert not res.qcritical.empty
    assert any("Sewer system not set" in w for w in res.warnings)
    # the calibration period only covers part of the record
    cal = run_assessment(spec, {}, sample_frame, ds, {}, resolve_options(ASSESS_OPTIONS, {}),
                         [ObjectiveSpec("nash_sutcliffe")])
    assert len(cal.observed) < len(sample_frame) and cal.result.qcritical.empty
    with pytest.raises(ValueError, match="validation"):
        run_assessment(spec, {}, sample_frame, ds, {}, resolve_options(ASSESS_OPTIONS, {"period": "validation"}),
                       [ObjectiveSpec("nash_sutcliffe")])
