"""Components, objectives and losses are discovered from sparsehydro's registries, extensions included."""

from __future__ import annotations

import textwrap

import pytest

from sparsehydro_viewer.core import components
from sparsehydro_viewer.core.catalog import CATALOG, ModelSpec
from sparsehydro_viewer.core.extensions import load_extensions
from sparsehydro_viewer.core.objectives import OBJECTIVES, ObjectiveSpec
from sparsehydro_viewer.core.processes import LOSS_KEYS, NEEDS_LOSSES, ROUTING_KEYS, ProcessDesign, to_tree

EXTENSION = textwrap.dedent('''
    """A test extension: one unit hydrograph and one objective."""
    import numpy as np
    from sparsehydro.metrics.objectives import IObjective, objective_registry
    from sparsehydro.models.unithydrograph.models import GammaUH
    from sparsehydro.registry import registry


    @registry.register
    class SlowGammaUH(GammaUH):
        """A gamma UH registered by an extension."""
        model_name = "test-slow-gamma-uh"


    class PeakError(IObjective):
        """Absolute error of the maximum."""
        name = "test_peak_error"
        minimize = True

        def __init__(self, scale: float = 1.0, mask=None):
            super().__init__(mask)
            self.scale = scale

        def evaluate(self, observed, predicted):
            return self.scale * abs(float(np.max(observed)) - float(np.max(predicted)))


    objective_registry.add(PeakError.name, PeakError)
''')


@pytest.fixture
def extension(tmp_path):
    from sparsehydro.metrics.objectives import objective_registry
    from sparsehydro.registry import registry

    path = tmp_path / "my_extension.py"
    path.write_text(EXTENSION, encoding="utf-8")
    yield path
    for reg, name in ((registry, "test-slow-gamma-uh"), (objective_registry, "test_peak_error")):
        if name in reg:
            reg.unregister(name)
    components.refresh()
    OBJECTIVES.refresh()


def test_library_components_are_discovered() -> None:
    assert {"rtk-triangle", "gamma-uh", "clark-uh", "scs-uh", "mixture-uh", "weibull-uh"} <= set(ROUTING_KEYS)
    assert LOSS_KEYS[:4] == ["initial-abstraction", "tank-constant", "tank-linear", "tank-sqrt"]
    assert "rdii" not in LOSS_KEYS  # its primary output is flow, not excess
    assert {"rtk-triangle"} == NEEDS_LOSSES  # the only routing component that reads excess instead of rain
    assert [o.name for o in components.COMPONENTS["initial-abstraction"].options] == ["snow"]
    assert not components.COMPONENTS["gamma-uh"].options  # float arguments are parameters, not options
    # objectives that need data arrays (event windows, dry/storm masks) wait for the Events/Assess phases
    assert set(OBJECTIVES.unavailable()) == {"con15_error", "disjoint_ccc"}
    assert "wrmse" in {e.name for e in OBJECTIVES.entries()}  # weights are optional


def test_extension_module_adds_a_routing_process_and_an_objective(extension) -> None:
    report = load_extensions([str(extension)])
    assert str(extension) in report.loaded and not report.failed
    components.refresh()
    OBJECTIVES.refresh()
    assert "test-slow-gamma-uh" in ROUTING_KEYS  # the live list seen by the process builder
    assert components.COMPONENTS["test-slow-gamma-uh"].also_flow
    model = CATALOG.instantiate(ModelSpec(to_tree(ProcessDesign(routing=["rtk-triangle", "test-slow-gamma-uh"]))))
    assert "uh2_theta" in model.scalar_parameter_names
    entry = OBJECTIVES.get("test_peak_error")
    assert entry.minimize and [o.name for o in entry.options] == ["scale"]
    assert OBJECTIVES.build(ObjectiveSpec("test_peak_error", {"scale": 2.0})).scale == 2.0


def test_broken_extension_is_reported_not_raised(tmp_path) -> None:
    bad = tmp_path / "broken_ext.py"
    bad.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    report = load_extensions([str(bad), "no_such_module_xyz"])
    failed = dict(report.failed)
    assert "boom" in failed[str(bad)] and "ModuleNotFoundError" in failed["no_such_module_xyz"]
