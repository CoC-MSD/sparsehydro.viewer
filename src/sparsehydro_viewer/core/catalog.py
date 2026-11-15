"""Model specifications built from component trees.

A :class:`ModelSpec` is a component tree (:mod:`.components`) plus
per-parameter overrides.  :data:`CATALOG` builds it into an initialised
sparsehydro model, describes its parameters for the UI and prepares input
frames.  There are no preset models: every structure is a tree the user
assembles.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .components import (
    ABSTRACTION_KEYS,
    COMPONENTS,
    UH_KEYS,
    Built,
    ComponentSpec,
    build,
    default_tree,
    describe,
    new_component,
)

# ---------------------------------------------------------------------------
# Specs (serialisable)
# ---------------------------------------------------------------------------


@dataclass
class ParameterState:
    """User overrides for one parameter (scalar, or one vector element ``name[i]``).

    ``None`` keeps the model default.  For vector elements ``calibrate``
    applies to the whole vector.
    """

    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    calibrate: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ParameterState:
        return cls(**{k: d.get(k) for k in ("value", "lower", "upper", "calibrate")})


@dataclass
class ModelSpec:
    """A buildable, serialisable model: component tree + parameter overrides.

    :ivar root: Root of the component tree.
    :ivar parameters: Overrides by flat parameter name.
    :ivar label: Name chosen by the user (defaults to a description of the tree).
    """

    root: ComponentSpec = field(default_factory=default_tree)
    parameters: dict[str, ParameterState] = field(default_factory=dict)
    label: str = ""

    @property
    def display_label(self) -> str:
        return self.label or describe(self.root)

    @property
    def structure_key(self) -> str:
        """Identifies the structure (tree and options), independent of parameter values."""
        import json

        return json.dumps(self.root.to_dict(), sort_keys=True)

    def with_values(self, values: dict[str, float]) -> ModelSpec:
        """Copy whose parameter values are replaced by *values*."""
        spec = copy.deepcopy(self)
        for name, val in values.items():
            spec.parameters.setdefault(name, ParameterState()).value = float(val)
        return spec

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "root": self.root.to_dict(),
            "parameters": {k: v.to_dict() for k, v in self.parameters.items() if v.to_dict()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ModelSpec:
        root = ComponentSpec.from_dict(d["root"]) if "root" in d else _legacy_root(d)
        return cls(root=root,
                   parameters={k: ParameterState.from_dict(v) for k, v in d.get("parameters", {}).items()},
                   label=d.get("label", ""))

    @classmethod
    def of(cls, root: ComponentSpec, label: str = "") -> ModelSpec:
        return cls(root=root, label=label)


def _legacy_root(d: dict[str, Any]) -> ComponentSpec:
    """Convert the first project format (``kind`` + ``options`` presets) to a tree."""
    kind, opts = d.get("kind", ""), d.get("options", {})
    if kind == "abstraction-uh":
        root = new_component("excess-uh")
        root.slots["abstraction"] = new_component(opts.get("abstraction", "initial-abstraction"))
        root.slots["uh"] = new_component(opts.get("uh", "peak-tail-uh"))
        return root
    if kind == "rdii":
        root = new_component("rdii")
        root.slots["uhs"] = [new_component("rtk-triangle") for _ in range(int(opts.get("n_triangles", 3)))]
        return root
    if kind in COMPONENTS:
        return new_component(kind)
    raise ValueError(f"Unknown model description {d!r}")


@dataclass(frozen=True)
class ParameterInfo:
    """Read-only snapshot of one flat parameter for display.

    :ivar group: Component the parameter belongs to (for grouping in the UI).
    :ivar vector: Name of the vector parameter for elements ``name[i]``.
    """

    name: str
    value: float
    lower: float
    upper: float
    units: str
    description: str
    calibrate: bool
    default: float
    group: str = "Model"
    vector: str | None = None


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def flat_names(model: Any) -> list[str]:
    """Scalar names followed by vector elements ``name[i]``, in registration order."""
    names = list(model.scalar_parameter_names)
    for v in model.vector_parameter_names:
        names += [f"{v}[{i}]" for i in range(model.get_vector_parameter(v).size)]
    return names


def _split(name: str) -> tuple[str, int | None]:
    if name.endswith("]") and "[" in name:
        base, idx = name[:-1].split("[", 1)
        return base, int(idx)
    return name, None


class ModelCatalog:
    """Builds :class:`ModelSpec` trees into sparsehydro models."""

    # -- building ----------------------------------------------------------

    def build(self, spec: ModelSpec, *, strict: bool = True) -> Built:
        """Build, initialise, apply component defaults and user overrides.

        :param strict: Raise :class:`KeyError` for overrides naming unknown
            parameters (``False`` ignores them, e.g. after a structure edit).
        """
        built = build(spec.root)
        model = built.model
        model.initialize()
        for name, value, calibrate in built.defaults:
            if name in model.scalar_parameter_names:
                p = model.get_scalar_parameter(name)
                if calibrate is not None:
                    p.update(calibrate=calibrate)
                if value is not None:
                    model.apply_flat_parameter(name, value)
        known = set(flat_names(model))
        for name, state in spec.parameters.items():
            if name not in known:
                if strict:
                    raise KeyError(f"{spec.display_label}: no parameter {name!r}")
                continue
            self._apply_override(model, name, state)
        return built

    @staticmethod
    def _apply_override(model: Any, name: str, state: ParameterState) -> None:
        base, idx = _split(name)
        if idx is None:
            p = model.get_scalar_parameter(name)
            lower = p.lower_bound if state.lower is None else float(state.lower)
            upper = p.upper_bound if state.upper is None else float(state.upper)
            p.update(lower_bound=lower, upper_bound=upper)
            if state.calibrate is not None:
                p.update(calibrate=bool(state.calibrate))
        else:
            vp = model.get_vector_parameter(base)
            if state.lower is not None:
                vp.lower_bounds[idx] = float(state.lower)
            if state.upper is not None:
                vp.upper_bounds[idx] = float(state.upper)
            if state.calibrate is not None:
                vp.calibrate = bool(state.calibrate)
        if state.value is not None:
            model.apply_flat_parameter(name, float(state.value))

    def instantiate(self, spec: ModelSpec, *, strict: bool = True) -> Any:
        """Initialised (not prepared) sparsehydro model for *spec*."""
        return self.build(spec, strict=strict).model

    def prune(self, spec: ModelSpec) -> ModelSpec:
        """Copy of *spec* without overrides for parameters the structure no longer has."""
        model = self.instantiate(ModelSpec(spec.root))
        known = set(flat_names(model))
        out = copy.deepcopy(spec)
        out.parameters = {k: v for k, v in out.parameters.items() if k in known}
        return out

    # -- description ---------------------------------------------------------

    def defaults(self, spec: ModelSpec) -> dict[str, float]:
        """Values of a freshly built model with *spec*'s structure (no user overrides)."""
        model = self.instantiate(ModelSpec(spec.root))
        return {n: float(model.read_flat_parameter(n)) for n in flat_names(model)}

    def describe_parameters(self, spec: ModelSpec) -> list[ParameterInfo]:
        """Every flat parameter (vector elements included) with overrides applied."""
        defaults = self.defaults(spec)
        built = self.build(spec, strict=False)
        model = built.model
        names = flat_names(model)
        groups = built.parameter_groups(names)
        out = []
        for n in names:
            base, idx = _split(n)
            if idx is None:
                p = model.get_scalar_parameter(n)
                out.append(ParameterInfo(n, float(model.read_flat_parameter(n)), float(p.lower_bound),
                                         float(p.upper_bound), p.units or "", p.description or "",
                                         bool(p.calibrate), defaults.get(n, float(p.value)), groups[n]))
            else:
                vp = model.get_vector_parameter(base)
                out.append(ParameterInfo(n, float(vp.values[idx]), float(vp.lower_bounds[idx]),
                                         float(vp.upper_bounds[idx]), vp.units or "", vp.description or "",
                                         bool(vp.calibrate), defaults.get(n, float(vp.values[idx])), groups[n],
                                         vector=base))
        return out

    def predicted_key(self, spec: ModelSpec) -> str:
        return build(spec.root).output_key

    @staticmethod
    def prepare_frame(data: pd.DataFrame) -> pd.DataFrame:
        """Add the column names that different components read (``rain`` and ``rainfall_in``)."""
        if "rainfall_in" in data.columns:
            return data
        out = data.copy()
        out["rainfall_in"] = out["rain"]
        return out


def parameter_counts(model: Any) -> tuple[int, int]:
    """Return ``(total, calibrated)`` parameter counts including vector elements."""
    total = calibrated = 0
    for n in model.scalar_parameter_names:
        total += 1
        calibrated += bool(model.get_scalar_parameter(n).calibrate)
    for n in model.vector_parameter_names:
        vp = model.get_vector_parameter(n)
        total += vp.size
        calibrated += vp.size if vp.calibrate else 0
    return total, calibrated


def build_uh(key: str) -> Any:
    """Instantiate a unit hydrograph component by key."""
    return build(ComponentSpec(key)).model


def uh_label(key: str) -> str:
    return COMPONENTS[key].label


CATALOG = ModelCatalog()

__all__ = [
    "ABSTRACTION_KEYS",
    "CATALOG",
    "UH_KEYS",
    "ModelCatalog",
    "ModelSpec",
    "ParameterInfo",
    "ParameterState",
    "build_uh",
    "flat_names",
    "parameter_counts",
    "uh_label",
]
