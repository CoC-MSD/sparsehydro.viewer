"""Components and internal states of viewer-built models (core/trace.py)."""

from __future__ import annotations

import numpy as np
import pytest

from sparsehydro_viewer.core.catalog import ModelSpec
from sparsehydro_viewer.core.data import Period
from sparsehydro_viewer.core.evaluation import Evaluator
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.processes import ProcessDesign, to_tree
from sparsehydro_viewer.core.trace import flow_parts, leaf_label, state_fields


def _evaluate(design: ProcessDesign, frame, values=None):
    ev = Evaluator(ModelSpec(to_tree(design)), frame, [ObjectiveSpec("nash_sutcliffe")], Period())
    res = ev.evaluate(values or {})
    trace = ev.trace()
    trace.setdefault(ev.predicted_key, res.predicted)
    return ev, res, trace


@pytest.mark.parametrize("design, n_parts", [
    (ProcessDesign(routing=["rtk-triangle", "gamma-uh", "rtk-triangle"]), 3),
    (ProcessDesign(routing=["rtk-triangle", "nash-uh"], sanitary=True), 3),  # sanitary + 2 unit hydrographs
    (ProcessDesign(losses=None, routing=["peak-tail-uh"]), 2),  # the peak and tail parts
])
def test_individual_hydrographs_add_up_to_the_simulation(design, n_parts, short_frame) -> None:
    ev, res, trace = _evaluate(design, short_frame)
    fields = ev.trace_fields()
    parts = flow_parts(fields, trace, ev.predicted_key)
    assert len(parts) == n_parts
    total = np.sum([y for _, y in parts], axis=0)
    np.testing.assert_allclose(total, res.predicted, rtol=1e-8, atol=1e-10 * max(1.0, np.abs(res.predicted).max()))
    labels = {f.name: f.label for f in fields}
    assert all(labels[name] for name, _ in parts)


def test_sum_weights_scale_the_parts(short_frame) -> None:
    design = ProcessDesign(routing=["rtk-triangle", "gamma-uh"], sanitary=True)
    ev, res, trace = _evaluate(design, short_frame, {"w_2": 0.5})
    parts = dict(flow_parts(ev.trace_fields(), trace, ev.predicted_key))
    np.testing.assert_allclose(sum(parts.values()), res.predicted, rtol=1e-8, atol=1e-12)


def test_states_of_the_losses_are_listed(short_frame) -> None:
    ev, _, trace = _evaluate(ProcessDesign(), short_frame)
    states = state_fields(ev.trace_fields())
    names = [f.name for f in states]
    assert "ia.ia_available" in names
    f = next(s for s in states if s.name == "ia.ia_available")
    assert f.role == "state" and f.label == "ia › remaining abstraction" and f.units == "in"
    assert len(trace["ia.ia_available"]) == len(short_frame)


def test_labels() -> None:
    assert leaf_label("rdii_component_2", "RDII flow routed through unit hydrograph 2 (GammaUH)") == "UH 2 (GammaUH)"
    assert leaf_label("san_contribution") == "san"
    assert leaf_label("peak_Q_pred") == "peak part"
    assert leaf_label("S_in") == "soil store"
