# MODIS ↔ VIIRS hotspot harmonization (NASA Space Apps prototype)

This tool turns NASA FIRMS active-fire hotspots from MODIS (2000+) and VIIRS (2012+) into one
monthly, gridded (0.25°) fire-activity series in **VIIRS-equivalent units**. It works for any
country, any mix of countries, or the whole globe, and for any years.

The calibration is regional. A Poisson GLM uses MODIS-side fire characteristics (FRP per
detection, density, view angle, Terra/Aqua mix) and adds a shrunken regional correction.
Recalibrated on all 236 FIRMS countries, 2012-2024 (`outputs_full/`), the recommended product
is fire cell-days with `glm_regional`. For country-years with ≥ 10 000 VIIRS detections, the
p90 of the annual-total error is 23 % in countries the model never saw and 14 % in held-out
years of seen countries, which is the 2000-2011 back-cast case. See `METHOD.md` §6.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m harmonize.pipeline --data-dir data_global --out-dir outputs_global
.venv/bin/python -m pytest -q
```

Put any FIRMS archive CSVs, or FIRMS zips, in the data folder. Countries, years and sensors
can be mixed, and the pipeline works out which places and days each sensor covers. The
per-country yearly files need no API key:

```bash
B=https://firms.modaps.eosdis.nasa.gov/data/country
curl -O $B/modis/2019/modis_2019_Brazil.csv
curl -O $B/viirs-snpp/2019/viirs-snpp_2019_Brazil.csv
```

**Back-cast a MODIS-only period** (for example 2000-2011) with a saved calibration:

```bash
.venv/bin/python -m harmonize.pipeline --data-dir data_2005 --out-dir out_2005 \
    --coefficients outputs_global/calibration_coefficients.json
```

## Outputs

| file | content |
|---|---|
| `harmonized.csv` / `.parquet` | per cell × month × D/N/ALL: `viirs_raw`, `modis_raw`, `modis_as_viirs_equivalent`, `harmonized_value`, `source_flag` (VIIRS / MIXED / MODIS_CALIBRATED) |
| `calibration_coefficients.json` | every fitted model plus the recommendation; reusable via `--coefficients` |
| `hotspots_clean.parquet` | filtered points in the common schema, for downloads |
| `validation/`, `plots/` | hold-out scores (by country, year, spatial block and month) and figures |

## Docs and options

- `SCHEMA.md`: the data contract.
- `METHOD.md`: choices, results and limitations.
- Global scale, in parts (`METHOD.md` §9): `--paired-only` per half or year, then
  `--from-paired a.parquet b.parquet ...` to calibrate and validate on the union, with
  `--jobs N` for parallel folds. `python -m harmonize.crosstest` fits on one part and scores
  another.
- Options: `--cell-size 0.25`, `--time-step month|day`, `--keep-types 0`,
  `--min-confidence nominal`, `--points-format parquet|csv|both`, `--skip-validation`
  (much faster on very large inputs).
