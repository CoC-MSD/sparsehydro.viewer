"""Objective catalog: sparsehydro objectives the viewer can configure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .options import OptionSpec, resolve_options


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


def _entries() -> list[ObjectiveEntry]:
    from sparsehydro.calibration import objectives as O

    def simple(cls: type) -> Callable[[dict[str, Any]], Any]:
        return lambda _o: cls()

    return [
        ObjectiveEntry("nash_sutcliffe", "NSE", False, "Nash-Sutcliffe efficiency (1 is perfect).", (), simple(O.NashSutcliffe)),
        ObjectiveEntry("kge", "KGE", False, "Kling-Gupta efficiency (1 is perfect).", (), simple(O.KGE)),
        ObjectiveEntry("ccc", "Lin's CCC", False, "Concordance correlation coefficient.", (),
                       simple(O.ConcordanceCorrelationCoefficient)),
        ObjectiveEntry("log_nse", "log NSE", False, "NSE of log flows; emphasises recessions.",
                       (OptionSpec("epsilon", "float", 0.01, doc="Offset added before taking logs.", minimum=0.0),),
                       lambda o: O.LogNSE(epsilon=o["epsilon"])),
        ObjectiveEntry("index_of_agreement", "Index of agreement", False, "Willmott's d.", (),
                       simple(O.IndexOfAgreement)),
        ObjectiveEntry("rmse", "RMSE", True, "Root mean square error (flow units).", (), simple(O.RMSE)),
        ObjectiveEntry("mae", "MAE", True, "Mean absolute error (flow units).", (), simple(O.MAE)),
        ObjectiveEntry("mse", "MSE", True, "Mean square error.", (), simple(O.MSE)),
        ObjectiveEntry("peak_weighted_mse", "Peak-weighted MSE", True, "MSE weighted by observed flow^power.",
                       (OptionSpec("power", "float", 1.0, minimum=0.0, doc="Exponent on observed flow."),),
                       lambda o: O.PeakWeightedMSE(power=o["power"])),
        ObjectiveEntry("pbias", "PBIAS", True, "Absolute percent bias in volume.", (), simple(O.PBIAS)),
        ObjectiveEntry("volume_relative_error", "Volume error", True, "Relative volume error.", (),
                       simple(O.VolumeRelativeError)),
    ]


class ObjectiveCatalog:
    def __init__(self) -> None:
        self._entries = {e.name: e for e in _entries()}

    def get(self, name: str) -> ObjectiveEntry:
        try:
            return self._entries[name]
        except KeyError:
            raise KeyError(f"Unknown objective {name!r}; known: {list(self._entries)}") from None

    def entries(self) -> list[ObjectiveEntry]:
        return list(self._entries.values())

    def build(self, spec: ObjectiveSpec) -> Any:
        entry = self.get(spec.name)
        return entry.factory(resolve_options(entry.options, spec.options))

    def label(self, name: str) -> str:
        return self._entries[name].label if name in self._entries else name


OBJECTIVES = ObjectiveCatalog()

DEFAULT_OBJECTIVES: tuple[ObjectiveSpec, ...] = (ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias"))

__all__ = ["DEFAULT_OBJECTIVES", "OBJECTIVES", "ObjectiveCatalog", "ObjectiveEntry", "ObjectiveSpec"]
