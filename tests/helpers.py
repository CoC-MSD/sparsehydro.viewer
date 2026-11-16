"""Test helpers."""

from __future__ import annotations

from typing import Any

from sparsehydro_viewer.core.catalog import ModelSpec, ParameterState


def spec_for(kind: str, options: dict[str, Any] | None = None,
             parameters: dict[str, ParameterState] | None = None, label: str = "") -> ModelSpec:
    """Model spec from the first project format's ``kind``/``options`` (converted to a component tree).

    ``"abstraction-uh"`` -> excess-uh (default peak-tail UH), ``"rdii"`` -> RDII with ``n_triangles``
    RTK triangles, a UH key -> that UH applied directly to rain.
    """
    spec = ModelSpec.from_dict({"kind": kind, "options": options or {}, "label": label})
    spec.parameters = dict(parameters or {})
    return spec
