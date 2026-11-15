# Architecture

```
sparsehydro_viewer/
  __main__.py, app.py     entry point, QApplication, theme
  core/                   Qt-free: specs, catalogs, evaluation, persistence (only layer, with services, that imports sparsehydro)
    options.py            OptionSpec: declarative constructor options -> generated forms
    components.py         component types (flow / abstraction / uh), ComponentSpec trees, build()
    catalog.py            ModelSpec = component tree + parameter overrides; build, describe, prune
    objectives.py         ObjectiveSpec / catalog
    solvers.py            SolverSpec / catalog
    data.py               DatasetSpec, loading (CSV/TSF), periods
    evaluation.py         Evaluator: prepared model + CalibrationProblem; one call = series + objectives + constraints
    uh.py                 unit hydrograph curves and statistics
    calibration.py        run_calibration(): rebuilds everything from a picklable payload
    runs.py               RunRecord: configuration + Pareto set + history
    project.py            Project folder persistence
    diagnostics.py        non-domination, AIC/BIC, complexity front
    events.py             event detection + per-event fitting, overrides
  services/               Qt-side execution
    jobs.py               JobManager: thread pool, progress, cancellation
    calibration.py        CalibrationService: one spawned process per run, queue, cancel/terminate
    live.py               LiveEvaluationService: worker thread, latest-request-wins
  session.py              Session: single source of state, signals only
  widgets/                plots and inputs (no sparsehydro imports)
  views/                  pages and main window (no sparsehydro imports)
```

## Model-view-controller

`Session` is the model. Views never talk to each other: they write to the session and redraw from its
signals.

| Change | Written by | Session signal | Reacting views |
| --- | --- | --- | --- |
| Dataset loaded or selected | Data page | `datasetChanged` | Data chart, live evaluation, Calibrate summary, dock header |
| Calibration/validation period | Data date fields, chart drag-select, region drag, toolbar actions | `periodsChanged` | Data chart regions and fields, live evaluation, Calibrate summary, dock header |
| Model structure | Model composer, Explore "Load into sliders", Calibrate "Use settings" | `modelChanged` | Working-model dock, composer, live evaluation, status bar, Explore and Compare markers |
| Parameter values | Working-model dock sliders, Explore "Load into sliders" | `valuesChanged` | Live evaluation, then Model, Explore and Compare |
| Bounds / calibrate flags | Working-model dock | `parametersEdited` | Live evaluation, counts, Calibrate summary |
| Objectives | Calibrate page | `objectivesChanged` | Live evaluation, Model metrics |
| Runs and selection | Calibrate, Explore, Compare | `runsChanged`, `runUpdated`, `selectionChanged` | Run tables, Explore, Compare |

Structure edits carry over values: the composer emits parameter renames (wrapping a model into a sum
adds a term prefix; reordering or removing UHs renumbers `uh{i}_` and `R_i`), and the session keeps
every value and bound whose renamed parameter still exists.

## Data flow for a slider move

1. `ParameterRow` updates its spin box and tells `ParameterPanel`, which batches edits for 30 ms.
2. `ParameterPanel.valuesEdited` -> `Session.set_values` -> `Session.valuesChanged`.
3. `LiveController` posts the values to `LiveEvaluationService`; only the newest pending request is
   kept.
4. The worker thread's `Evaluator.evaluate()` applies the values, calls
   `CalibrationProblem.evaluate` (the optimizers' own code path) and `predict_arrays()`, and computes
   UH curves.
5. `LiveResult` returns to the GUI thread; Model, Explore and Compare redraw. Explore shows it as the
   star in the Pareto plot and the dashed line in parallel coordinates.

A typical evaluation of a year of 5-minute data takes a few milliseconds; `tests/core/test_evaluation.py`
asserts under 50 ms for three weeks.

## Calibration

`CalibratePage` builds a `RunRecord` and a `CalibrationPayload` (model spec dict, objective and solver
specs, the data frame and the period). `CalibrationService` starts a `spawn` process running
`core.calibration.process_main`, which rebuilds the model and streams `started`, `progress`, then
`finished`, `failed` or `cancelled` over a queue that a 100 ms timer drains. Cancelling sets an event
that the solver callback checks; solvers without callbacks are terminated after 4 s.

## Library adapters (to shrink as sparsehydro grows)

| Here | Replace with (library plan item) |
| --- | --- |
| `core/catalog.py` model list and option descriptors | `registry.describe()` + `build_model(config)` (L3, direction plan phase 4) |
| `core/solvers.py`, `core/objectives.py` option descriptors | solver/objective registries with `describe()` (L3) |
| `core/uh.py` child-parameter mapping by prefix | `kernel_curve(dt_hours)` on UH components and composites (L5) |
| `core/diagnostics.py` | `sparsehydro.calibration.diagnostics` (L7) |
| `core/events.py` overrides (only exclusion applied) | event overrides in detection (L8) |
| `services/calibration.py` hard terminate for SciPy | a cancel token honoured by every solver (L4) |
