"""Solver catalog: optimisers the viewer can configure and run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .options import OptionSpec, resolve_options

Callback = Callable[[dict[str, Any]], None]


@dataclass
class SolverSpec:
    """Serialisable solver choice."""

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "options": dict(self.options)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SolverSpec:
        return cls(d["name"], dict(d.get("options", {})))


@dataclass(frozen=True)
class SolverEntry:
    """How to build one solver.

    :ivar multi_objective: ``False`` for scalar optimisers, which optimise
        ``objective_index`` only and return a single solution.
    :ivar supports_callback: Whether per-generation progress is reported.
        Runs without it can still be cancelled (the worker process is stopped).
    """

    name: str
    label: str
    description: str
    multi_objective: bool
    supports_callback: bool
    options: tuple[OptionSpec, ...]
    factory: Callable[[dict[str, Any], Callback | None], Any]


_SEED = OptionSpec("seed", "int", 42, doc="Random seed; fixed seeds make runs reproducible.", minimum=0)


def _create(registry_name: str, **kwargs: Any) -> Any:
    """Build through sparsehydro's solver registry (the viewer's names are kept for saved projects)."""
    from sparsehydro.calibration.solvers import solver_registry

    return solver_registry.create(registry_name, **kwargs)


def _nsga2(o: dict[str, Any], cb: Callback | None) -> Any:
    return _create("pymoo_nsga2", pop_size=o["pop_size"], n_gen=o["n_gen"], seed=o["seed"], n_jobs=o["n_jobs"],
                   callback=cb)


def _platypus(algorithm: str) -> Callable[[dict[str, Any], Callback | None], Any]:
    def build(o: dict[str, Any], cb: Callback | None) -> Any:
        import platypus

        return _create("platypus", algorithm_class=getattr(platypus, algorithm), n_evaluations=o["n_evaluations"],
                       seed=o["seed"], record_frequency=o["record_frequency"], callback=cb)

    return build


def _smpso(o: dict[str, Any], cb: Callback | None) -> Any:
    return _create("pso", swarm_size=o["swarm_size"], leader_size=o["swarm_size"], n_evaluations=o["n_evaluations"],
                   seed=o["seed"], record_frequency=o["record_frequency"], callback=cb)


def _scipy(o: dict[str, Any], _cb: Callback | None) -> Any:
    return _create("scipy", method=o["method"], objective_index=o["objective_index"], maxiter=o["maxiter"],
                   seed=o["seed"])


def _cmaes(o: dict[str, Any], _cb: Callback | None) -> Any:
    return _create("cmaes", objective_index=o["objective_index"], n_trials=o["n_trials"], seed=o["seed"],
                   multi_start=o["multi_start"], verbose=False)


_EVALS = OptionSpec("n_evaluations", "int", 5000, label="Evaluations", minimum=10, maximum=10_000_000,
                    doc="Total model evaluations budget.")
_RECORD = OptionSpec("record_frequency", "int", 100, label="Report every", minimum=1,
                     doc="Iterations between progress reports.")


def _entries() -> list[SolverEntry]:
    return [
        SolverEntry(
            "nsga2", "NSGA-II (pymoo)", "Elitist genetic algorithm; the default multi-objective solver.", True, True,
            (OptionSpec("pop_size", "int", 50, label="Population", minimum=4, maximum=10_000),
             OptionSpec("n_gen", "int", 40, label="Generations", minimum=1, maximum=100_000),
             _SEED,
             OptionSpec("n_jobs", "int", 1, label="Parallel workers", minimum=1, maximum=64,
                        doc="Processes used to evaluate each population.")),
            _nsga2,
        ),
        SolverEntry("platypus-nsga2", "NSGA-II (Platypus)", "NSGA-II as implemented in Platypus.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("NSGAII")),
        SolverEntry("platypus-nsga3", "NSGA-III (Platypus)", "Reference-point NSGA for 3+ objectives.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("NSGAIII")),
        SolverEntry("platypus-spea2", "SPEA2 (Platypus)", "Strength Pareto evolutionary algorithm.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("SPEA2")),
        SolverEntry("platypus-gde3", "GDE3 (Platypus)", "Generalised differential evolution.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("GDE3")),
        SolverEntry("platypus-ibea", "IBEA (Platypus)", "Indicator-based evolutionary algorithm.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("IBEA")),
        SolverEntry("smpso", "SMPSO (Platypus)", "Speed-constrained multi-objective particle swarm.", True, True,
                    (OptionSpec("swarm_size", "int", 100, label="Swarm size", minimum=4), _EVALS, _SEED, _RECORD),
                    _smpso),
        SolverEntry(
            "scipy", "SciPy (single objective)",
            "Scalar optimiser on one objective; returns one solution. No progress reporting.", False, False,
            (OptionSpec("method", "choice", "differential_evolution", label="Method",
                        choices=("differential_evolution", "Nelder-Mead", "Powell", "L-BFGS-B")),
             OptionSpec("objective_index", "int", 0, label="Objective #", minimum=0,
                        doc="Position of the objective to optimise in the objective list."),
             OptionSpec("maxiter", "int", 200, label="Max iterations", minimum=1),
             _SEED),
            _scipy,
        ),
        SolverEntry(
            "cmaes", "CMA-ES (single objective)",
            "Covariance matrix adaptation on one objective, optionally from several starts; returns one solution. "
            "No progress reporting.", False, False,
            (OptionSpec("objective_index", "int", 0, label="Objective #", minimum=0,
                        doc="Position of the objective to optimise in the objective list."),
             OptionSpec("n_trials", "int", 2000, label="Evaluations", minimum=10),
             OptionSpec("multi_start", "int", 1, label="Starts", minimum=1, maximum=64,
                        doc="Independent restarts; the best result is kept."),
             _SEED),
            _cmaes,
        ),
    ]


class SolverCatalog:
    def __init__(self) -> None:
        self._entries = {e.name: e for e in _entries()}

    def get(self, name: str) -> SolverEntry:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Unknown solver {name!r}; known: {list(self._entries)}") from None

    def entries(self) -> list[SolverEntry]:
        return list(self._entries.values())

    def build(self, spec: SolverSpec, callback: Callback | None = None) -> Any:
        entry = self.get(spec.name)
        return entry.factory(resolve_options(entry.options, spec.options), callback)


SOLVERS = SolverCatalog()

__all__ = ["SOLVERS", "SolverCatalog", "SolverEntry", "SolverSpec"]
