# sparsehydro.viewer

Desktop workbench for [sparsehydro](https://github.com/CoC-MSD/SparseHydro): organise monitoring sites and their
rainfall and flow records, build a model one hydrological process at a time, see every parameter change in the
hydrograph, its components and the model's internal states as you drag a slider, fit storm events, calibrate with
multi-objective optimizers, compare alternative models with parameter count as a first-class axis, and grade a model
against the MSDGC calibration criteria.

Built on PySide6 (Qt for Python) and pyqtgraph.

## Credits

**Developer:** Caleb Buahin.

Developed on behalf of **MSDGC** (Metropolitan Sewer District of Greater Cincinnati)
by **Hazen and Sawyer**.

## Install

```bash
pip install sparsehydro-viewer
sparsehydro-viewer            # or: python -m sparsehydro_viewer [project.shproj]
```

Windows users without Python can use the installer attached to each
[GitHub release](https://github.com/CoC-MSD/sparsehydro.viewer/releases); it can also associate `.shproj` project
files with the application.

The viewer needs sparsehydro 1.0.0b1 or later. Until it is published on PyPI, install it first from source:

```bash
pip install "sparsehydro @ git+https://github.com/CoC-MSD/SparseHydro@v1.0.0b1"
```

To check an installation (models, calibration in worker processes, the project file and the main window):

```bash
sparsehydro-viewer --self-test report.txt    # exit code 0 when every required check passes
```

## Workspaces

Every page shares one toolbar (project, Run/Stop for the page's main command, chart navigation for the page's
active chart, page-specific actions, and the **analysis dataset**, switchable from any page) and one status bar
(messages, context, cursor readout, and a progress bar over all background work).

| Workspace | What it does |
| --- | --- |
| **Sites** | The project's monitoring sites, their sensors and datasets, and zones (sewersheds) in a tree, on a map and with a property editor (typed values, units, limits; custom attributes). Import CSV, FlowFinity `.tsf` and other records into a new or existing site. Place or drag sites and digitise zones on the map. On the time-series chart, set calibration and validation periods by dragging. An OpenStreetMap basemap is **off by default** and asks before the first download, because the tile server sees the area viewed. |
| **Model** | Build the working model by adding processes: rainfall losses (none, initial abstraction with optional snowmelt, drained tanks), any number of unit hydrographs, then other flow components (sanitary pattern, groundwater, ...). Every unit hydrograph, loss and objective registered in sparsehydro is offered, extensions included. The **Working model** dock has a slider, bounds and a calibrate flag for every parameter. Moving a slider re-simulates the model and redraws the hydrograph, every unit hydrograph (unit area, in hours, with shape statistics) and the objectives on the calibration and validation periods. **Components** stacks the hydrograph as its individual hydrographs, and **States & inputs** draws the model's internal states and fluxes (initial abstraction left, tank storage, soil and groundwater stores, snowpack) and the dataset's other inputs (e.g. temperature) in panels under the hydrograph, on the same time axis. **Export trace…** saves all of them to CSV. |
| **Events** | Detect storm events (global events and their sub-events) on the whole record and move between them: list, Previous/Next, or double-click on the chart; **Show all** returns to the record. Fit one or more models (any rain-driven unit hydrograph or the working model), per event and/or **pooled** (one parameter set for all events), compare their NSE event by event, and send any fit to the working model. Events can be excluded from fitting. |
| **Calibrate** | Pick objectives (NSE, KGE, Lin's CCC, log NSE, RMSE, PBIAS, volume error, ... as registered in sparsehydro) and an optimizer (NSGA-II, NSGA-III, SPEA2, GDE3, IBEA, SMPSO, OMOPSO, CMA-ES from Platypus, or SciPy; the Windows installer offers NSGA-II from pymoo and SciPy, see Licence), then run. Each run executes in its own process; the monitor follows one run or overlays all running ones, with convergence (best values, front size, hypervolume) and the front, whose earlier generations can be shown and replayed. Runs queue and can be cancelled at any time. |
| **Explore** | One run's Pareto set: scatter of any two objectives, brushable parallel coordinates over objectives and parameters, the selected solution's hydrograph (with its components) and a band over the filtered solutions, its unit hydrograph and parameters (flagging values at a bound). **Load into sliders** makes a solution the working model. |
| **Compare** | Alternative models side by side: parameter counts, best objectives, NSE, RMSE, AIC and BIC on calibration and validation periods, the MSDGC grade, a complexity-vs-performance plot with the models not beaten by a simpler one, parallel coordinates across runs, and overlaid hydrographs. |
| **Assess** | Grade the working model or a run's solution with the MSDGC calibration criteria (Modeling Guidelines Rev 5.8): Pass, Conditional or Fail (shown in text and symbol as well as colour), each criterion against its limits, observed-vs-model scatter plots of zone and event volumes with tolerance bands, concordance by month group, Qcritical levels and the event table, linked to the hydrograph. |

A project is one SQLite file (`*.shproj`) holding the sites, sensors, zones, attributes, locations and the time
series themselves, plus models, calibration runs and settings, so it can be moved or shared on its own. Tables
follow the water ontology's class and slot names. Projects saved as folders by earlier versions, and projects with
the earlier step-based unit hydrograph parameters, are converted when opened.

## Extensions

Models, unit hydrographs, objectives and solvers registered with sparsehydro appear in the viewer automatically.
Installed packages are found through the `sparsehydro.extensions` entry-point group; modules or `.py` files can
also be listed in the settings (`extensions/modules`). Both are loaded with `sparsehydro.load_extensions()`; a
failing extension is reported, not fatal.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest                            # add -m "not slow" to skip optimizer runs and subprocess calibrations
ruff check src tests
```

Layering: only `sparsehydro_viewer.core` (Qt-free) and `sparsehydro_viewer.services` import sparsehydro.
`widgets` and `views` work with core objects, which a test enforces. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/architecture.md](docs/architecture.md).

The Windows installer is built by the release workflow (also runnable by hand, without publishing): PyInstaller
one-folder build from `packaging/sparsehydro-viewer.spec`, `--self-test` on the frozen executable, then Inno Setup
(`packaging/installer.iss`).

## Licence

MIT, see [LICENSE](LICENSE). The application uses Qt through PySide6 under the LGPLv3; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which also explains why the Windows installer leaves out the
GPL-licensed Platypus optimizers by default.
