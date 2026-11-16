# Assess

The **Assess** page grades a model the way the MSDGC Modeling Guidelines (Rev 5.8) do, using
`sparsehydro.studies.msdgc.scorecard`. The criteria are described in [MSDGC calibration criteria](../reference/msdgc).

```{image} ../_static/screenshots/assess.png
:alt: Assess page with the settings, the grade and criteria, and observed-versus-model scatter plots of the zone volumes.
:class: screenshot
```

## Settings

| Setting | Meaning |
| --- | --- |
| Model | The working model at its slider values, or a run's knee solution. |
| Period | Calibration, validation or the whole record. |
| Volume approach | *Storm volume* (base flow adjusted to each storm over the 24 h before it; the official approach) or *total volume*. |
| Zone windows | The v5.0.5 assessment tool's windows (treatment capped at 24 h) or the guidelines' (no cap). |
| Event detection | Inter-event period, minimum event rain, minimum duration and start/end threshold (MSDGC detector). |

## Results

- The **grade** - Pass, Conditional or Fail, in text and with a symbol - and whether it is *official* or
  *provisional*, with the reasons (for example a missing site attribute).
- Each **criterion** with its value, pass range and fail limits.
- **Zone volumes**: observed against model volumes of every event for the conveyance, overflow/storage and treatment
  zones and the whole event, with the 1:1 line and ±10 % / ±20 % bands; Con15 events are ringed and critical-month
  events drawn as triangles. Clicking a point opens that event.
- **Summary**: concordance correlation by month group (all, critical April-July, other months) and the Cinci score.
- **Events**: every event with its volumes and peaks; selecting one zooms the hydrograph to it.

For Qcritical the site needs its *Average dry weather flow (ODWF-A)* and *Sewer system* attributes (Sites page).

Compare grades every scored run the same way.
