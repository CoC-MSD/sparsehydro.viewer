# sparsehydro.viewer

Desktop workbench for [sparsehydro](https://github.com/CoC-MSD/SparseHydro): load rainfall and flow,
build a model, see every parameter change in the hydrograph and in objective space as you drag a slider,
calibrate with multi-objective optimizers, and compare alternative models with parameter count as a
first-class axis, so the most parsimonious adequate model stands out.

Built on PySide6 (Qt for Python) and pyqtgraph.

## Install

```bash
pip install sparsehydro-viewer
sparsehydro-viewer            # or: python -m sparsehydro_viewer [project-folder]
```

Windows users without Python can use the installer attached to each
[GitHub release](https://github.com/CoC-MSD/sparsehydro.viewer/releases).

Until sparsehydro is published on PyPI, install it first from source:

```bash
pip install "sparsehydro @ git+https://github.com/CoC-MSD/SparseHydro@dev"
```

## Workspaces

| Workspace | What it does |
| --- | --- |
| **Data** | Load a CSV (any column names, mapped in the form) or FlowFinity rain + flow `.tsf` files; convert flow units; inspect the record. Set calibration and validation periods by dragging on the chart (toolbar: pan, zoom box, select calibration/validation, fit, zoom to period, export), by dragging the shaded regions, or in the date fields. |
| **Model** | Compose the working model from components; there are no preset models. Flow components: sum of terms, RDII (an abstraction plus any number of unit hydrographs of any type), excess → UH, sanitary pattern (hour/day/month), or any UH used directly. Abstractions: initial abstraction (optional snow) or drained tanks. UHs: gamma, Nash, triangle, rectangle, decay, delayed gamma, peak + tail, RTK triangle. For example: sanitary + RDII(IA; gamma, Nash, RTK). The **Working model** dock groups parameters by component and has a slider, bounds and a calibrate flag for each, vector elements included. Moving a slider re-simulates the model, redraws the hydrograph and every unit hydrograph (unit area, in hours, with time to peak, centroid, t50 and t95), and updates the objectives for the calibration and validation periods. |
| **Events** | Detect storm events (global events and their sub-events), fit one unit hydrograph per global event, and step through them in four views: data fitting, UH shapes, convolution and fit weights, per event or for the whole record. Events can be excluded from fitting. |
| **Calibrate** | Pick objectives (NSE, KGE, Lin's CCC, log NSE, RMSE, PBIAS, volume error, ...) and an optimizer (NSGA-II, NSGA-III, SPEA2, GDE3, IBEA, SMPSO or SciPy), then run. Each run executes in its own process with live convergence and front plots, and can be cancelled at any time. |
| **Explore** | One run's Pareto set: scatter of any two objectives, brushable parallel coordinates over objectives and parameters, the selected solution's hydrograph with a band over the filtered solutions, its unit hydrograph and parameters (flagging values at a bound). The current slider point is shown in both objective views. **Load into sliders** makes a solution the working model. |
| **Compare** | Alternative models side by side: parameter counts, best objectives, NSE, RMSE, AIC and BIC on calibration and validation periods, a complexity-vs-performance plot with the models not beaten by a simpler one, parallel coordinates across all runs with parameter count as an axis, and overlaid hydrographs. |

Projects are folders (`project.json` plus `runs/*.npz`) that can be moved or shared together with their data.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest                            # add -m "not slow" to skip subprocess calibrations
ruff check src tests
```

Layering: only `sparsehydro_viewer.core` (Qt-free) and `sparsehydro_viewer.services` import
sparsehydro. `widgets` and `views` work with core objects, which a test enforces. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/architecture.md](docs/architecture.md).

## Licence

MIT, see [LICENSE](LICENSE). The application uses Qt through PySide6 under the LGPLv3; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
