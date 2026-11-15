"""Composable model components.

A model is a tree of :class:`ComponentSpec` nodes, not a preset.  Each node
has a component *type* (from :data:`COMPONENTS`), constructor options and
*slots* holding child nodes.  Types play one of three roles:

``flow``
    produces a flow series and can be the root or a term of a sum:
    ``sum`` (adds terms), ``rdii`` (abstraction + any number of unit
    hydrographs over a contributing area), ``excess-uh`` (abstraction + one
    unit hydrograph), ``sanitary`` (hour/day/month pattern) and every unit
    hydrograph used directly on rainfall.
``abstraction``
    turns rainfall into excess: initial abstraction or a drained tank.
``uh``
    a unit hydrograph shape.

For example "sanitary pattern + initial abstraction routed through a gamma
and two RTK triangles" is::

    sum
      terms: sanitary
             rdii  abstraction: initial-abstraction
                   uhs: gamma-uh, rtk-triangle, rtk-triangle

:func:`build` turns a tree into a sparsehydro model with today's library
classes (``EnsembleModel``, ``RDIIModel``, ``AbstractionUHModel``, ...).  The
tree is deliberately shaped like the ``CompositeModel`` configuration planned
for sparsehydro, so that ``build`` can later delegate to
``sparsehydro.configuration.build_model``.
"""

from __future__ import annotations

import copy
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .options import OptionSpec, resolve_options

ROLES = ("flow", "abstraction", "uh")


# ---------------------------------------------------------------------------
# Spec (serialisable)
# ---------------------------------------------------------------------------


@dataclass
class ComponentSpec:
    """One node of a model tree.

    :ivar type: Key in :data:`COMPONENTS`.
    :ivar options: Constructor options.
    :ivar slots: Child nodes by slot name; list-valued for multi slots.
    :ivar alias: Parameter prefix when the node is a term of a ``sum``.
    """

    type: str
    options: dict[str, Any] = field(default_factory=dict)
    slots: dict[str, Any] = field(default_factory=dict)
    alias: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.options:
            out["options"] = dict(self.options)
        if self.alias:
            out["alias"] = self.alias
        if self.slots:
            out["slots"] = {k: ([c.to_dict() for c in v] if isinstance(v, list) else v.to_dict())
                            for k, v in self.slots.items() if v is not None}
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentSpec:
        slots = {k: ([cls.from_dict(c) for c in v] if isinstance(v, list) else cls.from_dict(v))
                 for k, v in d.get("slots", {}).items()}
        return cls(d["type"], dict(d.get("options", {})), slots, d.get("alias", ""))

    def copy(self) -> ComponentSpec:
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# Component types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotSpec:
    """A place for child components.

    :ivar accepts: Roles a child may have.
    :ivar multiple: List slot (``True``) or single child.
    :ivar minimum: Minimum number of children.
    :ivar default: Component type created when a child is added.
    """

    name: str
    label: str
    accepts: tuple[str, ...]
    multiple: bool = False
    minimum: int = 1
    default: str = ""


@dataclass(frozen=True)
class ComponentType:
    """How to build one kind of component.

    ``build(options, children)`` receives built children (``(model,
    output_key)`` for flow children; models for the rest) and returns the
    sparsehydro model.  ``output_key(options)`` names the output compared
    with observed flow when the component is a flow.
    """

    key: str
    label: str
    role: str
    description: str
    options: tuple[OptionSpec, ...] = ()
    slots: tuple[SlotSpec, ...] = ()
    build: Callable[[dict[str, Any], dict[str, Any]], Any] = lambda o, c: None
    output_key: Callable[[dict[str, Any]], str] = lambda o: "Q_pred"
    also_flow: bool = False  # a uh that may also be used directly as a flow component

    def slot(self, name: str) -> SlotSpec:
        return next(s for s in self.slots if s.name == name)


def _uh_classes() -> dict[str, tuple[str, Any, str]]:
    from sparsehydro.models import unithydrograph as U
    from sparsehydro.models.rdii.rtk_triangle import RTKTriangle

    return {
        "gamma-uh": ("Gamma UH", U.GammaUH, "Two-parameter gamma shape (tt, tp in steps)."),
        "nash-uh": ("Nash cascade UH", U.NashUH, "n linear reservoirs with storage constant k (steps)."),
        "triangle-uh": ("Triangle UH", U.TriangleUH, "Linear rise to tp, linear fall to tt (steps)."),
        "rectangle-uh": ("Rectangle UH", U.RectangleUH, "Uniform pulse of duration tr (steps)."),
        "decay-uh": ("Exponential decay UH", U.DecayUH, "Single linear reservoir, alpha^t."),
        "gamma-delay-uh": ("Delayed gamma UH", U.GammaDelayUH, "Gamma shape shifted by td (steps)."),
        "peak-tail-uh": ("Peak + tail UH", U.PeakTailUH, "Triangle peak mixed with a gamma tail (weight w)."),
        "rtk-triangle": ("RTK triangle", RTKTriangle, "SWMM RTK triangle: fraction R, time to peak T [h], "
                                                      "recession ratio K."),
    }


UH_KEYS: tuple[str, ...] = (
    "gamma-uh", "nash-uh", "triangle-uh", "rectangle-uh", "decay-uh", "gamma-delay-uh", "peak-tail-uh",
    "rtk-triangle",
)
ABSTRACTION_KEYS: tuple[str, ...] = ("initial-abstraction", "tank-constant", "tank-linear", "tank-sqrt")


def _build_uh(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    return lambda _o, _c: _uh_classes()[key][1]()


def _build_ia(o: dict[str, Any], _c: dict[str, Any]) -> Any:
    from sparsehydro.models.rdii.initial_abstraction import IAModel

    return IAModel(snow=bool(o["snow"]))


def _build_tank(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    def build(o: dict[str, Any], _c: dict[str, Any]) -> Any:
        from sparsehydro.registry import registry

        return registry.create(key, n_substeps=int(o["n_substeps"]))

    return build


def _build_rdii(_o: dict[str, Any], c: dict[str, Any]) -> Any:
    from sparsehydro.models.rdii.model import RDIIModel

    return RDIIModel(ia_model=c["abstraction"], uh_components=list(c["uhs"]))


def _build_excess_uh(_o: dict[str, Any], c: dict[str, Any]) -> Any:
    from sparsehydro.models import AbstractionUHModel

    return AbstractionUHModel(abstraction=c["abstraction"], uh=c["uh"])


def _build_sanitary(o: dict[str, Any], _c: dict[str, Any]) -> Any:
    from sparsehydro.models import SeasonalityModel

    return SeasonalityModel(include_hour=o["hour"], include_dow=o["day_of_week"], include_month=o["month"],
                            output_name="sanitary_flow")


def _build_sum(_o: dict[str, Any], c: dict[str, Any]) -> Any:
    from sparsehydro.models import EnsembleModel

    terms = c["terms"]
    # itemgetter, unlike a lambda, pickles: NSGA-II with parallel workers copies the model.
    return EnsembleModel([(m, operator.itemgetter(key)) for m, key, _alias in terms],
                         aliases=[alias for _m, _k, alias in terms], output_name="total_flow",
                         normalize_weights=False)


def _types() -> dict[str, ComponentType]:
    out: dict[str, ComponentType] = {}
    for key, (label, _cls, doc) in _uh_classes().items():
        out[key] = ComponentType(key, label, "uh", doc, build=_build_uh(key), also_flow=True)
    out["initial-abstraction"] = ComponentType(
        "initial-abstraction", "Initial abstraction", "abstraction",
        "Temperature-dependent initial abstraction with recovery and depletion.",
        options=(OptionSpec("snow", "bool", False, label="Degree-day snow",
                            doc="Store precipitation as snow below a threshold temperature (needs temperature_c)."),),
        build=_build_ia)
    for key, label in (("tank-constant", "Tank, constant drain"), ("tank-linear", "Tank, linear drain"),
                       ("tank-sqrt", "Tank, square-root drain")):
        out[key] = ComponentType(
            key, label, "abstraction", "Abstraction store that fills with rain and drains between storms.",
            options=(OptionSpec("n_substeps", "int", 5, label="Sub-steps", minimum=1, maximum=100),),
            build=_build_tank(key))
    out["rdii"] = ComponentType(
        "rdii", "RDII (abstraction + UHs)", "flow",
        "Rainfall excess from an abstraction, split by fractions R_i over any number of unit hydrographs, "
        "times a contributing area (flow in cfs).",
        slots=(SlotSpec("abstraction", "Abstraction", ("abstraction",), default="initial-abstraction"),
               SlotSpec("uhs", "Unit hydrographs", ("uh",), multiple=True, minimum=1, default="rtk-triangle")),
        build=_build_rdii, output_key=lambda o: "rdii_cfs")
    out["excess-uh"] = ComponentType(
        "excess-uh", "Excess → UH", "flow",
        "Rainfall excess from an abstraction routed through one unit hydrograph with amplitude A.",
        slots=(SlotSpec("abstraction", "Abstraction", ("abstraction",), default="initial-abstraction"),
               SlotSpec("uh", "Unit hydrograph", ("uh",), default="gamma-uh")),
        build=_build_excess_uh, output_key=lambda o: "Q_pred")
    out["sanitary"] = ComponentType(
        "sanitary", "Sanitary pattern", "flow",
        "Dry-weather flow: baseline times hour-of-day, day-of-week and month factors.",
        options=(OptionSpec("hour", "bool", True, label="Hour of day"),
                 OptionSpec("day_of_week", "bool", True, label="Day of week"),
                 OptionSpec("month", "bool", True, label="Month")),
        build=_build_sanitary, output_key=lambda o: "sanitary_flow")
    out["sum"] = ComponentType(
        "sum", "Sum of terms", "flow",
        "Adds the flows of its terms (each scaled by a weight w_i, fixed at 1 by default).",
        slots=(SlotSpec("terms", "Terms", ("flow",), multiple=True, minimum=1, default="rdii"),),
        build=_build_sum, output_key=lambda o: "total_flow")
    return out


COMPONENTS: dict[str, ComponentType] = _types()


def types_for(roles: tuple[str, ...]) -> list[ComponentType]:
    """Component types allowed in a slot accepting *roles* (UHs also qualify as flows)."""
    return [t for t in COMPONENTS.values()
            if t.role in roles or ("flow" in roles and t.also_flow)]


def is_flow(spec: ComponentSpec) -> bool:
    t = COMPONENTS[spec.type]
    return t.role == "flow" or t.also_flow


# ---------------------------------------------------------------------------
# Creating and editing trees
# ---------------------------------------------------------------------------


def new_component(type_key: str) -> ComponentSpec:
    """A node of *type_key* with default options and default children."""
    t = COMPONENTS[type_key]
    spec = ComponentSpec(type_key, resolve_options(t.options, {}))
    for s in t.slots:
        if s.multiple:
            spec.slots[s.name] = [new_component(s.default) for _ in range(s.minimum)]
        else:
            spec.slots[s.name] = new_component(s.default)
    return spec


def change_type(spec: ComponentSpec, type_key: str) -> ComponentSpec:
    """Replace a node's type, keeping children whose slot names and roles still fit."""
    new = new_component(type_key)
    new.alias = spec.alias
    t = COMPONENTS[type_key]
    for s in t.slots:
        old = spec.slots.get(s.name)
        if old is None:
            continue
        kids = old if isinstance(old, list) else [old]
        ok = [k for k in kids if k.type in {c.key for c in types_for(s.accepts)}]
        if s.multiple and len(ok) >= s.minimum:
            new.slots[s.name] = ok
        elif not s.multiple and ok:
            new.slots[s.name] = ok[0]
    for o in t.options:
        if o.name in spec.options:
            try:
                new.options[o.name] = o.coerce(spec.options[o.name])
            except ValueError:
                pass
    return new


def default_tree() -> ComponentSpec:
    """Starting point for a new project: one RDII term inside a sum, ready for more terms."""
    root = new_component("sum")
    root.slots["terms"][0].slots["uhs"] = [new_component("rtk-triangle"), new_component("gamma-uh")]
    assign_aliases(root)
    return root


def assign_aliases(root: ComponentSpec) -> None:
    """Give every term of every sum a unique, short alias (kept if already set and unique)."""
    def walk(node: ComponentSpec) -> None:
        if node.type == "sum":
            used: set[str] = set()
            for term in node.slots.get("terms", []):
                base = term.alias or _ALIAS_BASE.get(term.type, term.type.split("-")[0])
                alias, i = base, 2
                while alias in used:
                    alias, i = f"{base}{i}", i + 1
                term.alias = alias
                used.add(alias)
        for v in node.slots.values():
            for c in (v if isinstance(v, list) else [v]):
                walk(c)

    walk(root)


_ALIAS_BASE = {"rdii": "wet", "excess-uh": "wet", "sanitary": "san", "sum": "sum"}


def describe(spec: ComponentSpec) -> str:
    """Compact one-line description, e.g. ``sanitary + RDII(IA; RTK, gamma)``."""
    t = COMPONENTS[spec.type]
    if spec.type == "sum":
        return " + ".join(describe(c) for c in spec.slots.get("terms", []))
    if spec.type == "rdii":
        uhs = ", ".join(_short(c.type) for c in spec.slots.get("uhs", []))
        return f"RDII({_short(spec.slots['abstraction'].type)}; {uhs})"
    if spec.type == "excess-uh":
        return f"{_short(spec.slots['abstraction'].type)} → {_short(spec.slots['uh'].type)}"
    if spec.type == "sanitary":
        return "sanitary"
    return t.label


def _short(key: str) -> str:
    return {"initial-abstraction": "IA", "tank-constant": "tank", "tank-linear": "tank(lin)",
            "tank-sqrt": "tank(sqrt)", "rtk-triangle": "RTK", "gamma-uh": "gamma", "nash-uh": "Nash",
            "triangle-uh": "triangle", "rectangle-uh": "rectangle", "decay-uh": "decay",
            "gamma-delay-uh": "delayed gamma", "peak-tail-uh": "peak+tail"}.get(key, key)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


@dataclass
class Built:
    """Result of :func:`build`.

    :ivar model: Uninitialised sparsehydro model.
    :ivar output_key: Output field compared with observed flow.
    :ivar defaults: ``(flat name, value, calibrate)`` adjustments applied after
        ``initialize()`` (``None`` keeps the library's choice).
    :ivar groups: ``(flat-name prefix, group label)`` used to group
        parameters in the UI; matched longest prefix first.
    :ivar uh_paths: For each unit hydrograph: ``(label, child model, flat
        prefix of its parameters, flat name of its amplitude or None)``.
    :ivar abstractions: ``(flat prefix, child model, group label)`` for each
        abstraction; their parameter names are known only after the root
        model is initialised (see :meth:`parameter_groups`).
    """

    model: Any
    output_key: str
    defaults: list[tuple[str, float | None, bool | None]] = field(default_factory=list)
    groups: list[tuple[str, str]] = field(default_factory=list)
    uh_paths: list[tuple[str, Any, str, str | None]] = field(default_factory=list)
    abstractions: list[tuple[str, Any, str]] = field(default_factory=list)

    def parameter_groups(self, names: list[str]) -> dict[str, str]:
        """Group label for every flat parameter name (call after ``initialize()``)."""
        exact = {f"{prefix}{n}": label for prefix, child, label in self.abstractions
                 for n in list(child.scalar_parameter_names) + list(child.vector_parameter_names)}
        out = {}
        for name in names:
            base = name.split("[", 1)[0]
            if base in exact:
                out[name] = exact[base]
                continue
            best, label = -1, "Model"
            for prefix, lbl in self.groups:
                if base.startswith(prefix) and len(prefix) > best:
                    best, label = len(prefix), lbl
            out[name] = label
        return out


def build(spec: ComponentSpec, *, _prefix: str = "", _label: str = "") -> Built:
    """Build a sparsehydro model from a component tree."""
    t = COMPONENTS[spec.type]
    opts = resolve_options(t.options, spec.options)
    label = f"{_label} ({t.label})" if _label and (t.role == "uh" or spec.type == "sanitary") else (_label or t.label)

    if t.role == "uh":
        model = t.build(opts, {})
        amp = type(model)._amplitude_param_name
        return Built(model, "Q_pred", groups=[(_prefix, label)],
                     uh_paths=[(label, model, _prefix, f"{_prefix}{amp}" if amp else None)])
    if t.role == "abstraction":
        return Built(t.build(opts, {}), "", groups=[(_prefix, label)])

    if spec.type == "sum":
        terms = spec.slots["terms"]
        built_terms, out = [], Built(None, t.output_key(opts))
        for i, term in enumerate(terms, start=1):
            alias = term.alias or f"t{i}"
            path = f"{_label} › {alias}" if _label else alias
            child = build(term, _prefix=f"{_prefix}{alias}_", _label=path)
            built_terms.append((child.model, child.output_key, alias))
            # Terms add: weights start at 1 and fixed; users can free them in the parameter panel.
            out.defaults.append((f"{_prefix}w_{i}", 1.0, False))
            out.defaults += child.defaults
            out.groups += child.groups
            # The term's weight joins the term's own group (e.g. "san (Sanitary pattern)") when it has one.
            own = next((lbl for p, lbl in child.groups if p == f"{_prefix}{alias}_"), path)
            out.groups.append((f"{_prefix}w_{i}", own))
            out.uh_paths += child.uh_paths
            out.abstractions += child.abstractions
        out.model = t.build(opts, {"terms": built_terms})
        return out

    if spec.type == "rdii":
        abstraction = build(spec.slots["abstraction"])
        uhs = [build(u) for u in spec.slots["uhs"]]
        n = len(uhs)
        model = t.build(opts, {"abstraction": abstraction.model, "uhs": [u.model for u in uhs]})
        out = Built(model, t.output_key(opts), groups=[(f"{_prefix}area_acres", label)])
        # RDIIModel keeps abstraction parameter names unprefixed (within its own prefix).
        out.abstractions.append((_prefix, abstraction.model,
                                 f"{label} › {COMPONENTS[spec.slots['abstraction'].type].label}"))
        for i, (u_spec, u) in enumerate(zip(spec.slots["uhs"], uhs), start=1):
            u_label = f"{label} › UH {i}: {COMPONENTS[u_spec.type].label}"
            out.groups += [(f"{_prefix}uh{i}_", u_label), (f"{_prefix}R_{i}", u_label)]
            amp = type(u.model)._amplitude_param_name
            out.uh_paths.append((u_label, u.model, f"{_prefix}uh{i}_", f"{_prefix}R_{i}" if amp else None))
            # The library seeds R_i from the UH's own amplitude, which for A-type UHs (A=100) breaks the
            # R_i <= 1 bound; start every component with an equal share instead.
            out.defaults.append((f"{_prefix}R_{i}", round(1.0 / n, 6) if amp != "R" else None, None))
        return out

    if spec.type == "excess-uh":
        abstraction = build(spec.slots["abstraction"])
        uh = build(spec.slots["uh"])
        model = t.build(opts, {"abstraction": abstraction.model, "uh": uh.model})
        u_label = f"{label} › {COMPONENTS[spec.slots['uh'].type].label}"
        out = Built(model, t.output_key(opts), groups=[(f"{_prefix}uh_", u_label)])
        out.abstractions.append((_prefix, abstraction.model,
                                 f"{label} › {COMPONENTS[spec.slots['abstraction'].type].label}"))
        out.uh_paths.append((u_label, uh.model, f"{_prefix}uh_", None))
        return out

    # leaf flow components (sanitary)
    return Built(t.build(opts, {}), t.output_key(opts), groups=[(_prefix, label)])


__all__ = [
    "ABSTRACTION_KEYS",
    "COMPONENTS",
    "ROLES",
    "UH_KEYS",
    "Built",
    "ComponentSpec",
    "ComponentType",
    "SlotSpec",
    "assign_aliases",
    "build",
    "change_type",
    "default_tree",
    "describe",
    "is_flow",
    "new_component",
    "types_for",
]
