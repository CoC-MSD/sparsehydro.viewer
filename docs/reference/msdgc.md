# MSDGC calibration criteria

The Assess page and the Compare grade apply the compliance check of the MSDGC Modeling Guidelines, Revision 5.8
(October 2025), Volume II, as implemented in `sparsehydro.studies.msdgc.scorecard.assess_calibration`.

## Volumes

- **Storm volume** (6.4.1, the official approach): observed and modelled base flows are each adjusted, storm by storm,
  to match their total flow over the 24 hours before the event, then subtracted. **Total volume** (6.4.2) compares
  total flows directly.
- **Zones** (6.4.3): within each event, the largest moving-window volume over three windows whose length follows the
  event's duration - *conveyance*, *overflow/storage* and *treatment* - found independently for observed and
  modelled flow. The v5.0.5 assessment tool caps the treatment window at 24 hours; the guidelines' Table 6-1 does
  not. Both are offered.

## Criteria (7.1)

| Criterion | Pass | Fail |
| --- | --- | --- |
| Lin's concordance correlation of zone volumes, for each of conveyance, overflow/storage and treatment | ≥ 0.90 | (below 0.90 is not a pass) |
| Qcritical: error in the volume above the system capacity Qc1 | within ±10 % | beyond ±20 % |
| Con15: zero-intercept slope of modelled on observed conveyance volumes of the largest 15 % of events, as a percent error | within ±10 % | beyond ±20 % |

Any fail fails the calibration; all passing passes it; anything else is a **conditional** pass. The mean of the three
concordance correlations is reported as the **Cinci score**, and the correlations are reported for all months, the
critical months (April-July) and the other months (Table 7-3).

## Qcritical levels (Table 7-2)

Qc1 is a factor times the site's average observed dry weather flow (ODWF-A):

| Volume approach | Combined system | Sanitary system |
| --- | --- | --- |
| Total volume | 2.5 × ODWF-A | 1.5 × ODWF-A |
| Storm volume | 1.5 × ODWF-A | 0.5 × ODWF-A |

Qc2 to Qc4 split the range from Qc1 to the largest observed event peak into equal parts and are reported; the grade
uses Qc1.

## Official and provisional grades

The grade is *official* only when every input the guidelines take from elsewhere is available. Otherwise it is marked
*provisional* with the reasons, for example:

- no average dry weather flow (ODWF-A) for the site, so Qcritical cannot be computed;
- no sewer system given (sanitary is assumed);
- no separate base flow (the flows are taken as storm flow).

## Open points

- Whether Qc2 to Qc4 divide the range into thirds (the guidelines' text read literally, used now) or quarters
  ("quartile-based" elsewhere in the text).
- Parity with the MSDGC .NET assessment tool is to be confirmed on a site's exported scorecard (tables D1-6 and D1-8).
- Depth and velocity compliance are not part of this check.
