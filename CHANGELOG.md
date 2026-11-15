# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Application shell: one standard toolbar on every page (project, Run/Stop for the page's command, chart
  navigation bound to the page's active chart, page-specific actions) and a standard status bar (message,
  context, cursor readout, activity with a global progress bar). SVG icon set, tinted to the theme.
- Project file: one SQLite file (`*.shproj`) holding sites, sensors, zones, edges, attributes, WKT locations
  and the time series themselves (compressed arrays), with tables named after the water ontology
  (`MonitoringSite`, `Sensor`, `Zone`, `Edge`, `Datastream`, `Observation`, `AttributeMeasurement`), plus
  datasets, models, runs and settings. The app edits an in-memory copy and Save writes it atomically.
  Projects saved as folders by earlier versions are imported on open.
- Property editor modelled on QPropertyModel: typed editors with units, limits, choices, descriptions,
  reset to default and multi-object editing; used for site properties and custom attributes
  ("Add attribute...") on the Data page.
- Process builder (Model page): grow a model one process at a time - rainfall losses, a list of unit
  hydrographs, other flow components - with parameter values carried across design changes; new RTK
  triangles start progressively slower. The component-tree editor moves to an Advanced tab.
- Progress reporting: per-run progress bars in Calibrate (generations or evaluations), event detection and
  fitting report event i/N and can be stopped between events.

- PySide6 + pyqtgraph application with six workspaces: Data, Model, Events, Calibrate, Explore and Compare.
- Parameter dock with linear or log sliders, editable bounds and calibrate flags; live re-simulation on a
  worker thread with request coalescing.
- Unit hydrograph preview (unit area, hours) with shape statistics and pinned comparisons.
- Calibration in worker processes with progress, cancellation and a run queue; NSGA-II, Platypus
  (NSGA-III, SPEA2, GDE3, IBEA, SMPSO) and SciPy optimizers.
- Brushable parallel coordinates and Pareto scatter with linked selection; the slider point is shown
  in objective space.
- Parsimony comparison: parameter counts, AIC/AICc/BIC, calibration vs validation scores and a
  complexity-performance front.
- Events workspace: event hierarchy detection, one unit hydrograph per global event, four views,
  event exclusion.
- Project folders (`project.json` + `runs/*.npz`), recent projects, light/dark themes.
- Packaging: wheel with `sparsehydro-viewer` GUI entry point, PyInstaller spec, Inno Setup installer
  script, CI for tests and releases.
