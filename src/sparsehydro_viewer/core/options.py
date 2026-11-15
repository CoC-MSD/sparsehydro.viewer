"""Declarative option descriptors used to generate configuration forms.

An :class:`OptionSpec` describes one constructor option of a model, objective
or solver.  Views turn a sequence of them into a form; the catalogs turn the
form's ``dict`` back into objects.  :func:`signature_options` derives them
from the constructors registered in sparsehydro's registries, so new library
objectives, solvers and components appear without viewer changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OptionKind = Literal["float", "int", "bool", "choice", "str"]


@dataclass(frozen=True)
class OptionSpec:
    """One configurable option.

    :ivar name: Keyword passed to the constructor.
    :ivar kind: Value type, which selects the editor widget.
    :ivar default: Default value.
    :ivar label: Human-readable label (defaults to ``name``).
    :ivar doc: Tooltip text.
    :ivar choices: Allowed values for ``kind == "choice"``.
    :ivar minimum: Lower limit for numeric kinds.
    :ivar maximum: Upper limit for numeric kinds.
    """

    name: str
    kind: OptionKind
    default: Any
    label: str = ""
    doc: str = ""
    choices: tuple[Any, ...] = field(default_factory=tuple)
    minimum: float | None = None
    maximum: float | None = None

    @property
    def display_label(self) -> str:
        return self.label or self.name.replace("_", " ")

    def coerce(self, value: Any) -> Any:
        """Convert *value* to this option's type, falling back to the default.

        :param value: Raw value (for example from JSON).
        :returns: Value of the declared kind.
        :raises ValueError: If a ``choice`` value is not allowed.
        """
        if value is None:
            return self.default
        if self.kind == "float":
            return float(value)
        if self.kind == "int":
            return int(value)
        if self.kind == "bool":
            return bool(value)
        if self.kind == "choice":
            if value not in self.choices:
                raise ValueError(f"{self.name}: {value!r} not in {self.choices}")
            return value
        return str(value)


def signature_options(factory: Any, skip: set[str] | frozenset[str] = frozenset(),
                      overrides: dict[str, OptionSpec] | None = None) -> tuple[tuple[OptionSpec, ...], list[str]]:
    """Option descriptors read from a constructor's signature.

    Keyword parameters with a scalar default (``bool``, ``int``, ``float``,
    ``str``) become options; *overrides* replaces a generated descriptor (to
    add a label, limits or choices).

    :param factory: Class or callable registered in a sparsehydro registry.
    :param skip: Parameter names the caller supplies itself (e.g. ``mask``).
    :returns: ``(options, required)`` where *required* lists parameters without
        a default that are not in *skip*: the factory cannot be built from
        options alone.
    """
    import inspect

    overrides = overrides or {}
    target = factory.__init__ if isinstance(factory, type) else factory
    try:
        params = list(inspect.signature(target).parameters.values())
    except (TypeError, ValueError):
        return tuple(overrides.values()), []
    opts: list[OptionSpec] = []
    required: list[str] = []
    for p in params:
        if p.name in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) or p.name in skip:
            continue
        if p.name in overrides:
            opts.append(overrides[p.name])
            continue
        d = p.default
        if d is inspect.Parameter.empty:
            required.append(p.name)
        elif isinstance(d, bool):
            opts.append(OptionSpec(p.name, "bool", d))
        elif isinstance(d, int):
            opts.append(OptionSpec(p.name, "int", d))
        elif isinstance(d, float):
            opts.append(OptionSpec(p.name, "float", d))
        elif isinstance(d, str):
            opts.append(OptionSpec(p.name, "str", d))
    return tuple(opts), required


def resolve_options(specs: tuple[OptionSpec, ...] | list[OptionSpec], values: dict[str, Any] | None) -> dict[str, Any]:
    """Merge user values over defaults and coerce types.

    Unknown keys in *values* are ignored so that older project files keep
    loading after an option is removed.

    :param specs: Option descriptors.
    :param values: User-supplied values.
    :returns: Complete option dictionary.
    """
    values = values or {}
    return {s.name: s.coerce(values.get(s.name, s.default)) for s in specs}
