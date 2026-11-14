# Improving `glm_regional`: experiments

Branch `improve-experiments`. Nothing in `harmonize/` is changed; the candidates are fitted
on top of `glm_regional` by `scripts/experiments/improve.py` and scored with the same
hold-outs and tiers as METHOD.md. Terra + Aqua, day + night. All numbers are p90 |annual
bias| per country-year, in %.

## Candidates

- **cell**: one factor per 0.25° cell, r = (V + λ)/(E + λ) with E the `glm_regional`
  prediction, then a rescale per 5° tile so that predicted = observed VIIRS in training.
  λ is chosen by an inner even/odd-year CV on the training rows.
- **renorm**: the 5° rescale alone.
- Also tried and dropped: a seasonal factor per 10° or 5° tile (makes unseen countries worse:
  cell-days 23.4 → 31.7 on half A), finer nested tiles of 2° and 1° (smaller gain than the
  cell factor), seasonal GLM features (no gain in unseen years), a 2° block stage before the
  cell stage (same as cell).

The winner was chosen on half A and confirmed on half B
(`outputs_full/improve/tiers_halfA_round1.csv`, `tiers_halfB_confirm.csv`).

## Standard hold-outs, full data (`tiers_full.csv`)

| | tier | glm_regional | cell | renorm |
|---|---|---|---|---|
| hotspots, unseen years | ≥ 10 k | 20.6 | 15.2 | 17.7 |
| | ≥ 1 k | 31.5 | 24.3 | 25.5 |
| cell-days, unseen years | ≥ 10 k | 14.4 | 11.5 | 12.6 |
| | ≥ 1 k | 25.7 | 20.0 | 22.5 |
| FRP, unseen years | ≥ 10 k | 17.5 | 14.2 | 15.0 |
| | ≥ 1 k | 30.3 | 24.3 | 24.1 |
| hotspots, unseen countries | ≥ 10 k | 29.3 | 27.8 | 27.8 |
| cell-days, unseen countries | ≥ 10 k | 23.1 | 21.5 | 21.0 |
| FRP, unseen countries | ≥ 10 k | 24.0 | 21.6 | 21.7 |

## Long-gap test (`scripts/experiments/long_gap.py`, `tiers_long_gap.csv`)

Leave-year-out keeps training years on both sides of the test year. The real back-cast has
none before. Here the model is fitted on one block of years and scored on a separate block.
≥ 10 k tier.

| fit → test | hotspots: base / cell / renorm | cell-days: base / cell / renorm | FRP: base / cell / renorm |
|---|---|---|---|
| 2016-24 → 2012-15 | 22.4 / 16.4 / 16.7 | 11.4 / 11.1 / 11.2 | 18.1 / 13.1 / 13.7 |
| 2019-24 → 2012-15 | 20.1 / 17.8 / 17.7 | 11.9 / 13.1 / 11.9 | 18.7 / 14.6 / 15.3 |
| 2019-24 → 2012-13 | 21.5 / 19.5 / 16.7 | 10.7 / 15.1 / 11.7 | 17.1 / 13.6 / 13.9 |
| 2015-21 → 2012-13 | 21.1 / 16.6 / 16.0 | 11.3 / 12.7 / 11.6 | 17.0 / 12.0 / 11.9 |
| 2012-20 → 2021-24 | 22.0 / 18.0 / 21.2 | 17.8 / 15.1 / 17.9 | 19.8 / 20.0 / 20.5 |
| 2012-17 → 2021-24 | 23.3 / 17.4 / 22.0 | 18.4 / 15.7 / 18.0 | 20.3 / 20.2 / 20.7 |
| 2012-17 → 2023-24 | 21.0 / 16.7 / 20.9 | 19.0 / 19.0 / 19.0 | 20.2 / 20.0 / 19.8 |

## Reading

- **Hotspots: the cell factor is better in all seven splits** (by 2 to 6 points).
- **FRP: better in the four backward splits** (by 3.5 to 5 points), equal in the forward ones.
- **Cell-days: not better going backwards.** Equal at a 1-4 year gap, worse in the other three
  backward splits (by 1.2 to 4.4 points). The worst case is fitted on 2019-2024 only, the
  years of Terra's orbit drift. It is better going forwards.
- **The 5° rescale alone is the safe variant.** For cell-days it is within 1 point of the
  current model in every split, and it keeps most of the hotspot and FRP gain going backwards.
- In the backward splits the current cell-days model (10.7-11.9) is still the best single
  number, ahead of corrected hotspots (16.4-19.5) and corrected FRP (12.0-14.6).

Not tested: Terra-only and Aqua-only fits, day and night separately, the 2011/2012 step and
the 31-country back-cast series.
