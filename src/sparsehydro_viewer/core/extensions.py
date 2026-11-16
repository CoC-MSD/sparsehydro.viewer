"""Load sparsehydro extensions so their models, objectives and solvers are discovered.

sparsehydro registers a class when the module defining it is imported, and
:func:`sparsehydro.load_extensions` imports extension modules: the ones
installed packages declare in the ``sparsehydro.extensions`` entry-point group,
plus modules or ``.py`` files passed to it. The viewer calls it before building
its catalogs, adding the modules listed in the user's settings
(``extensions/modules``) for work in progress that is not installed.
"""

from __future__ import annotations

from sparsehydro.registry import EXTENSION_GROUP as GROUP
from sparsehydro.registry import ExtensionReport
from sparsehydro.registry import load_extensions as _load


def load_extensions(extra: list[str] | None = None, *, entry_points: bool = True) -> ExtensionReport:
    """Import installed extensions (once per process) and *extra* modules or ``.py`` files.

    Failures are reported in the returned (cumulative) report, not raised.
    """
    return _load(extra or [], entry_points=entry_points)


def report() -> ExtensionReport:
    return _load([], entry_points=False)


__all__ = ["GROUP", "ExtensionReport", "load_extensions", "report"]
