from __future__ import annotations

import numpy as np
import pytest

from helpers import spec_for
from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec, ParameterState, flat_names, parameter_counts
from sparsehydro_viewer.core.components import (
    COMPONENTS,
    ComponentSpec,
    assign_aliases,
    change_type,
    default_tree,
    describe,
    new_component,
    types_for,
)
from sparsehydro_viewer.core.objectives import OBJECTIVES, ObjectiveSpec
from sparsehydro_viewer.core.options import OptionSpec, resolve_options
from sparsehydro_viewer.core.solvers import SOLVERS, SolverSpec


def example_tree() -> ComponentSpec:
    """Sanitary pattern + initial abstraction routed through gamma, Nash and RTK unit hydrographs."""
    root = new_component("sum")
    root.slots["terms"] = [new_component("sanitary"), new_component("rdii")]
    root.slots["terms"][1].slots["uhs"] = [new_component(k) for k in ("gamma-uh", "nash-uh", "rtk-triangle")]
    assign_aliases(root)
    return root


@pytest.mark.parametrize("key", [k for k, t in COMPONENTS.items() if t.role == "flow" or t.also_flow])
def test_every_flow_component_builds_as_a_model(key: str) -> None:
    model = CATALOG.instantiate(ModelSpec(new_component(key)))
    assert model.validate()
    assert parameter_counts(model)[1] > 0


@pytest.mark.parametrize("uh", [t.key for t in types_for(("uh",))])
@pytest.mark.parametrize("abstraction", [t.key for t in types_for(("abstraction",))])
def test_any_uh_with_any_abstraction_in_rdii(uh: str, abstraction: str) -> None:
    root = new_component("rdii")
    root.slots["abstraction"] = new_component(abstraction)
    root.slots["uhs"] = [new_component(uh), new_component("rtk-triangle")]
    model = CATALOG.instantiate(ModelSpec(root))
    # The library seeds R_i from A-type amplitudes (A=100); the builder starts them at 1/n instead.
    assert model.validate(), [(n, model.read_flat_parameter(n)) for n in model.scalar_parameter_names]


def test_example_composition() -> None:
    spec = ModelSpec(example_tree())
    assert describe(spec.root) == "sanitary + RDII(IA; gamma, Nash, RTK)"
    model = CATALOG.instantiate(spec)
    assert model.validate()
    total, cal = parameter_counts(model)
    assert (total, cal) == (66, 64)  # term weights w_1, w_2 start fixed at 1
    assert model.read_flat_parameter("w_1") == 1.0
    infos = CATALOG.describe_parameters(spec)
    groups = {p.group for p in infos}
    assert {"san (Sanitary pattern)", "wet › Initial abstraction", "wet › UH 2: Nash cascade UH"} <= groups
    vec = [p for p in infos if p.vector == "san_pf_hour"]
    assert len(vec) == 24 and vec[3].name == "san_pf_hour[3]"


def test_vector_element_overrides() -> None:
    spec = ModelSpec(example_tree(), parameters={
        "san_pf_hour[3]": ParameterState(value=1.4, upper=2.5),
        "san_pf_month[0]": ParameterState(calibrate=False),
    })
    model = CATALOG.instantiate(spec)
    assert model.read_flat_parameter("san_pf_hour[3]") == pytest.approx(1.4)
    assert model.get_vector_parameter("san_pf_hour").upper_bounds[3] == 2.5
    assert model.get_vector_parameter("san_pf_month").calibrate is False
    assert parameter_counts(model)[1] == 64 - 12


def test_change_type_keeps_fitting_children() -> None:
    node = new_component("rdii")
    node.slots["abstraction"] = new_component("tank-linear")
    excess = change_type(node, "excess-uh")
    assert excess.slots["abstraction"].type == "tank-linear"
    assert change_type(excess, "rdii").slots["abstraction"].type == "tank-linear"


def test_assign_aliases_unique() -> None:
    root = new_component("sum")
    root.slots["terms"] = [new_component("rdii"), new_component("rdii"), new_component("sanitary")]
    assign_aliases(root)
    assert [t.alias for t in root.slots["terms"]] == ["wet", "wet2", "san"]


def test_default_tree_and_spec_round_trip() -> None:
    spec = ModelSpec(default_tree(), {"R_1": ParameterState(value=0.2, calibrate=False)}, "mine")
    back = ModelSpec.from_dict(spec.to_dict())
    assert back.to_dict() == spec.to_dict()
    assert back.structure_key == spec.structure_key
    assert CATALOG.instantiate(back).read_flat_parameter("R_1") == pytest.approx(0.2)


def test_legacy_specs_convert() -> None:
    assert spec_for("abstraction-uh", {"uh": "nash-uh"}).root.slots["uh"].type == "nash-uh"
    rdii = spec_for("rdii", {"n_triangles": 4})
    assert [u.type for u in rdii.root.slots["uhs"]] == ["rtk-triangle"] * 4
    assert spec_for("gamma-uh").root.type == "gamma-uh"


def test_overrides_and_strictness() -> None:
    spec = spec_for("gamma-uh", parameters={"tp": ParameterState(value=7.0, lower=1.0, upper=20.0),
                                            "A": ParameterState(calibrate=False)})
    info = {p.name: p for p in CATALOG.describe_parameters(spec)}
    assert info["tp"].value == 7.0 and (info["tp"].lower, info["tp"].upper) == (1.0, 20.0)
    assert info["A"].calibrate is False and info["tp"].default == 5.0
    bad = spec_for("gamma-uh", parameters={"nope": ParameterState(value=1.0)})
    with pytest.raises(KeyError):
        CATALOG.instantiate(bad)
    assert "nope" not in CATALOG.prune(bad).parameters


def test_flat_names_include_vector_elements() -> None:
    model = CATALOG.instantiate(ModelSpec(new_component("sanitary")))
    names = flat_names(model)
    assert "pf_hour[23]" in names and "pf_month[11]" in names
    assert np.isfinite(model.read_flat_parameter("pf_dow[6]"))


def test_option_coercion() -> None:
    specs = (OptionSpec("a", "int", 1), OptionSpec("b", "choice", "x", choices=("x", "y")))
    assert resolve_options(specs, {"a": "3", "unknown": 1}) == {"a": 3, "b": "x"}
    with pytest.raises(ValueError):
        resolve_options(specs, {"b": "z"})


@pytest.mark.parametrize("entry", OBJECTIVES.entries(), ids=lambda e: e.name)
def test_objective_names_match_library(entry) -> None:
    obj = OBJECTIVES.build(ObjectiveSpec(entry.name))
    assert obj.name == entry.name and obj.minimize == entry.minimize


@pytest.mark.parametrize("entry", SOLVERS.entries(), ids=lambda e: e.name)
def test_every_solver_builds(entry) -> None:
    assert SOLVERS.build(SolverSpec(entry.name), callback=None) is not None
