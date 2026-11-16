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
from .core.data import DatasetSpec, Period
from .core.objectives import ObjectiveSpec
from .core.project import Project
from .core.runs import RunRecord
from .core.selection import SolutionRef, SolutionSelection
from .core.solvers import SolverSpec


class Session(QObject):
    projectChanged = Signal()
    projectSaved = Signal()
    nodesChanged = Signal(list)  # iris of sites/sensors/zones whose fields or attributes changed
    nodesStructureChanged = Signal()  # nodes added or removed
    nodeSelectionChanged = Signal(list)  # iris selected in the Sites workspace (tree or map)
    datasetChanged = Signal()
    datasetDataChanged = Signal(str)  # a dataset's series changed (another rain gauge or temperature series)
    periodsChanged = Signal()  # calibration/validation period of the current dataset
    modelChanged = Signal()
    modelRenamed = Signal()
    parametersEdited = Signal()  # bounds / calibrate flags changed (structure, not values)
    valuesChanged = Signal(dict)  # slider values
    objectivesChanged = Signal()
    runsChanged = Signal()
    runUpdated = Signal(str)
    #: The solutions selected across the application (a :class:`~.core.selection.SolutionSelection`).
    solutionSelectionChanged = Signal(object)
    #: Run id whose filter (the solutions passing a parallel-coordinates brush) changed.
    solutionFilterChanged = Signal(str)
    selectionChanged = Signal(str, list)  # primary run id and its selected final-front indices (legacy view)
    dirtyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = Project()
        self._frames: dict[str, pd.DataFrame] = {}
        self.dataset_name: str | None = None
        self.model_spec: ModelSpec = ModelSpec()
        self.values: dict[str, float] = {}
        self.selection = SolutionSelection()
        #: Run id -> solution indices passing that run's brush (absent: no filter).
        self.filter_rows: dict[str, list[int]] = {}
        self.selected_nodes: list[str] = []
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
        self.selection = SolutionSelection()
        self.filter_rows = {}
        self.selected_nodes = []
        self.set_dirty(False)
        self.projectChanged.emit()
        self.nodesStructureChanged.emit()
        self.datasetChanged.emit()
        self.modelChanged.emit()
        self.objectivesChanged.emit()
        self.runsChanged.emit()

    def save_project(self, path: str | None = None) -> None:
        """Save to *path* (a ``.shproj`` file; default: the file the project was opened from)."""
        self.project.ui_state["model"] = self.model_spec.with_values(self.values).to_dict()
        self.project.save(path)
        self.set_dirty(False)
        self.projectSaved.emit()

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
            self._frames[name] = self.project.frame(name)
        return self._frames[name]

    def add_dataset(self, spec: DatasetSpec, frame: pd.DataFrame) -> None:
        """Import *frame* into the project database (site, sensors, series) and make it the current dataset."""
        self.project.add_dataset(spec, frame)
        self._frames[spec.name] = frame
        self.dataset_name = spec.name
        self.set_dirty()
        self.nodesStructureChanged.emit()
        self.datasetChanged.emit()
        site = self.dataset.site_iri if self.dataset is not None else None
        if site:
            self.select_nodes([site])

    def select_dataset(self, name: str) -> None:
        if name != self.dataset_name:
            self.dataset_name = name
            self.datasetChanged.emit()

    def set_dataset_inputs(self, name: str, *, rain_stream: str | None = None,
                           temperature_stream: str | None = "") -> None:
        """Change which rain gauge and/or temperature series dataset *name* uses (see
        :meth:`~.core.project.Project.set_dataset_inputs`); everything computed from the dataset is redone."""
        self.project.set_dataset_inputs(name, rain_stream=rain_stream, temperature_stream=temperature_stream)
        self._frames.pop(name, None)  # the frame is rebuilt from the new series
        self.set_dirty()
        self.datasetDataChanged.emit(name)
        self.nodesStructureChanged.emit()  # the tree lists each dataset's inputs
        if name == self.dataset_name:
            self.datasetChanged.emit()

    def inputs_text(self, name: str | None = None) -> str:
        """Rain and temperature series of a dataset (default: the current one), for hints and tooltips."""
        name = name or self.dataset_name
        return self.project.inputs_text(name) if name else ""

    # ------------------------------------------------------------------ nodes (project database)

    @property
    def store(self):
        return self.project.store

    def select_nodes(self, iris: list[str]) -> None:
        """Select nodes; a single site with data also becomes the current dataset."""
        iris = list(dict.fromkeys(iris))
        if iris == self.selected_nodes:
            return
        self.selected_nodes = iris
        self.nodeSelectionChanged.emit(list(iris))
        if len(iris) == 1:
            sets = self.datasets_of(iris[0])
            if sets and self.dataset_name not in {d.name for d in sets}:
                self.select_dataset(sets[0].name)

    def datasets_of(self, site_iri: str) -> list[DatasetSpec]:
        return [d for d in self.project.datasets if d.site_iri == site_iri]

    def add_node(self, table: str, label: str, **fields) -> str:
        iri = self.project.store.add_node(table, label, **fields)
        self.set_dirty()
        self.nodesStructureChanged.emit()
        return iri

    def import_gis_layer(self, layer, plan):
        """Import a GIS layer (see :func:`sparsehydro_viewer.core.gis.import_layer`) and notify views once."""
        from .core.gis import import_layer

        report = import_layer(self.project.store, layer, plan)
        if report.added or report.updated or report.links:
            self.set_dirty()
            self.nodesStructureChanged.emit()
            self.nodesChanged.emit(list(report.updated))
        return report

    def delete_nodes(self, iris: list[str]) -> None:
        """Delete nodes (with their sensors' data); datasets recorded at deleted sites go too."""
        st = self.project.store
        gone = set(iris)
        for iri in list(iris):  # sensors of deleted sites go with them
            gone |= {n.iri for n in st.sensors_of(iri)}
        for iri in gone:
            st.delete_node(iri)
        before = len(self.project.datasets)
        self.project.datasets = [d for d in self.project.datasets if d.site_iri not in gone]
        for name in list(self._frames):
            if not any(d.name == name for d in self.project.datasets):
                del self._frames[name]
        if self.dataset_name and not any(d.name == self.dataset_name for d in self.project.datasets):
            self.dataset_name = self.project.datasets[0].name if self.project.datasets else None
        self.selected_nodes = [i for i in self.selected_nodes if i not in gone]
        self.set_dirty()
        self.nodesStructureChanged.emit()
        self.nodeSelectionChanged.emit(list(self.selected_nodes))
        if len(self.project.datasets) != before:
            self.datasetChanged.emit()

    def update_node(self, iri: str, **fields) -> None:
        """Change a node's own fields (label, description, geometry...) and notify views."""
        self.project.store.update_node(iri, **fields)
        self.set_dirty()
        self.nodesChanged.emit([iri])

    def set_attribute(self, iri: str, key: str, value) -> None:
        """Set (``None`` clears) an attribute of a node and notify views."""
        self.project.store.set_attribute(iri, key, value)
        self.set_dirty()
        self.nodesChanged.emit([iri])

    def define_attribute(self, definition) -> None:
        self.project.store.define_attribute(definition)
        self.set_dirty()
        self.nodesChanged.emit([])

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
        for rid in ids:
            self.filter_rows.pop(rid, None)
        self._apply_selection(self.selection.pruned(r.id for r in self.project.runs))
        self.set_dirty()
        self.runsChanged.emit()

    def run(self, run_id: str | None) -> RunRecord | None:
        if run_id is None:
            return None
        try:
            return self.project.run(run_id)
        except KeyError:
            return None

    # ------------------------------------------------------------------ solution selection
    #
    # One selection for the whole application. Charts never talk to each other: a click, Ctrl+click, rubber band
    # or brush in any of them writes the selection here, and every chart redraws from solutionSelectionChanged.

    def _apply_selection(self, selection: SolutionSelection, *, force: bool = False) -> None:
        if selection == self.selection and not force:
            return
        self.selection = selection
        self.solutionSelectionChanged.emit(selection)
        self.selectionChanged.emit(self.selected_run or "", list(self.selected_solutions))

    def set_selection(self, refs, primary: SolutionRef | None = None) -> None:
        """Select exactly *refs* (across runs); *primary* (default: the last) drives the detail views."""
        self._apply_selection(self.selection.replaced(refs, primary))

    def select_in_run(self, run_id: str, refs, primary: SolutionRef | None = None, *, add: bool = False) -> None:
        """Replace (or with *add*, extend) one run's selected solutions; other runs keep theirs."""
        self._apply_selection(self.selection.with_run(run_id, refs, primary, add=add))

    def toggle_selected(self, ref: SolutionRef) -> None:
        """Ctrl+click: add *ref* to the selection, or remove it if it is selected."""
        self._apply_selection(self.selection.toggled(ref))

    def clear_selection(self) -> None:
        self._apply_selection(SolutionSelection())

    def set_filter(self, run_id: str, rows: list[int] | None) -> None:
        """Record the solutions of a run that pass its brush (``None``: no filter), for every view of that run."""
        if rows is None:
            if self.filter_rows.pop(run_id, None) is None:
                return
        else:
            if self.filter_rows.get(run_id) == list(rows):
                return
            self.filter_rows[run_id] = list(rows)
        self.solutionFilterChanged.emit(run_id)

    @property
    def selected_run(self) -> str | None:
        """Run of the primary selected solution."""
        return self.selection.primary.run_id if self.selection.primary else None

    @property
    def selected_solutions(self) -> list[int]:
        """Selected final-front indices of the primary run, the primary one first."""
        run_id = self.selected_run
        return self.selection.indices(run_id) if run_id else []

    def select(self, run_id: str | None, indices: list[int]) -> None:
        """Select final-front solutions of one run (the first is primary); always notifies."""
        if run_id is None:
            self._apply_selection(SolutionSelection(), force=True)
            return
        refs = [SolutionRef(run_id, int(i)) for i in indices]
        self._apply_selection(self.selection.with_run(run_id, refs, refs[0] if refs else None), force=True)

    def load_solution(self, run_id: str, index: int, generation: int | None = None) -> None:
        """Make a run's model the working model with a solution's values."""
        run = self.project.run(run_id)
        self.set_model(run.model, run.solution_values(index) if generation is None
                       else run.solution_values(index, generation))

    # ------------------------------------------------------------------ misc

    def ui(self, key: str, default: Any = None) -> Any:
        return self.project.ui_state.get(key, default)

    def set_ui(self, key: str, value: Any) -> None:
        self.project.ui_state[key] = value
        self.set_dirty()
