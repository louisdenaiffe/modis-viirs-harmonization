# MODIS ↔ VIIRS hotspot harmonization (NASA Space Apps prototype)

Drop FIRMS archive CSVs (any country/year, MODIS C6.1 and/or VIIRS 375 m) into `data/`, then:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m harmonize.pipeline          # everything -> outputs/
.venv/bin/python -m pytest -q                   # tests
```

* `SCHEMA.md`: the data contract (point table, aggregated table, coefficients JSON, harmonized.csv)
* `METHOD.md`: choices, results and limitations
* Options: `--cell-size 0.25 --time-step month|day --keep-types 0 --min-confidence nominal --coefficients <json>`
