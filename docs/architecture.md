# Architecture

```
sparsehydro_viewer/
  __main__.py, app.py     entry point (--version, --self-test), QApplication, theme, user extensions
  platform.py             Windows taskbar identity (AppUserModelID, relaunch icon/command)
  selftest.py             installation self-test (also run on the frozen build in CI)
  session.py              Session: single source of state, signals only
  core/                   Qt-free; the only layer, with services, that imports sparsehydro
    options.py            OptionSpec: declarative options -> generated forms and property editors
    components.py         component types discovered from sparsehydro's registries; ComponentSpec trees, build()
    processes.py          process-oriented model design (losses -> unit hydrographs -> other flows)
    catalog.py            ModelSpec = component tree + parameter overrides; build, describe, prune
    objectives.py         objectives from sparsehydro's objective registry
    solvers.py            solvers built through sparsehydro's solver registry
    extensions.py         sparsehydro.load_extensions() wrapper (entry points + configured modules)
    data.py               DatasetSpec, loading (CSV/TSF), periods
    evaluation.py         Evaluator: prepared model + CalibrationProblem; one call = series + objectives (+ trace)
    trace.py              hydrograph components, states, fluxes and dataset inputs from model traces
    uh.py                 unit hydrograph curves and statistics (hours-based kernels)
    calibration.py        run_calibration(): rebuilds everything from a picklable payload
    runs.py               RunRecord: configuration + Pareto set + history
    events.py             event detection; per-event and pooled fits of several configurations; overrides
    assess.py             MSDGC assessment (sparsehydro.studies.msdgc.scorecard) on a dataset
    diagnostics.py        non-domination, AIC/BIC, complexity front, slow-response warnings
    geometry.py           WKT and lon/lat <-> Web Mercator (no GIS dependency)
    migration.py          step-based unit hydrograph parameters -> hours, applied once per project
    project.py            Project: setup in memory, written into the store on save
    store/                SQLite project file (*.shproj): schema, typed store, array codec
  services/               Qt-side execution
    jobs.py               JobManager: thread pool, progress, cancellation
    calibration.py        CalibrationService: one spawned process per run, queue, cancel/terminate
    live.py               LiveEvaluationService: worker thread, latest-request-wins
  widgets/                plots and inputs (no sparsehydro imports)
    properties/           property editor after QPropertyModel
  views/                  pages, dialogs and main window (no sparsehydro imports)
    shell/                page protocol, standard toolbar, status bar, activity, dataset selector
```

## Project file

`core/store/` is the project database (SQLite, `*.shproj`). `schema.py` documents the tables and their
mapping to the water ontology (`water-ontology/schema`, `wsys:` namespace): `MonitoringSite`, `Sensor`, `Zone`,
`Edge`, `Datastream`, `Observation` (one packed array per series), `AttributeMeasurement`, plus viewer tables for
datasets, models, runs and settings. `store.py` (`ProjectStore`) is the typed API; `arrays.py` packs series
losslessly (regular time axes are stored as start + step). `core/project.py` (`Project`) keeps the setup in memory
and writes it into the store on save; the app works on an in-memory copy of the file and saves it back with
SQLite's backup API. Node edits go through the session (`Session.update_node`, `Session.set_attribute`), which
emits `nodesChanged`. Opening a project runs `core/migration.py` once (marked by the `uh_schema` setting) and
seeds attribute definitions added since the file was written.

`widgets/properties/` is the property editor (after QPropertyModel): `PropertyNode` tree, `PropertyModel`,
`PropertyDelegate`, `PropertyEditor`, and adapters for option specs and project nodes.

## Discovery and extensions

Nothing in the viewer lists models by hand. `core/components.py` reads sparsehydro's model registry
(unit hydrographs: `IUnitHydroComponent` subclasses; losses: models whose primary output is `p_excess_in`),
`core/objectives.py` the objective registry (options from constructor signatures), and `core/solvers.py` builds
solvers through the solver registry. `app.create_app` loads extensions first (`core/extensions.py` ->
`sparsehydro.load_extensions()`: the `sparsehydro.extensions` entry-point group plus the modules or `.py` files in
the `extensions/modules` setting) and then refreshes the catalogs; failures are logged, not raised.

## Application shell

`views/shell/` holds the parts every page shares:

- `page.py` - `Page`, the base class of every workspace. A page declares `primary_text` and implements
  `primary()` (the toolbar's Run button), `stop()` / `stop_enabled()` (Stop), `context_actions()`
  (page-specific toolbar buttons), `active_chart()` (the chart the navigation buttons act on) and
  `status_text()`; it emits `contextChanged` when any of these change. `submit_job()` runs background work
  that Stop can cancel.
- `toolbar.py` - `MainToolBar`: project actions, Run/Stop, `ChartActions` (pan, zoom box, fit, auto Y,
  export; `widgets/chart_actions.py`), the current page's actions (rebuilt when they change), the analysis
  dataset selector (`dataset_selector.py`), dock toggles.
- `status_bar.py` - `StandardStatusBar`: message, context, cursor readout of the active chart, and
  `activity.py`'s `ActivityIndicator` (one progress bar over thread-pool jobs and calibration processes).

## Model-view-controller

`Session` is the model. Views never talk to each other: they write to the session and redraw from its
signals.

| Change | Written by | Session signal | Reacting views |
| --- | --- | --- | --- |
| Sites, sensors, zones, attributes | Sites tree, map, property editor, import dialog | `nodesChanged`, `nodesStructureChanged` | Sites tree, map, properties |
| Node selection | Sites tree, map | `nodeSelectionChanged` | Sites tree, map, properties |
| Analysis dataset | toolbar selector, Sites page | `datasetChanged` | every page, live evaluation, Calibrate summary, dock header |
| Calibration/validation period | Sites chart drag-select, region drag, toolbar actions | `periodsChanged` | Sites chart regions, live evaluation, Calibrate summary, dock header |
| Model structure | process builder, component tree, Explore "Load into sliders", Calibrate "Use settings", Events "Use as working model" | `modelChanged` | Working-model dock, Model page, live evaluation, status bar, Explore and Compare markers |
| Parameter values | Working-model dock sliders, Explore "Load into sliders" | `valuesChanged` | Live evaluation, then Model, Explore and Compare |
| Bounds / calibrate flags | Working-model dock | `parametersEdited` | Live evaluation, counts, Calibrate summary |
| Objectives | Calibrate page | `objectivesChanged` | Live evaluation, Model metrics |
| Runs and selection | Calibrate, Explore, Compare | `runsChanged`, `runUpdated`, `selectionChanged` | Run tables, Explore, Compare, Assess source list |

Structure edits carry over values: the composer emits parameter renames (wrapping a model into a sum
adds a term prefix; reordering or removing UHs renumbers them), and the session keeps every value and bound
whose renamed parameter still exists.

## Data flow for a slider move

1. `ParameterRow` updates its spin box and tells `ParameterPanel`, which batches edits for 30 ms.
2. `ParameterPanel.valuesEdited` -> `Session.set_values` -> `Session.valuesChanged`.
3. `LiveController` posts the values to `LiveEvaluationService`; only the newest pending request is
   kept.
4. The worker thread's `Evaluator.evaluate()` applies the values, calls
   `CalibrationProblem.evaluate` (the optimizers' own code path) and `predict_arrays()`, and computes
   UH curves. Only while components or a model state are shown does it call `predict_trace()` instead,
   so the sliders cost nothing extra otherwise.
5. `LiveResult` returns to the GUI thread; Model, Explore and Compare redraw. Explore shows it as the
   star in the Pareto plot and the dashed line in parallel coordinates.

A typical evaluation of a year of 5-minute data takes a few milliseconds; `tests/core/test_evaluation.py`
asserts under 50 ms for three weeks.

## Components and internal states

sparsehydro models declare traced fields with a role (`output`, `component`, `state`, `flux`) and, for components,
the output they add up to (`component_of`); `predict_trace()` returns outputs plus every traced field for one run.
`core/trace.py` turns that into what the views draw: `flow_parts()` (the stacked components of the simulated
hydrograph, with sum weights applied, nested composites flattened to their leaves), `state_fields()` (states and
fluxes grouped by component, with units) and `input_fields()` (the dataset's other columns, such as temperature).
`TimeseriesPlot.set_panels()` draws the selected series in extra panels under rain and flow, one per unit, sharing
the time axis.

## Events

`core/events.py` detects the event hierarchy with sparsehydro (`detect_event_hierarchy`), applies the stored
overrides (currently: excluded global events), and fits every `EventConfig` - a rain-driven unit hydrograph or a
composed model such as the working model - per event (`GlobalSequentialFitter`, warm-started) and/or pooled
(`PooledEventFitter`, one parameter set for all events). Progress is reported across all fits and cancellation is
checked between events; a configuration that fails is recorded without losing the others. `EventAnalysis`
exposes the event table, `comparison_table()` (NSE of every configuration and mode per event, plus the mean) and
the whole-record fit weights. The Events page draws the whole record once per analysis and zooms to events.

## Calibration

`CalibratePage` builds a `RunRecord` and a `CalibrationPayload` (model spec dict, objective and solver
specs, the data frame and the period). `CalibrationService` starts a `spawn` process running
`core.calibration.process_main`, which rebuilds the model and streams `started`, `progress`, then
`finished`, `failed` or `cancelled` over a queue that a 100 ms timer drains. Cancelling sets an event
that the solver callback checks; solvers without callbacks are terminated after 4 s.

## Assessment

`core/assess.py` detects events with the MSDGC detector, simulates the chosen model (working model or a run's knee
solution) and calls `sparsehydro.studies.msdgc.scorecard.assess_calibration`; site attributes `shv:odwf_a` and
`shv:sewer_system` supply the Qcritical inputs. Compare grades every run the same way (`grade_run`).

## Packaging

`packaging/sparsehydro-viewer.spec` builds a one-folder PyInstaller bundle (Qt stays as replaceable shared
libraries, as the LGPL expects; Platypus is excluded by default, see THIRD_PARTY_NOTICES.md), `launcher.py` calls
`multiprocessing.freeze_support()` so calibration workers start in the frozen build, and `installer.iss` builds
the Inno Setup installer (per-user by default, optional `.shproj` association, AppUserModelID shortcuts).
The release workflow runs `sparsehydro-viewer.exe --self-test` on the bundle before building the installer; the
self-test evaluates every unit hydrograph, composed models and their traces, small calibrations in spawned
workers, a project round trip and the main window, and writes a report (a windowed executable has no console).

## Remaining library dependencies to watch

| Here | Waiting for |
| --- | --- |
| `core/events.py` overrides (only exclusion applied) | event overrides (add, split, merge, peaks) in sparsehydro's detection |
| `services/calibration.py` hard terminate for SciPy and CMA-ES | a cancel token honoured by every solver |
| `core/diagnostics.py` AIC/BIC | `metrics.functions` information criteria, if adopted by the library |
