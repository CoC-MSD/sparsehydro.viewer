# Compare

The **Compare** page sets alternative models side by side, with the number of parameters as a first-class measure,
so the simplest model that performs nearly as well as the best stands out.

```{image} ../_static/screenshots/compare.png
:alt: Compare page with the run table, the complexity-performance plot, parallel coordinates across runs, the fronts and the chosen solutions of two runs over the whole record.
:class: screenshot
```

- The **run table** lists every finished run: model, dataset, calibrated and total parameters, best objective values
  and, after **Score runs** (<kbd>F5</kbd>), NSE, RMSE, AIC and BIC on the calibration and validation periods with
  the MSDGC grade and Cinci score. Tick the runs to compare.
- The **complexity vs performance** plot puts each run at its parameter count; the step line joins the runs not
  beaten by a simpler one. The marker shape gives the MSDGC grade (circle pass, diamond conditional, cross fail).
  **Show** keeps only passing (or passing and conditional) runs.
- **Parallel coordinates** across all ticked runs have parameter count as an axis; the **Pareto fronts** overlay
  their fronts.
- **Chosen solutions** overlays each ticked run's solution over the whole record, with the calibration and
  validation periods shaded. Each run has its own choice in the list beside the chart: the knee, the best for an
  objective, or a solution picked by clicking it in the parallel coordinates. The same choice is used for scoring.

AIC and BIC assume independent errors; with autocorrelated flows use them to rank models fitted to the same period,
not as a test.
