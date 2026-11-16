"""Qt-free application core: specifications, catalogs, evaluation and persistence.

Only this package and :mod:`sparsehydro_viewer.services` import
:mod:`sparsehydro`; widgets and views work with the objects defined here.
"""

from .diagnostics import quiet_slow_response_warning

quiet_slow_response_warning()

from .catalog import CATALOG, ModelSpec, ParameterInfo, ParameterState, parameter_counts  # noqa: E402
from .data import DatasetSpec, Period, load_dataset  # noqa: E402
from .evaluation import Evaluation, Evaluator  # noqa: E402
from .objectives import DEFAULT_OBJECTIVES, OBJECTIVES, ObjectiveSpec  # noqa: E402
from .project import Project  # noqa: E402
from .runs import RunRecord  # noqa: E402
from .solvers import SOLVERS, SolverSpec  # noqa: E402


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
