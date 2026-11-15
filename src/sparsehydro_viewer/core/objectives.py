"""Objective catalog: the objectives registered in sparsehydro, as the viewer offers them.

Entries come from :data:`sparsehydro.metrics.objectives.objective_registry`;
direction (``minimize``) comes from the objective class and options from its
constructor. The viewer only adds display labels and short descriptions.
Objectives whose constructor needs data the viewer cannot yet supply (event
windows, per-step weights, dry/storm masks) are listed by :meth:`unavailable`
and hidden from the choosers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .options import OptionSpec, resolve_options, signature_options


@dataclass
class ObjectiveSpec:
    """Serialisable objective choice."""

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "options": dict(self.options)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ObjectiveSpec:
        return cls(d["name"], dict(d.get("options", {})))


@dataclass(frozen=True)
class ObjectiveEntry:
    name: str
    label: str
    minimize: bool
    description: str
    options: tuple[OptionSpec, ...]
    factory: Callable[[dict[str, Any]], Any]


#: Display labels and descriptions; anything else falls back to the class docstring.
_LABELS: dict[str, tuple[str, str]] = {
    "nash_sutcliffe": ("NSE", "Nash-Sutcliffe efficiency (1 is perfect)."),
    "kge": ("KGE", "Kling-Gupta efficiency (1 is perfect)."),
    "ccc": ("Lin's CCC", "Concordance correlation coefficient."),
    "log_nse": ("log NSE", "NSE of log flows; emphasises recessions."),
    "index_of_agreement": ("Index of agreement", "Willmott's d."),
    "rmse": ("RMSE", "Root mean square error (flow units)."),
    "mae": ("MAE", "Mean absolute error (flow units)."),
    "mse": ("MSE", "Mean square error."),
    "peak_weighted_mse": ("Peak-weighted MSE", "MSE weighted by observed flow^power."),
    "pbias": ("PBIAS", "Absolute percent bias in volume."),
    "volume_relative_error": ("Volume error", "Relative volume error."),
    "con15_error": ("Con15 error", "Error of the peak slope over the top 15 % of events."),
    "wrmse": ("Weighted RMSE", "RMSE with per-step weights."),
    "disjoint_ccc": ("Dry/storm CCC", "CCC combined over dry and storm windows."),
}

_OPTION_HINTS: dict[str, OptionSpec] = {
    "epsilon": OptionSpec("epsilon", "float", 0.01, doc="Offset added before taking logs.", minimum=0.0),
    "power": OptionSpec("power", "float", 1.0, minimum=0.0, doc="Exponent on observed flow."),
    "top_fraction": OptionSpec("top_fraction", "float", 0.15, minimum=0.01, maximum=1.0,
                               doc="Fraction of events, by observed peak, in the slope."),
}

_SKIP = frozenset({"mask"})


def _first_line(obj: Any) -> str:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    return doc.splitlines()[0] if doc else ""


def _registry():
    from sparsehydro.metrics.objectives import objective_registry

    return objective_registry


class ObjectiveCatalog:
    def __init__(self) -> None:
        from .extensions import load_extensions

        load_extensions()  # installed extensions register their objectives first
        self.refresh()

    def refresh(self) -> None:
        """(Re)read the registry, e.g. after extensions were loaded."""
        self._entries: dict[str, ObjectiveEntry] = {}
        self._unavailable: dict[str, list[str]] = {}
        reg = _registry()
        for name in reg.names():
            cls = reg.get(name)
            hints = {k: v for k, v in _OPTION_HINTS.items()}
            options, required = signature_options(cls, _SKIP, hints)
            if required:
                self._unavailable[name] = required
                continue
            label, desc = _LABELS.get(name, (name.replace("_", " "), _first_line(cls)))
            self._entries[name] = ObjectiveEntry(
                name, label, bool(getattr(cls, "minimize", True)), desc, options,
                lambda o, n=name: reg.create(n, **o))

    def get(self, name: str) -> ObjectiveEntry:
        try:
            return self._entries[name]
        except KeyError:
            if name in self._unavailable:
                raise KeyError(f"Objective {name!r} needs {self._unavailable[name]}, which the viewer "
                               "cannot supply yet") from None
            raise KeyError(f"Unknown objective {name!r}; known: {list(self._entries)}") from None

    def entries(self) -> list[ObjectiveEntry]:
        return list(self._entries.values())

    def unavailable(self) -> dict[str, list[str]]:
        """Registered objectives hidden because they need data arrays: ``{name: [parameters]}``."""
        return dict(self._unavailable)

    def build(self, spec: ObjectiveSpec) -> Any:
        entry = self.get(spec.name)
        return entry.factory(resolve_options(entry.options, spec.options))

    def label(self, name: str) -> str:
        if name in self._entries:
            return self._entries[name].label
        return _LABELS.get(name, (name,))[0]


OBJECTIVES = ObjectiveCatalog()

DEFAULT_OBJECTIVES: tuple[ObjectiveSpec, ...] = (ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias"))

__all__ = ["DEFAULT_OBJECTIVES", "OBJECTIVES", "ObjectiveCatalog", "ObjectiveEntry", "ObjectiveSpec"]
