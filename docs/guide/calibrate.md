# Calibrate

The **Calibrate** page optimises the working model's ticked parameters against the chosen objectives on the
calibration period.

```{image} ../_static/screenshots/calibrate.png
:alt: Calibrate page with objectives, optimizer settings, the run table, convergence and the final front with earlier generations faded behind it.
:class: screenshot
```

## Objectives

Tick the objectives to optimise and drag them into order; the arrow says whether higher or lower is better. Every
objective registered in sparsehydro is offered: NSE, KGE, Lin's concordance correlation, index of agreement, log
NSE, MAE, MSE, RMSE, peak-weighted MSE, PBIAS, volume error and others from extensions. Objectives with options
show them below the list when selected.

## Optimizers

| Optimizer | Kind | Notes |
| --- | --- | --- |
| NSGA-II (Platypus) | multi-objective | The default where Platypus is installed (pip). |
| NSGA-II (pymoo) | multi-objective | Offered where Platypus is not installed (the Windows installer). |
| NSGA-III, SPEA2, GDE3, IBEA | multi-objective | Platypus; NSGA-III suits three or more objectives. |
| SMPSO, OMOPSO | multi-objective | Particle swarms (Platypus); OMOPSO keeps one solution per ε-box. |
| SciPy, CMA-ES | single objective | Optimise one objective (*Objective #*) and return one solution. |

Only installed optimizers are listed. A project saved with an NSGA-II that is not installed here switches to the
other one at the same evaluation budget, with a note.

## Runs

**Run calibration** (<kbd>F5</kbd>) starts a run in its own process, so the window stays responsive; runs beyond
two queue. The table shows each run's model, parameter counts, optimizer, status, a progress bar, reports and
elapsed time. Stop (<kbd>Shift</kbd>+<kbd>F5</kbd>) cancels the selected runs (or all); optimizers without progress
reports are stopped by ending their process. Double-click a run to explore it; **Use run settings** loads its model,
objectives and optimizer back into the editors.

## Following a run

The **Show** box chooses what the charts display: the run selected in the table, any particular run, or **all
running runs** overlaid in their own colours.

- **Convergence** plots the best value of an objective at each report, or the front's size, or its **hypervolume**
  (objectives scaled over the run's history; higher means a better and wider front).
- **Current front** shows the front in any two objectives. **Earlier generations** draws the fronts of earlier
  reports behind it, fainter the older they are, and the slider replays the run report by report (it follows a
  running calibration until you drag it back).
