# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Dataset inputs: every dataset names the rain gauge and temperature series it reads, and both can be changed
  to any rain or temperature series of the project, including a gauge at another site (pickers on the Sites
  time-series tab and above the Model page hydrograph). The series must overlap the flow record. A change
  rebuilds the dataset, re-simulates the working model and redraws Explore and Compare. The inputs are shown
  in the Sites tree under each dataset, in the dataset selector's tooltip, the Working model panel, the
  Calibrate launch hint and the Assess banner; the map draws a dashed line from a flow site to the site of
  the gauge it uses (`USES_GAGE`), and the Sites chart plots temperature in its own panel.
- Assess names the working model ("Working model: <name> (current slider values)") in the model list, the
  grade banner, the hydrograph legend and the status bar, and follows a rename.
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
- Events workspace reworked: the hydrograph always shows the whole record with the global events shaded;
  choosing an event (list, Previous/Next, the comparison table or a double-click on its span) zooms to it and
  "Show all" (Home) returns to the full record. Several models can be fitted to the same events: any rain-driven
  unit hydrograph or the working model, each per event (one parameter set per global event, warm-started) and/or
  pooled (one parameter set for all events, sparsehydro's `PooledEventFitter`). Fits are overlaid (pooled
  dashed), the Comparison tab gives the NSE of every model and mode per event with the mean, the details list
  every model's fitted values, and "Use as working model" sends a configuration with its pooled (or the event's)
  values to the Model page. Progress covers every fit, and Stop cancels between events. One failing model does
  not lose the others. The configurations are saved in the project.
- Compare: the chosen-solutions chart shows every ticked run at once, each with its own solution (knee, best for
  any objective, or one picked by clicking it in the parallel coordinates), chosen in a list beside the chart; the
  same choice is used for scoring and marked on the fronts. The chart is simulated as soon as runs are ticked (no
  scoring needed), over the whole record with the calibration and validation periods shaded, runs alternate solid
  and dashed lines, and runs on other datasets are named instead of silently left out.
- Calibrate: a "Show" selector chooses what the convergence and front charts display - the run selected in the
  table, any particular run, or every running run overlaid in its own colour - so simultaneous calibrations can
  be followed side by side. "Earlier generations" draws the fronts of earlier reports behind the current one,
  fainter the older they are, and a slider replays the run report by report (it follows a running calibration
  until dragged back). The convergence chart can also show the front's size and its normalised hypervolume per
  report (`core.diagnostics.front_history`, exact hypervolume up to four objectives).
- One solution selection across charts and pages. Explore and Compare share the session's selection
  (`core/selection.py`): click a point or a line to select a solution, Ctrl+click to add or remove one, Shift+drag
  a rectangle in the scatter, or brush an axis of the parallel coordinates to select everything that passes (the
  brush also filters that run wherever it is shown); Esc clears. Every chart redraws from the selection, and what
  is selected on one page is selected on the other.
  - Explore draws one line per selected solution (up to 12, the primary one emphasised) over a filled band between
    the minimum and maximum of the selection - or of the whole Pareto set when one solution is selected ("Pareto
    range", with a legend entry). A "Selected" table lists every selected solution with its objectives and
    parameters; clicking a row makes it the primary one that the parameters, unit hydrograph and components show.
    With nothing selected the knee is shown by default, without selecting it elsewhere.
  - Compare's parallel coordinates and fronts are now clickable and brushable: a click also makes that solution the
    run's chosen one; the chart shows each run's Pareto range as a band, its chosen solution, and any other
    selected solutions as thinner lines.
  - Simulations of selected solutions are shared and cached (`core/simulate.py`), so returning to a solution or
    opening it on the other page is immediate.
- Earlier generations keep their parameter sets. Every progress report of a calibration now stores the front's
  parameter vectors with its objectives (sparsehydro's solver callbacks pass `pareto_X`), saved in the project
  (at most 200 reports per run: the first, the last and evenly spaced ones). Their solutions can therefore be
  clicked and simulated like those of the final front: in Calibrate's front chart (with "Earlier generations" or
  while replaying a report, and on the latest report of a running calibration), and in Explore, whose new
  **Earlier generations** action draws the history behind the front. A selected earlier solution shows its
  hydrograph, parameters and unit hydrograph, can be Ctrl+clicked together with final solutions, and "Load into
  sliders" takes it. Runs saved before this (or by solvers that report no parameter sets) show their history as
  before, not clickable, and say why.
- Clickable legends on every chart: clicking a legend symbol hides or shows its series, including everything
  drawn for it (a band's fill, a stacked component's fill and edge, all earlier-generation layers together), and a
  hidden series stays hidden when the chart redraws (slider moves, new selections, rebuilt state panels). Bands
  now have legend entries. The toolbar's chart group gains **Series**, a menu of the active chart's series with
  tick boxes and "Show all" - the keyboard route to the same thing (`widgets/legend.py`).
- User documentation (Sphinx, built on the sparsehydro docs setup): installation, a getting-started tutorial on the
  sample data, one page per workspace, keyboard shortcuts, and reference pages for the project file and its
  water-ontology mapping, the MSDGC criteria, extensions, the architecture and the `core` API. Screenshots are
  generated, not captured: `docs/scripts/screenshots.py` drives the application offscreen on the sample data (with
  throwaway settings), and the docs workflow runs it before a strict build and publishes to GitHub Pages.
- Calibrate: earlier generations no longer set the front chart's axes, so early poor solutions do not squeeze the
  current front into a corner (`ParetoLayer.in_range`).
- GIS import and export of sewersheds and sites (Sites page, Map tab; optional `gis` extra with pyogrio and pyproj,
  bundled in the Windows installer). Reads file geodatabases (choose the layer), shapefiles, GeoPackage, GeoJSON,
  KML/KMZ and other GDAL formats and reprojects to longitude/latitude. The wizard previews the layer on a map and maps
  its columns: the name and id columns, the zone kind (fixed or from a column), which columns become attributes
  (name, type and unit editable), and what to do with features already in the project (skip, update, add).
  Polygons and multipolygons (with holes) become zones, points become sites, lines are refused with a reason.
  Sites inside a zone are linked to it (`BELONGS_TO_ZONE`) and each zone's area on the WGS84 ellipsoid is stored as
  "Contributing area" [ac]. Zones or sites (all, or the selected ones) export to GeoPackage, GeoJSON or shapefile.
  The map draws multipolygons and holes, and thins very large rings for drawing only. The self-test reads a small
  layer in a projected coordinate system when the extra is installed.
- Map tools on the standard toolbar: on the Map tab the toolbar's Pan, Zoom box, Fit all and Export act on the
  map, and with the page's Select, Edit locations and Draw zone they form one group with exactly one tool active.
  Select drags a rectangle (no Shift needed) or, from its drop-down, a free lasso; click and Ctrl+click as
  before; Alt picks zones only (otherwise sites win over the zones beneath them); Esc clears the selection.
  The wheel zooms and the middle button pans in every tool. The status bar shows the latitude and longitude
  under the mouse and how many features are selected.
- Optimizers follow what is installed: NSGA-II from Platypus is the default; where Platypus is absent (the
  Windows installer, which leaves out GPL code) NSGA-II from pymoo is offered instead, and unavailable optimizers
  are not listed. Projects and run settings naming an NSGA-II that is not installed switch to the other one at
  the same evaluation budget (population x generations), with a note; other missing optimizers fall back to the
  default. pymoo is an optional extra (`sparsehydro-viewer[pymoo]`, in `dev`), following sparsehydro, which
  makes it optional and deprecates its pymoo solver. The self-test requires one multi-objective optimizer.
- OMOPSO (Platypus) optimizer: multi-objective particle swarm with an ε-dominance archive; options for swarm and
  leader sizes, ε (one value for all objectives), mutation probability, evaluations, seed and report interval.
- Accessibility and finish: every control has an accessible name for screen readers and, where its purpose is not
  written on it, a tooltip (parameter sliders and values say what the parameter is, its range, units and whether
  the slider is logarithmic; option fields give their description, range and default; toolbar actions show their
  shortcut and a status-bar tip). Controls without an explicit name are named from their label, text, tooltip or
  group (`views/accessibility.py`). A high-contrast theme (black, white, yellow accent) joins light and dark, and
  every theme meets WCAG 2 AA contrast (4.5:1 for text, 3:1 for plotted lines); in the dark theme, text on the
  accent colour is now dark (white was 2.7:1). Tests check names, tooltips, keyboard reach and contrast.
- `sparsehydro-viewer --self-test REPORT` checks an installation (every unit hydrograph, composed models and their
  traces, small calibrations in spawned worker processes, a project round trip, the main window) and writes a
  report; optional components such as the Platypus optimizers are reported as unavailable without failing. The
  release workflow runs it on the frozen executable instead of `--version`, keeps the report, and can be started
  by hand to build and test the installer without publishing.
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

### Fixed

- Compare: the chosen-solutions chart was squeezed to a few pixels on ordinary screens (it looked empty) and
  stayed empty until the runs were scored; it now has a minimum height and the largest share of the page.
