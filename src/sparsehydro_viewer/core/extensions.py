"""Load sparsehydro extensions so their models, objectives and solvers are discovered.

sparsehydro registers a model when its class is defined (``@registry.register``
with a ``model_name``); objectives and solvers have their own registries
(``objective_registry.add``, ``solver_registry.add``). A class is therefore
discoverable once the module that defines it has been imported. This module
imports extension modules from two places before the viewer builds its
catalogs:

* **Installed packages** that declare an entry point in the
  ``sparsehydro.extensions`` group, e.g. in the extension's ``pyproject.toml``::

      [project.entry-points."sparsehydro.extensions"]
      my_models = "my_package.models"

* **User settings**: module names or ``.py`` files listed under
  ``extensions/modules`` (one per line), for work in progress that is not
  installed.

Failures are collected, not raised, so one broken extension does not stop the
application; :func:`load_extensions` returns what was loaded and what failed.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

GROUP = "sparsehydro.extensions"


@dataclass
class ExtensionReport:
    loaded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


_REPORT: ExtensionReport | None = None


def _import(target: str) -> None:
    path = Path(target)
    if path.suffix == ".py":
        if not path.is_file():
            raise FileNotFoundError(target)
        name = f"sparsehydro_ext_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {target}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    else:
        importlib.import_module(target)


def load_extensions(extra: list[str] | None = None, *, entry_points: bool = True) -> ExtensionReport:
    """Import extension modules (once per process; later calls only import new *extra* targets).

    :param extra: Module names or ``.py`` paths (typically from the user's settings).
    :param entry_points: Also load the ``sparsehydro.extensions`` entry points of installed packages.
    """
    global _REPORT
    first = _REPORT is None
    report = _REPORT if _REPORT is not None else ExtensionReport()
    targets: list[tuple[str, object]] = []
    if first and entry_points:
        from importlib.metadata import entry_points as eps

        for ep in eps(group=GROUP):
            targets.append((f"{ep.name} ({ep.value})", ep))
    for t in extra or []:
        t = t.strip()
        if t and t not in report.loaded and t not in {f for f, _ in report.failed}:
            targets.append((t, t))
    for label, target in targets:
        try:
            if isinstance(target, str):
                _import(target)
            else:
                target.load()  # type: ignore[attr-defined]
            report.loaded.append(label)
        except Exception as exc:  # noqa: BLE001 - report and continue
            report.failed.append((label, f"{type(exc).__name__}: {exc}"))
    _REPORT = report
    return report


def report() -> ExtensionReport:
    return _REPORT or ExtensionReport()


__all__ = ["GROUP", "ExtensionReport", "load_extensions", "report"]
