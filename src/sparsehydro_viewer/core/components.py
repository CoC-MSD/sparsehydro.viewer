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


#: Labels and one-line descriptions for the unit hydrographs the viewer knows; others registered in
#: sparsehydro appear with their class docstring. All times are in hours.
_UH_LABELS: dict[str, tuple[str, str, str]] = {
    "rtk-triangle": ("RTK triangle", "RTK", "SWMM RTK triangle: fraction R, time to peak T [h], recession ratio K."),
    "gamma-uh": ("Gamma UH", "gamma", "Gamma distribution: shape alpha, scale theta [h]."),
    "nash-uh": ("Nash cascade UH", "Nash", "n linear reservoirs with storage constant K [h]."),
    "triangle-uh": ("Triangle UH", "triangle", "Linear rise to Tp, linear fall to Tb [h]."),
    "rectangle-uh": ("Rectangle UH", "rectangle", "Uniform pulse of duration Tr [h]."),
    "decay-uh": ("Exponential decay UH", "decay", "Single linear reservoir with time constant K [h]."),
    "gamma-delay-uh": ("Delayed gamma UH", "delayed gamma", "Gamma shape shifted by a delay td [h]."),
    "peak-tail-uh": ("Peak + tail UH", "peak+tail", "Triangle peak blended with a gamma tail (tail fraction w)."),
    "mixture-uh": ("Mixture UH", "mixture", "Weighted blend of two gamma shapes (fast and slow)."),
    "clark-uh": ("Clark UH", "Clark", "Clark: time of concentration Tc and storage Rs [h]."),
    "modclark-uh": ("ModClark UH", "ModClark", "Modified Clark with a distributed travel-time area curve."),
    "scs-uh": ("SCS UH", "SCS", "NRCS dimensionless UH: time to peak Tp [h], peak rate factor PRF."),
    "snyder-uh": ("Snyder UH", "Snyder", "Snyder synthetic UH: lag tL [h], peaking coefficient Cp."),
    "weibull-uh": ("Weibull UH", "Weibull", "Weibull distribution: shape k, scale lam [h]."),
    "lognormal-uh": ("Lognormal UH", "lognormal", "Lognormal distribution: mu [ln h], sigma."),
    "gengamma-uh": ("Generalised gamma UH", "gen. gamma", "Generalised gamma: shapes a, c, scale [h]."),
}


def _uh_classes() -> dict[str, tuple[str, Any, str]]:
    """Unit hydrographs registered in sparsehydro (RTK triangle first, the viewer's known ones next)."""
    from sparsehydro.models.base import IUnitHydroComponent
    from sparsehydro.registry import registry

    out: dict[str, tuple[str, Any, str]] = {}
    found = [n for n in registry.names()
             if isinstance(registry.get(n), type) and issubclass(registry.get(n), IUnitHydroComponent)]
    for key in [k for k in _UH_LABELS if k in found] + sorted(k for k in found if k not in _UH_LABELS):
        cls = registry.get(key)
        label, _short_name, doc = _UH_LABELS.get(key, (key.replace("-", " "), key, _first_line(cls)))
        out[key] = (label, cls, doc)
    return out


def _first_line(obj: Any) -> str:
    doc = (getattr(obj, "__doc__", None) or "").strip()
    return doc.splitlines()[0] if doc else ""


#: Labels for the abstractions (losses) the viewer knows; others registered in sparsehydro are discovered.
_ABSTRACTION_LABELS: dict[str, tuple[str, str]] = {
    "initial-abstraction": ("Initial abstraction",
                            "Temperature-dependent initial abstraction with recovery and depletion."),
    "tank-constant": ("Tank, constant drain", "Abstraction store that fills with rain and drains between storms."),
    "tank-linear": ("Tank, linear drain", "Abstraction store whose drain rate grows with its content."),
    "tank-sqrt": ("Tank, square-root drain", "Abstraction store draining with the square root of its content."),
}

#: Constructor switches with nicer labels; other bool/int/str switches are generated from signatures.
_OPTION_HINTS: dict[str, OptionSpec] = {
    "snow": OptionSpec("snow", "bool", False, label="Degree-day snow",
                       doc="Store precipitation as snow below a threshold temperature (needs temperature_c)."),
    "n_substeps": OptionSpec("n_substeps", "int", 5, label="Sub-steps", minimum=1, maximum=100),
}
#: Constructor arguments that are wiring or units, not modelling choices.
_NOT_OPTIONS = frozenset({"units", "output_name", "source_column"})


def structural_options(cls: Any) -> tuple[OptionSpec, ...]:
    """Modelling switches of a registered class: its bool/int/str keyword arguments.

    Float arguments are starting values of parameters the user edits with the sliders, so they are not
    repeated as options; units, column names and output names are wiring the viewer sets itself.
    """
    from .options import signature_options

    opts, _required = signature_options(cls, _NOT_OPTIONS, _OPTION_HINTS)
    return tuple(o for o in opts if o.kind != "float" and not o.name.endswith("_col"))


def _probe(cls: Any) -> Any | None:
    """An initialised default instance, or ``None`` when the class cannot be built without arguments."""
    try:
        m = cls()
        m.initialize()
        return m
    except Exception:  # noqa: BLE001 - classes that need configuration are simply not offered
        return None


def _abstraction_classes() -> dict[str, tuple[str, Any, str]]:
    """Registered models that turn rainfall into excess on their own (no bound inputs, ``p_excess_in`` out)."""
    from sparsehydro.models.base import IUnitHydroComponent
    from sparsehydro.models.composite import CompositeModel
    from sparsehydro.registry import registry

    found = []
    for name in registry.names():
        cls = registry.get(name)
        if not isinstance(cls, type) or issubclass(cls, (IUnitHydroComponent, CompositeModel)):
            continue
        m = _probe(cls)
        primary = next((f for f in (m.output_field_names if m is not None else []) if f != "datetime"), None)
        if m is not None and not m.input_field_names and primary == "p_excess_in":
            found.append(name)
    out: dict[str, tuple[str, Any, str]] = {}
    for key in [k for k in _ABSTRACTION_LABELS if k in found] + sorted(k for k in found if k not in _ABSTRACTION_LABELS):
        label, doc = _ABSTRACTION_LABELS.get(key, (key.replace("-", " "), _first_line(registry.get(key))))
        out[key] = (label, registry.get(key), doc)
    return out


# Live lists: :func:`refresh` updates them in place when extensions add components.
UH_KEYS: list[str] = []
ABSTRACTION_KEYS: list[str] = []
#: Routing components that read rainfall *excess* (not ``rain``) and so need a losses process.
NEEDS_EXCESS: set[str] = set()

#: Starting (T [h], K) of the 1st, 2nd, 3rd... RTK triangle in an RDII component.
RTK_START: tuple[tuple[float, float], ...] = ((1.0, 1.5), (6.0, 2.0), (24.0, 3.0), (72.0, 3.0), (168.0, 3.0))


def _build_registered(key: str) -> Callable[[dict[str, Any], dict[str, Any]], Any]:
    def build(o: dict[str, Any], _c: dict[str, Any]) -> Any:
        from sparsehydro.registry import registry

        return registry.create(key, **o)

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
    UH_KEYS[:] = []
    NEEDS_EXCESS.clear()
    for key, (label, cls, doc) in _uh_classes().items():
        m = _probe(cls)
        # A UH that reads plain rain can also stand alone as a flow; one that reads excess (e.g. the RTK
        # triangle, which reads p_excess_mm) needs a losses process in front of it.
        reads_rain = m is not None and "rain" in m.input_field_names
        if m is None:
            continue
        UH_KEYS.append(key)
        if not reads_rain:
            NEEDS_EXCESS.add(key)
        out[key] = ComponentType(key, label, "uh", doc, options=structural_options(cls),
                                 build=_build_registered(key), also_flow=reads_rain)
    ABSTRACTION_KEYS[:] = []
    for key, (label, cls, doc) in _abstraction_classes().items():
        ABSTRACTION_KEYS.append(key)
        out[key] = ComponentType(key, label, "abstraction", doc, options=structural_options(cls),
                                 build=_build_registered(key))
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


COMPONENTS: dict[str, ComponentType] = {}


def refresh() -> None:
    """(Re)discover component types from sparsehydro's registry, e.g. after extensions were loaded."""
    types = _types()
    COMPONENTS.clear()
    COMPONENTS.update(types)


def _initial_discovery() -> None:
    from .extensions import load_extensions

    load_extensions()  # installed extension packages register before the first discovery
    refresh()


_initial_discovery()


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
    """Starting point for a new project: initial abstraction routed through one RTK triangle.

    This is the process builder's default design (:class:`~.processes.ProcessDesign`), so a new model
    can be grown from it one process at a time.
    """
    return new_component("rdii")


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
    if key in _UH_LABELS:
        return _UH_LABELS[key][1]
    return {"initial-abstraction": "IA", "tank-constant": "tank", "tank-linear": "tank(lin)",
            "tank-sqrt": "tank(sqrt)"}.get(key, key)


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
            # Successive RTK triangles start progressively slower (fast inflow -> slow infiltration), so adding
            # a triangle adds a distinct response instead of a copy of the first one.
            if u_spec.type == "rtk-triangle":
                k = sum(1 for s in spec.slots["uhs"][:i] if s.type == "rtk-triangle") - 1
                t, kk = RTK_START[min(k, len(RTK_START) - 1)]
                out.defaults += [(f"{_prefix}uh{i}_T", t, None), (f"{_prefix}uh{i}_K", kk, None)]
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
