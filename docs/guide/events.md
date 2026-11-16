# Events

The **Events** page detects storm events on the whole record - global events and the sub-events inside them - and
fits one or more models to them, one parameter set per event and/or one for all events together.

```{image} ../_static/screenshots/events.png
:alt: Events page: the whole record with the events shaded and zoomed to the first event, fits of two unit hydrographs overlaid, the event list and the event details.
:class: screenshot
```

## Navigating

The hydrograph always holds the whole record with the global events shaded. Choosing an event - in the list, with
**Previous**/**Next** (<kbd>←</kbd>/<kbd>→</kbd>), from the comparison table, or by double-clicking its span - zooms
to it; **Show all** (<kbd>Home</kbd>) returns to the record. The list can be grouped by season or quarter and sorted
by start, rain, peak flow or NSE. **Exclude event** leaves the selected event out of the fits (stored in the
project); **Restore** brings excluded events back.

## Models to fit

Add any unit hydrograph that works directly on rain (**Add**), or the working model (**Add working model**, with its
structure, bounds and current values as the start). For each, tick:

- **Per event** - one parameter set per global event, each fit starting from the previous event's values (*warm
  start*), weighted towards the peaks of the sub-events (*peak weight*) and less elsewhere (*tail weight*);
- **Pooled** - one parameter set for all events at once, with the same weights.

**Detect and fit** (<kbd>F5</kbd>) runs everything with progress across all fits; Stop cancels between events. A
model that fails does not lose the others.

## Views

| Tab | Shows |
| --- | --- |
| 1 Hydrograph | Rain, observed and smoothed flow, each model's prediction (pooled dashed), detected peaks. |
| 2 UH shapes | The selected event's unit hydrograph against those of all events (first per-event model). |
| 3 Weights | The fit weight along the record. |
| 4 Comparison | NSE of every model and mode for every event and on average; the best per event in bold. |

```{image} ../_static/screenshots/events-comparison.png
:alt: Comparison table of NSE by event for each model, per event and pooled.
:class: screenshot
```

**Use as working model** sends the selected configuration to the Model page with its pooled values, or the selected
event's values when it was fitted per event only.

Adding, splitting and merging events by hand and editing peaks need support in sparsehydro's event detection that is
not available yet; exclusion is.
