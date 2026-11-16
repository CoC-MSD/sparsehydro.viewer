# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Developer credit for Caleb Buahin and partnership credit for MSDGC and Hazen and Sawyer
  in the About dialog, package metadata, Windows installer and documentation.
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
  ("Add attribute...") on the Sites page.
- Sites workspace (replaces Data): a tree of sites (with their sensors and datasets) and zones, a map and the
  time-series chart with calibration/validation periods, and the property editor. The map (Web Mercator,
  no GIS dependency) draws sites coloured by sensor kind and zones as polygons, with click, Ctrl-click and
  Shift-drag selection shared with the tree and the rest of the application; "Edit locations" places or
  drags sites, "Draw zone" digitises a polygon, and a scale bar shows ground distance. An optional
  OpenStreetMap basemap (cached tiles) is off by default and asks once before anything is downloaded,
  because the tile server sees the area viewed. The import dialog adds data to a new or existing site,
  optionally with its location.
- Application icon (window, taskbar, Windows executable and installer); the installer can associate
  `.shproj` project files with the viewer.
- Runs on the refactored sparsehydro (hours-based unit hydrographs, `metrics`, registries). Unit
  hydrographs, losses and objectives are discovered from sparsehydro's registries, so every registered
  formulation is offered (Clark, ModClark, SCS, Snyder, Weibull, lognormal, generalised gamma, mixture, ...)
  and extensions appear automatically: installed packages through the `sparsehydro.extensions` entry-point
  group, or modules / `.py` files listed in the settings (`extensions/modules`), loaded with
  `sparsehydro.load_extensions()`. Requires sparsehydro 1.0.0b1 or later. Solvers are built through
  sparsehydro's solver registry; Platypus NSGA-II and CMA-ES were added.
- The analysis dataset is shown on the toolbar of every page and can be switched there.
- Hydrograph components and internal states (Model page), from sparsehydro's model traces:
  "Components" stacks the simulated hydrograph as its individual hydrographs (each unit hydrograph, the
  sanitary term, each part of a peak-tail or mixture UH; sum weights applied), and the "Internal states" tab
  lists the model's states and fluxes by component (remaining initial abstraction, tank storage, soil and
  groundwater stores, snowpack, melt...) and plots the ticked ones on the hydrograph's time axis, one panel
  per unit. Both follow the sliders; the trace is computed only while one of them is on screen.
- Projects saved with step-based unit hydrograph parameters are converted to hours when opened (models,
  the working model and every run's Pareto set; see `core/migration.py`), and marked so it happens once.
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
