# Model

The **Model** page builds the *working model*: the model the sliders move, Calibrate starts from, and Explore and
Compare mark with a star.

```{image} ../_static/screenshots/model.png
:alt: Model page with the process builder, the simulated and observed hydrograph, unit hydrograph shapes and the working-model sliders.
:class: screenshot
```

## Building the model

The **Processes** tab grows a model one process at a time:

1. **Rainfall losses** - none, *initial abstraction* (optionally with degree-day snowmelt, which needs a temperature
   column), or drained tanks.
2. **Runoff routing** - any number of unit hydrographs of any type registered in sparsehydro: RTK triangle, gamma,
   Nash cascade, Clark, ModClark, SCS, Snyder, Weibull, lognormal, mixtures, peak + tail and others, plus those of
   installed extensions. The rainfall excess is shared between them by fractions *R*.
3. **Other flow components** - a sanitary (dry-weather) pattern by hour, day of week and month, and groundwater
   infiltration.

Values follow their process when the design changes, so adding a second unit hydrograph keeps the first one's
tuning. The **Advanced** tab edits the component tree directly. There are no preset models.

## The Working model panel

Each parameter has a calibrate tick, its bounds, a slider (logarithmic when the range spans orders of magnitude), a
value box and a reset button; the tooltip gives its meaning, units and range. Moving a slider re-simulates the model
on a background thread and redraws the hydrograph, every unit hydrograph (unit area, in hours, with time to peak,
centroid, t50 and t95) and the objectives on the calibration and validation periods. Unit hydrographs whose upper
bounds allow responses too slow for the record are flagged on their sliders and explained under the objectives.

## Components and internal states

**Components** shows the simulated hydrograph as the sum of its parts - each unit hydrograph, the sanitary term,
each part of a peak + tail or mixture unit hydrograph - stacked under the total.

```{image} ../_static/screenshots/model-components.png
:alt: The simulated hydrograph stacked as two RTK unit hydrographs under the observed flow.
:class: screenshot
```

The **States & inputs** tab lists the dataset's other inputs (for example temperature) and the model's internal
states and fluxes by component: remaining initial abstraction, tank storage, soil and groundwater stores, snowpack
and melt. Ticked series are drawn in panels under the hydrograph, one per unit, on the same time axis, so they pan
and zoom together. **Export trace...** saves the whole record's simulation with every component, state and flux to
CSV, with a second file describing each column.

States and components are computed only while they are shown, so the sliders stay fast otherwise.
