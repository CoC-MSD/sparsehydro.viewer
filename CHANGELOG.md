# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Developer credit for Caleb Buahin and attribution as developed on behalf of MSDGC by Hazen and Sawyer
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
  `.shproj` project files with the viewer. Started from Python, the main window sets its own taskbar relaunch
  properties (icon, command, name) so the taskbar button shows the application icon without a shortcut.
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
  sanitary term, each part of a peak-tail or mixture UH; sum weights applied), and the "States & inputs" tab
  lists the dataset's other inputs (e.g. temperature) and the model's states and fluxes by component
  (remaining initial abstraction, tank storage, soil and groundwater stores, snowpack, melt...). Ticked series
  are drawn in panels at the bottom of the hydrograph chart, one per unit, with the same width and time axis as
  the rain and flow panels, so they pan, zoom and select together. Both follow the sliders; the model trace is
  computed only while components or a model state is shown.
  Explore has the same "Components" layer for the selected solution, and "Export trace…" (Model page)
  saves the whole record's simulation with every component, state and flux to CSV, with a `.fields.csv`
  describing each column.
- Assess workspace: grades the working model or a calibration run's knee solution with the MSDGC calibration
  criteria (Modeling Guidelines Rev 5.8, via `sparsehydro.studies.msdgc.scorecard`). Events are detected on the
  chosen period with the MSDGC detector; the page shows the grade (text and symbol as well as colour, official or
  provisional with the reasons), each criterion against its pass and fail limits, observed-vs-model scatter plots
  of the zone and event volumes with the 1:1 line and ±10 % / ±20 % bands (Con15 events ringed, critical months
  as triangles), the concordance correlations by month group (Table 7-3), the Qcritical levels, and the event
  table linked to the hydrograph. Settings: period, storm or total volume, zone windows (tool v5.0.5 or
  guidelines), event detection. Sites gain the attributes "Average dry weather flow (ODWF-A)" and "Sewer
  system" that Qcritical needs; projects created earlier get them when opened.
- Unit hydrographs whose bounds allow responses too slow for the calibration period are reported once, by
  process and slider: the sliders concerned are marked in the Working model panel and the Model page explains
  the problem (sparsehydro's console warning, repeated on every evaluation, is no longer printed).
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
