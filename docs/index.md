# SparseHydro Viewer

SparseHydro Viewer is a desktop workbench for [sparsehydro](https://github.com/CoC-MSD/SparseHydro) models of
rainfall-derived inflow and infiltration (RDII) and other flow responses. It keeps monitoring sites, sewersheds and
their rainfall and flow records in one project file, lets you build a model one hydrological process at a time and
see every parameter change in the hydrograph as you drag a slider, fits storm events, calibrates with
multi-objective optimizers, compares alternative models with the number of parameters as a first-class measure, and
grades a model against the MSDGC calibration criteria.

```{image} _static/screenshots/model-components.png
:alt: The Model page: rain and observed flow above the simulated hydrograph split into its two unit hydrographs, the unit hydrograph shapes below, and the working-model sliders on the right.
:class: screenshot
```

Developed by Caleb Buahin on behalf of **MSDGC** (Metropolitan Sewer District of Greater Cincinnati) by
**Hazen and Sawyer**.

::::{grid} 1 2 2 3
:gutter: 2

:::{grid-item-card} Get started
:link: tutorial
:link-type: doc
Install, then follow one site from raw data to a graded, calibrated model.
:::

:::{grid-item-card} Workspaces
:link: guide/interface
:link-type: doc
The shared toolbar and status bar, then one page per workspace.
:::

:::{grid-item-card} Reference
:link: reference/project-file
:link-type: doc
Project file and ontology mapping, MSDGC criteria, extensions, architecture, API.
:::
::::

```{toctree}
:caption: Getting started
:maxdepth: 1

install
tutorial
```

```{toctree}
:caption: User guide
:maxdepth: 1

guide/interface
guide/sites
guide/model
guide/events
guide/calibrate
guide/explore
guide/compare
guide/assess
guide/shortcuts
```

```{toctree}
:caption: Reference
:maxdepth: 1

reference/project-file
reference/msdgc
reference/extensions
architecture
reference/api
```
