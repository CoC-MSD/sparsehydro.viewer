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
    #: Package the solver needs (``platypus`` is GPL-3.0 and left out of the default Windows installer; ``pymoo``
    #: is optional in sparsehydro).
    requires: str = ""

    @property
    def available(self) -> bool:
        if not self.requires:
            return True
        import importlib.util

        return importlib.util.find_spec(self.requires) is not None


_SEED = OptionSpec("seed", "int", 42, doc="Random seed; fixed seeds make runs reproducible.", minimum=0)


def _create(registry_name: str, **kwargs: Any) -> Any:
    """Build through sparsehydro's solver registry (the viewer's names are kept for saved projects)."""
    from sparsehydro.calibration.solvers import solver_registry

    return solver_registry.create(registry_name, **kwargs)


def _nsga2(o: dict[str, Any], cb: Callback | None) -> Any:
    import warnings

    # Deprecated in sparsehydro, but the viewer offers it on purpose where Platypus is not installed.
    warnings.filterwarnings("ignore", message="NSGAIISolver", category=DeprecationWarning)
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


class _OMOPSO:
    """OMOPSO through sparsehydro's particle-swarm solver; one ε for every objective, expanded at solve time
    (the number of objectives is known only from the problem)."""

    def __init__(self, o: dict[str, Any], cb: Callback | None) -> None:
        self.options, self.callback = dict(o), cb

    def solve(self, problem: Any) -> Any:
        o = self.options
        # OMOPSO's non-uniform mutation shrinks over max_iterations: match it to the evaluation budget.
        iterations = max(1, int(o["n_evaluations"]) // max(1, int(o["swarm_size"])))
        solver = _create("pso", swarm_size=o["swarm_size"], leader_size=o["leader_size"],
                         n_evaluations=o["n_evaluations"], seed=o["seed"], record_frequency=o["record_frequency"],
                         epsilons=[float(o["epsilon"])] * int(problem.n_objectives), callback=self.callback,
                         mutation_probability=float(o["mutation_probability"]), max_iterations=iterations)
        return solver.solve(problem)


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
        SolverEntry("platypus-nsga2", "NSGA-II (Platypus)",
                    "Elitist genetic algorithm (Platypus); the default multi-objective solver.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("NSGAII"), requires="platypus"),
        SolverEntry(
            "nsga2", "NSGA-II (pymoo)",
            "Elitist genetic algorithm (pymoo); offered where Platypus is not installed, e.g. the Windows "
            "installer. Deprecated in sparsehydro.", True, True,
            (OptionSpec("pop_size", "int", 50, label="Population", minimum=4, maximum=10_000),
             OptionSpec("n_gen", "int", 40, label="Generations", minimum=1, maximum=100_000),
             _SEED,
             OptionSpec("n_jobs", "int", 1, label="Parallel workers", minimum=1, maximum=64,
                        doc="Processes used to evaluate each population.")),
            _nsga2, requires="pymoo",
        ),
        SolverEntry("platypus-nsga3", "NSGA-III (Platypus)", "Reference-point NSGA for 3+ objectives.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("NSGAIII"), requires="platypus"),
        SolverEntry("platypus-spea2", "SPEA2 (Platypus)", "Strength Pareto evolutionary algorithm.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("SPEA2"), requires="platypus"),
        SolverEntry("platypus-gde3", "GDE3 (Platypus)", "Generalised differential evolution.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("GDE3"), requires="platypus"),
        SolverEntry("platypus-ibea", "IBEA (Platypus)", "Indicator-based evolutionary algorithm.", True, True,
                    (_EVALS, _SEED, _RECORD), _platypus("IBEA"), requires="platypus"),
        SolverEntry("smpso", "SMPSO (Platypus)", "Speed-constrained multi-objective particle swarm.", True, True,
                    (OptionSpec("swarm_size", "int", 100, label="Swarm size", minimum=4), _EVALS, _SEED, _RECORD),
                    _smpso, requires="platypus"),
        SolverEntry(
            "omopso", "OMOPSO (Platypus)",
            "Multi-objective particle swarm with an ε-dominance archive: the front keeps one solution per ε-box, "
            "so ε sets how finely the trade-off is resolved.", True, True,
            (OptionSpec("swarm_size", "int", 100, label="Swarm size", minimum=4, maximum=10_000,
                        doc="Particles moved at each iteration."),
             OptionSpec("leader_size", "int", 100, label="Leaders", minimum=2, maximum=10_000,
                        doc="Size of the archive the particles are guided by."),
             OptionSpec("epsilon", "float", 0.01, label="ε (all objectives)", minimum=1e-9, maximum=1e6,
                        doc="Resolution of the archive in objective units, the same for every objective; smaller "
                            "keeps more solutions."),
             OptionSpec("mutation_probability", "float", 0.1, label="Mutation probability", minimum=0.0, maximum=1.0,
                        doc="Chance of mutating each particle at each iteration (Platypus default 0.1); the "
                            "mutation's size shrinks as the evaluation budget is used up."),
             _EVALS, _SEED, _RECORD),
            _OMOPSO, requires="platypus",
        ),
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
            _cmaes, requires="platypus",
        ),
    ]


#: Preferred solvers, in order, when a project names none or one that is not installed.
_DEFAULTS = ("platypus-nsga2", "nsga2", "scipy")


class SolverCatalog:
    def __init__(self) -> None:
        self._entries = {e.name: e for e in _entries()}

    def get(self, name: str) -> SolverEntry:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Unknown solver {name!r}; known: {list(self._entries)}") from None

    def entries(self, *, available_only: bool = True) -> list[SolverEntry]:
        """Solvers in display order; by default only those whose package is installed."""
        return [e for e in self._entries.values() if e.available or not available_only]

    def default(self) -> SolverSpec:
        """The preferred available solver: Platypus NSGA-II, else pymoo NSGA-II, else SciPy."""
        name = next((n for n in _DEFAULTS if self._entries[n].available), "scipy")
        return SolverSpec(name)

    def usable(self, spec: SolverSpec | None) -> tuple[SolverSpec, str]:
        """*spec* if its solver is installed; otherwise the closest available one and a note saying so.

        The two NSGA-II implementations convert into each other (population x generations <-> evaluations,
        same seed), so projects move between pip installations (Platypus) and the Windows installer (pymoo).
        """
        if spec is not None and spec.name in self._entries and self._entries[spec.name].available:
            return spec, ""
        missing = "no solver" if spec is None else (
            f"{self._entries[spec.name].label} is not installed" if spec.name in self._entries
            else f"unknown solver {spec.name!r}")
        o = dict(spec.options) if spec is not None else {}
        seed = {"seed": o["seed"]} if "seed" in o else {}
        if spec is not None and spec.name == "nsga2" and self._entries["platypus-nsga2"].available:
            evals = int(o.get("pop_size", 50)) * int(o.get("n_gen", 40))
            return SolverSpec("platypus-nsga2", {"n_evaluations": evals, **seed}), \
                f"{missing}; using NSGA-II (Platypus) with {evals} evaluations"
        if spec is not None and spec.name == "platypus-nsga2" and self._entries["nsga2"].available:
            pop = 50
            gens = max(1, int(o.get("n_evaluations", 2000)) // pop)
            return SolverSpec("nsga2", {"pop_size": pop, "n_gen": gens, **seed}), \
                f"{missing}; using NSGA-II (pymoo), population {pop} for {gens} generations"
        fallback = self.default()
        return fallback, f"{missing}; using {self._entries[fallback.name].label}"

    def build(self, spec: SolverSpec, callback: Callback | None = None) -> Any:
        entry = self.get(spec.name)
        return entry.factory(resolve_options(entry.options, spec.options), callback)


SOLVERS = SolverCatalog()

__all__ = ["SOLVERS", "SolverCatalog", "SolverEntry", "SolverSpec"]
