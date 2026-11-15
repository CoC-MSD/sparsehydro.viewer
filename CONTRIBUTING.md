# Contributing

Thanks for helping improve sparsehydro-viewer.

## Branches and pull requests

- `main` holds releases and `dev` is the integration branch. Branch from `dev` as `feature/<topic>`
  or `bugfix/<topic>` and open pull requests against `dev`.
- Every pull request needs passing CI (`ruff`, `pytest` on Windows and Linux) and a `CHANGELOG.md`
  entry under `[Unreleased]`.
- Do not delete tests for code you did not change.

## Development setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -m "not slow"     # fast suite
pytest                   # full suite, including real calibrations in worker processes
```

GUI tests run headless (`QT_QPA_PLATFORM=offscreen`, set in `tests/conftest.py`).

## Architecture rules

- **Science belongs in sparsehydro.** If you need a new metric, kernel, detection rule or file
  reader, add it to the library and call it from `core/`. `core/catalog.py`, `core/diagnostics.py`
  and `core/events.py` hold temporary adapters that are meant to shrink as the library grows.
- `core/` is Qt-free and unit-tested without a display.
- Only `core/` and `services/` import `sparsehydro`; `widgets/` and `views/` must not
  (`tests/gui/test_app.py::test_views_and_widgets_do_not_import_sparsehydro`).
- Views talk to each other only through `Session` signals.
- Long work never runs on the GUI thread: use `JobManager` (threads) or `CalibrationService`
  (processes).

## Adding a model formulation

1. Implement and register it in sparsehydro.
2. Add a `ModelEntry` in `core/catalog.py` (options, factory, predicted output key, input column
   renames). It then appears in the Model page, sliders, calibration and comparison automatically.
3. `tests/core/test_catalog.py` parametrises over every catalog entry, so the new entry is exercised
   by the existing tests.

## Adding an optimizer or objective

Add a `SolverEntry` to `core/solvers.py` or an `ObjectiveEntry` to `core/objectives.py`. The forms
are generated from their `OptionSpec`s.

## Releases

Tag `vX.Y.Z` on `main`. The release workflow builds the wheel and sdist, publishes to PyPI with
trusted publishing, and attaches the Windows installer to the GitHub release.
