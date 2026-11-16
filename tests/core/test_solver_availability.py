"""Solvers offered depend on what is installed; NSGA-II converts between Platypus and pymoo."""

from __future__ import annotations

import pytest

from sparsehydro_viewer.core import solvers as solvers_mod
from sparsehydro_viewer.core.solvers import SOLVERS, SolverSpec


@pytest.fixture
def installed(monkeypatch):
    """Pretend only the given packages are installed (``None`` = the real environment)."""
    real = solvers_mod.SolverEntry.available

    def set_installed(packages: set[str]) -> None:
        monkeypatch.setattr(solvers_mod.SolverEntry, "available",
                            property(lambda e: not e.requires or e.requires in packages))

    yield set_installed
    monkeypatch.setattr(solvers_mod.SolverEntry, "available", real)


def test_pip_installation_prefers_platypus(installed) -> None:
    installed({"platypus"})
    assert SOLVERS.default().name == "platypus-nsga2"
    names = [e.name for e in SOLVERS.entries()]
    assert "nsga2" not in names and {"platypus-nsga2", "omopso", "cmaes", "scipy"} <= set(names)
    spec, note = SOLVERS.usable(SolverSpec("nsga2", {"pop_size": 20, "n_gen": 30, "seed": 7}))
    assert spec == SolverSpec("platypus-nsga2", {"n_evaluations": 600, "seed": 7})
    assert "NSGA-II (pymoo) is not installed" in note


def test_windows_installer_uses_pymoo(installed) -> None:
    installed({"pymoo"})
    assert SOLVERS.default().name == "nsga2"
    assert [e.name for e in SOLVERS.entries()] == ["nsga2", "scipy"]
    spec, note = SOLVERS.usable(SolverSpec("platypus-nsga2", {"n_evaluations": 5000, "seed": 3}))
    assert spec == SolverSpec("nsga2", {"pop_size": 50, "n_gen": 100, "seed": 3})
    spec, note = SOLVERS.usable(SolverSpec("omopso", {}))  # no counterpart: the default
    assert spec.name == "nsga2" and "OMOPSO (Platypus) is not installed" in note


def test_nothing_multi_objective_falls_back_to_scipy(installed) -> None:
    installed(set())
    assert SOLVERS.default().name == "scipy"
    assert SOLVERS.usable(SolverSpec("nsga2"))[0].name == "scipy"


def test_installed_solver_is_kept(installed) -> None:
    installed({"platypus", "pymoo"})
    spec = SolverSpec("nsga2", {"pop_size": 8})
    assert SOLVERS.usable(spec) == (spec, "")


def test_opening_a_project_switches_to_an_installed_nsga2(installed, tmp_path) -> None:
    from sparsehydro_viewer.core.project import Project

    installed({"platypus", "pymoo"})
    p = Project(solver=SolverSpec("platypus-nsga2", {"n_evaluations": 1000}))
    path = p.save(tmp_path / "p.shproj")
    installed({"pymoo"})  # the same project opened with the Windows installer
    back = Project.load(path)
    assert back.solver == SolverSpec("nsga2", {"pop_size": 50, "n_gen": 20})
    assert any("Optimizer" in w for w in back.import_warnings)
