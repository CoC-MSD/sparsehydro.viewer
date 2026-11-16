# Explore

The **Explore** page studies one run's Pareto set: the trade-offs between objectives and what each solution looks
like.

```{image} ../_static/screenshots/explore.png
:alt: Explore page with the Pareto scatter, parallel coordinates, the selected solution's hydrograph and its parameters.
:class: screenshot
```

- The **Pareto scatter** shows any two objectives; click a point to select a solution.
- **Parallel coordinates** run over the objectives and the parameters; drag along an axis to keep only the solutions
  in that range (brushing), on as many axes as needed. The hydrograph then shows a band over the remaining
  solutions.
- The selected solution's **hydrograph**, its **unit hydrographs** and its **parameters** are shown, with values at a
  bound flagged - a hint that the bound, not the data, decided the value.
- **Knee** (<kbd>K</kbd>) selects the balanced solution of the front, and **Best for** the best one for an objective.
- **Components** stacks the solution's hydrograph as its parts, as on the Model page.
- **Load into sliders** makes the run's model the working model with the selected solution's values.

The working model's current values appear as a star in the scatter and a dashed line in the parallel coordinates.
