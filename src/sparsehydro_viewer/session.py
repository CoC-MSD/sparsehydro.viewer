"""Application state shared by all views.

Views never call each other: they read and write the :class:`Session` and
react to its signals.  The session owns the project, the loaded dataset frame
(cached by dataset name), the working model with its current parameter
values, and the shared run/solution selection that links Explore and Compare.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QObject, Signal

from .core.catalog import CATALOG, ModelSpec, ParameterInfo
from .core.data import DatasetSpec, Period, load_dataset
from .core.objectives import ObjectiveSpec
from .core.project import Project
from .core.runs import RunRecord
from .core.solvers import SolverSpec


class Session(QObject):
    projectChanged = Signal()
    datasetChanged = Signal()
    periodsChanged = Signal()  # calibration/validation period of the current dataset
    modelChanged = Signal()
    modelRenamed = Signal()
    parametersEdited = Signal()  # bounds / calibrate flags changed (structure, not values)
    valuesChanged = Signal(dict)  # slider values
    objectivesChanged = Signal()
    runsChanged = Signal()
    runUpdated = Signal(str)
    selectionChanged = Signal(str, list)  # run id, solution indices
    dirtyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = Project()
        self._frames: dict[str, pd.DataFrame] = {}
        self.dataset_name: str | None = None
        self.model_spec: ModelSpec = ModelSpec()
        self.values: dict[str, float] = {}
        self.selected_run: str | None = None
        self.selected_solutions: list[int] = []
        self._dirty = False
        self._reset_values()

    # ------------------------------------------------------------------ project

    def set_project(self, project: Project) -> None:
        self.project = project
        self._frames.clear()
        self.dataset_name = project.datasets[0].name if project.datasets else None
        ui = project.ui_state
        if ui.get("model"):
            try:
                self.model_spec = ModelSpec.from_dict(ui["model"])
            except Exception:  # an older or edited file; fall back to the default
                self.model_spec = ModelSpec()
        else:
            self.model_spec = ModelSpec()
        self._reset_values()
        self.selected_run, self.selected_solutions = None, []
        self.set_dirty(False)
        self.projectChanged.emit()
        self.datasetChanged.emit()
        self.modelChanged.emit()
        self.objectivesChanged.emit()
        self.runsChanged.emit()

    def save_project(self, folder: str | None = None) -> None:
        self.project.ui_state["model"] = self.model_spec.with_values(self.values).to_dict()
        self.project.save(folder)
        self.set_dirty(False)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, dirty: bool = True) -> None:
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirtyChanged.emit(dirty)

    # ------------------------------------------------------------------ data

    @property
    def dataset(self) -> DatasetSpec | None:
        if self.dataset_name is None:
            return None
        try:
            return self.project.dataset(self.dataset_name)
        except KeyError:
            return None

    def frame(self, name: str | None = None) -> pd.DataFrame | None:
        name = name or self.dataset_name
        if name is None:
            return None
        if name not in self._frames:
            self._frames[name] = load_dataset(self.project.dataset(name))
        return self._frames[name]

    def add_dataset(self, spec: DatasetSpec, frame: pd.DataFrame) -> None:
        self.project.upsert_dataset(spec)
        self._frames[spec.name] = frame
        self.dataset_name = spec.name
        self.set_dirty()
        self.datasetChanged.emit()

    def select_dataset(self, name: str) -> None:
        if name != self.dataset_name:
            self.dataset_name = name
            self.datasetChanged.emit()

    def set_periods(self, calibration: Period, validation: Period) -> None:
        ds = self.dataset
        if ds is None:
            return
        if (ds.calibration.to_dict(), ds.validation.to_dict()) == (calibration.to_dict(), validation.to_dict()):
            return
        ds.calibration, ds.validation = calibration, validation
        self.set_dirty()
        self.periodsChanged.emit()

    def set_period(self, key: str, period: Period) -> None:
        """Set ``"calibration"`` or ``"validation"`` (an open :class:`Period` clears it)."""
        ds = self.dataset
        if ds is None:
            return
        cal, val = ds.calibration, ds.validation
        self.set_periods(period if key == "calibration" else cal, period if key == "validation" else val)

    # ------------------------------------------------------------------ model

    def _reset_values(self) -> None:
        self.values = {p.name: p.value for p in CATALOG.describe_parameters(self.model_spec)}

    def calibrate_flags(self) -> dict[str, bool]:
        return {p.name: p.calibrate for p in self.parameter_info()}

    def parameter_info(self) -> list[ParameterInfo]:
        return CATALOG.describe_parameters(self.model_spec.with_values(self.values))

    def set_model(self, spec: ModelSpec, values: dict[str, float] | None = None) -> None:
        """Replace the working model.

        Overrides and *values* for parameters the new structure lacks are
        dropped, so a structure edit keeps everything that still applies.
        """
        self.model_spec = CATALOG.prune(spec)
        self._reset_values()
        if values:
            self.values.update({k: v for k, v in values.items() if k in self.values})
        self.set_dirty()
        self.modelChanged.emit()
        self.valuesChanged.emit(dict(self.values))

    def set_model_label(self, label: str) -> None:
        if label != self.model_spec.label:
            self.model_spec.label = label
            self.set_dirty()
            self.modelRenamed.emit()

    def set_values(self, values: dict[str, float]) -> None:
        changed = {k: float(v) for k, v in values.items() if k in self.values and self.values[k] != float(v)}
        if changed:
            self.values.update(changed)
            self.valuesChanged.emit(dict(self.values))

    def edit_parameter(self, name: str, *, lower: float | None = None, upper: float | None = None,
                       calibrate: bool | None = None) -> None:
        from .core.catalog import ParameterState

        st = self.model_spec.parameters.setdefault(name, ParameterState())
        if lower is not None:
            st.lower = float(lower)
        if upper is not None:
            st.upper = float(upper)
        if calibrate is not None:
            st.calibrate = bool(calibrate)
        self.set_dirty()
        self.parametersEdited.emit()

    def reset_parameters(self) -> None:
        self.model_spec.parameters.clear()
        self._reset_values()
        self.parametersEdited.emit()
        self.valuesChanged.emit(dict(self.values))

    def working_spec(self) -> ModelSpec:
        """The model spec with the current slider values baked in."""
        return self.model_spec.with_values(self.values)

    # ------------------------------------------------------------------ objectives / solver

    @property
    def objectives(self) -> list[ObjectiveSpec]:
        return self.project.objectives

    def set_objectives(self, objectives: list[ObjectiveSpec]) -> None:
        self.project.objectives = list(objectives)
        self.set_dirty()
        self.objectivesChanged.emit()

    @property
    def solver(self) -> SolverSpec:
        return self.project.solver

    def set_solver(self, solver: SolverSpec) -> None:
        self.project.solver = solver
        self.set_dirty()

    # ------------------------------------------------------------------ runs

    def add_run(self, run: RunRecord) -> None:
        self.project.runs.append(run)
        self.set_dirty()
        self.runsChanged.emit()

    def update_run(self, run: RunRecord) -> None:
        self.set_dirty()
        self.runUpdated.emit(run.id)

    def remove_runs(self, ids: list[str]) -> None:
        self.project.runs = [r for r in self.project.runs if r.id not in set(ids)]
        if self.selected_run in ids:
            self.selected_run, self.selected_solutions = None, []
        self.set_dirty()
        self.runsChanged.emit()

    def run(self, run_id: str | None) -> RunRecord | None:
        if run_id is None:
            return None
        try:
            return self.project.run(run_id)
        except KeyError:
            return None

    def select(self, run_id: str | None, indices: list[int]) -> None:
        self.selected_run = run_id
        self.selected_solutions = list(indices)
        self.selectionChanged.emit(run_id or "", list(indices))

    def load_solution(self, run_id: str, index: int) -> None:
        """Make a run's model the working model with solution *index*'s values."""
        run = self.project.run(run_id)
        self.set_model(run.model, run.solution_values(index))

    # ------------------------------------------------------------------ misc

    def ui(self, key: str, default: Any = None) -> Any:
        return self.project.ui_state.get(key, default)

    def set_ui(self, key: str, value: Any) -> None:
        self.project.ui_state[key] = value
        self.set_dirty()
