from __future__ import annotations

import itertools

import numpy as np
import pytest

from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec, flat_names
from sparsehydro_viewer.core.components import default_tree, new_component
from sparsehydro_viewer.core.evaluation import Evaluator
from sparsehydro_viewer.core.objectives import ObjectiveSpec
from sparsehydro_viewer.core.processes import ProcessDesign, from_tree, renames, to_tree
from sparsehydro_viewer.widgets.model_composer import apply_renames


def designs():
    for losses, routing, sanitary in itertools.product(
            [None, "initial-abstraction", "tank-linear"],
            [["triangle-uh"], ["gamma-uh", "nash-uh"], ["rtk-triangle", "rtk-triangle", "gamma-uh"]],
            [False, True]):
        d = ProcessDesign(losses=losses, routing=list(routing), sanitary=sanitary)
        if not d.problems():
            yield d


@pytest.mark.parametrize("design", list(designs()), ids=lambda d: d.describe())
def test_design_round_trips_and_builds(design: ProcessDesign) -> None:
    root = to_tree(design)
    back = from_tree(root)
    assert back is not None and to_tree(back).to_dict() == root.to_dict()
    model = CATALOG.instantiate(ModelSpec(root))
    assert model.validate()


def test_default_model_is_the_default_design() -> None:
    assert from_tree(default_tree()) == ProcessDesign()


def test_rtk_needs_losses() -> None:
    d = ProcessDesign(losses=None, routing=["rtk-triangle"])
    assert d.problems() and "losses" in d.problems()[0]
    with pytest.raises(ValueError):
        to_tree(d)


def test_trees_from_the_advanced_editor_have_no_design() -> None:
    root = new_component("sum")
    root.slots["terms"] = [new_component("rdii"), new_component("rdii")]
    from sparsehydro_viewer.core.components import assign_aliases

    assign_aliases(root)
    assert from_tree(root) is None


def _values_after(old: ProcessDesign, new: ProcessDesign, values: dict[str, float], uh_map=None) -> dict[str, float]:
    moved = apply_renames(values, renames(old, new, uh_map))
    known = set(flat_names(CATALOG.instantiate(ModelSpec(to_tree(new)))))
    return {k: v for k, v in moved.items() if k in known}


def test_growing_a_model_keeps_tuned_values() -> None:
    # start: IA -> one RTK triangle (tuned)
    d0 = ProcessDesign()
    v0 = {"uh1_T": 3.5, "uh1_K": 2.2, "R_1": 0.04, "area_acres": 55.0, "ia_max": 0.3}
    # add a gamma UH: triangle values stay on UH 1
    d1 = ProcessDesign(routing=["rtk-triangle", "gamma-uh"])
    v1 = _values_after(d0, d1, v0)
    assert v1 == v0
    # add a sanitary term: everything moves under wet_
    d2 = ProcessDesign(routing=["rtk-triangle", "gamma-uh"], sanitary=True)
    v2 = _values_after(d1, d2, v1)
    assert v2 == {f"wet_{k}": v for k, v in v1.items()}
    # swap the two hydrographs: the triangle's values follow it to UH 2
    d3 = ProcessDesign(routing=["gamma-uh", "rtk-triangle"], sanitary=True)
    v3 = _values_after(d2, d3, v2, {0: 1, 1: 0})
    assert v3["wet_uh2_T"] == 3.5 and v3["wet_R_2"] == 0.04 and "wet_uh1_T" not in v3
    # switch losses to a tank: abstraction parameters go, area and fractions stay
    d4 = ProcessDesign(losses="tank-linear", routing=["gamma-uh", "rtk-triangle"], sanitary=True)
    v4 = _values_after(d3, d4, v3, {0: 0, 1: 1})
    assert v4["wet_area_acres"] == 55.0 and v4["wet_uh2_T"] == 3.5 and "wet_ia_max" not in v4


def test_direct_unit_hydrographs_keep_values() -> None:
    d0 = ProcessDesign(losses=None, routing=["gamma-uh"])
    v0 = {"A": 120.0, "tt": 3.0, "tp": 7.0}
    d1 = ProcessDesign(losses=None, routing=["gamma-uh", "triangle-uh"])
    assert _values_after(d0, d1, v0) == {"uh1_A": 120.0, "uh1_tt": 3.0, "uh1_tp": 7.0}
    # remove the gamma: the triangle becomes the model and its values follow it
    v1 = {"uh1_A": 120.0, "uh1_tt": 3.0, "uh2_A": 80.0, "uh2_tp": 9.0}
    d2 = ProcessDesign(losses=None, routing=["triangle-uh"])
    assert _values_after(d1, d2, v1, {1: 0}) == {"A": 80.0, "tp": 9.0}


def test_added_rtk_triangles_start_slower() -> None:
    model = CATALOG.instantiate(ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "gamma-uh",
                                                                         "rtk-triangle", "rtk-triangle"]))))
    ts = [model.read_flat_parameter(f"uh{i}_T") for i in (1, 3, 4)]
    assert ts == [1.0, 6.0, 24.0]


def test_designs_evaluate(short_frame) -> None:
    d = ProcessDesign(routing=["rtk-triangle", "gamma-uh"], snow=False, sanitary=True)
    ev = Evaluator(ModelSpec(to_tree(d)), short_frame, [ObjectiveSpec("nash_sutcliffe")])
    assert np.isfinite(ev.evaluate().predicted).all()
