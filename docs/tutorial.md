# Getting started

This walk-through takes one monitoring site from raw records to a graded, calibrated model. It uses the three-week
sample that comes with the source code (`tests/data/tc-nb-001_2022-05.csv`: 5-minute rainfall and storm flow at
site TC-NB-001, May 2022); any CSV with a time column, rainfall and flow works the same way.

## 1. Import the data

On the **Sites** page press **Import data** (the toolbar's Run button, <kbd>F5</kbd>). Choose the CSV, check that
the time, rain and flow columns were recognised, set the flow units, and import into a new site. The site appears in
the tree with a rain gauge, a flow meter and the dataset; its series are stored inside the project file.

Give the site a location: select it, turn on **Edit locations** and click the map, or type the longitude and latitude
in the properties on the right. Sewersheds can be drawn with **Draw zone** or imported from a GIS file (see
[Sites and map](guide/sites)).

```{image} _static/screenshots/sites-map.png
:alt: The Sites page with the site tree, a sewershed polygon around the sampled site on the map, and the properties of the selected site.
:class: screenshot
```

## 2. Choose the calibration and validation periods

Open the **Time series** tab. Press **Select calibration** (<kbd>C</kbd>) and drag across the first two weeks, then
**Select validation** (<kbd>V</kbd>) and drag across the last week. The shaded periods can be dragged or resized
afterwards. The dataset now shown in the toolbar's **Dataset** box is the one every page works on.

```{image} _static/screenshots/sites-timeseries.png
:alt: The time-series tab with rainfall above observed flow and the calibration and validation periods shaded.
:class: screenshot
```

## 3. Build a model

On the **Model** page, the **Processes** tab builds the working model step by step:

1. **Rainfall losses** - *Initial abstraction* (optionally with snowmelt).
2. **Runoff routing** - one *RTK triangle*; press **Add unit hydrograph** for a second, slower triangle.
3. **Other flow components** - leave them off for storm flow.

Drag the sliders in the **Working model** panel on the right: the simulated hydrograph, each unit hydrograph and the
objectives for both periods update as you drag. **Components** stacks the hydrograph as its individual unit
hydrographs; **States & inputs** draws the remaining initial abstraction and other internal states underneath.

## 4. Calibrate

On **Calibrate**, tick the objectives (for example NSE and PBIAS), keep NSGA-II as the optimizer and press **Run
calibration**. The run executes in its own process; the convergence chart and the front update as it reports, and
the toolbar's Stop button (<kbd>Shift</kbd>+<kbd>F5</kbd>) cancels it. Start a second run with one triangle to have
an alternative to compare.

## 5. Explore and compare

Double-click a finished run to open it in **Explore**: pick a solution in the Pareto scatter or the parallel
coordinates and see its hydrograph and parameters; **Load into sliders** makes it the working model.

**Compare** puts the runs side by side: the complexity-performance plot shows whether the second triangle pays for
its three extra parameters, and the chosen-solutions chart overlays each run's knee (or any other) solution over the
whole record.

## 6. Grade with the MSDGC criteria

On **Assess**, choose the working model or a run, keep the calibration period, and press **Assess**. The page grades
the model (Pass, Conditional or Fail) with each criterion against its limits, the zone-volume scatter plots and the
event table. Enter the site's average dry weather flow and sewer system in its properties (Sites page) to make the
grade official.

## 7. Save

**Save project** (<kbd>Ctrl</kbd>+<kbd>S</kbd>) writes everything - sites, sewersheds, data, models, runs and
settings - to one `.shproj` file that can be copied or shared on its own.
