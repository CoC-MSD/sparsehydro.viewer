"""Qt-free application core: specifications, catalogs, evaluation and persistence.

Only this package and :mod:`sparsehydro_viewer.services` import
:mod:`sparsehydro`; widgets and views work with the objects defined here.
"""

from .catalog import CATALOG, ModelSpec, ParameterInfo, ParameterState, parameter_counts
from .data import DatasetSpec, Period, load_dataset
from .evaluation import Evaluation, Evaluator
from .objectives import DEFAULT_OBJECTIVES, OBJECTIVES, ObjectiveSpec
from .project import Project
from .runs import RunRecord
from .solvers import SOLVERS, SolverSpec


def versions() -> dict[str, str]:
    """Installed versions of the main dependencies (for About and bug reports)."""
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for dist, key in (("sparsehydro", "sparsehydro"), ("PySide6-Essentials", "PySide6"), ("pyqtgraph", "pyqtgraph"),
                      ("numpy", "numpy"), ("pandas", "pandas")):
        try:
            out[key] = version(dist)
        except PackageNotFoundError:
            out[key] = "not installed"
    return out


__all__ = [
    "versions",
    "CATALOG",
    "DEFAULT_OBJECTIVES",
    "OBJECTIVES",
    "SOLVERS",
    "DatasetSpec",
    "Evaluation",
    "Evaluator",
    "ModelSpec",
    "ObjectiveSpec",
    "ParameterInfo",
    "ParameterState",
    "Period",
    "Project",
    "RunRecord",
    "SolverSpec",
    "load_dataset",
    "parameter_counts",
]
