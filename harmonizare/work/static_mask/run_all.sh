#!/bin/bash
# Rebuild everything (each step < 100 s; rerun step 1 until it prints ALL DONE). From the project folder:
#   bash harmonizare/work/static_mask/run_all.sh
set -e
python3 harmonizare/work/static_mask/01_cellyear.py 70 | tail -1
python3 harmonizare/work/static_mask/05_tn0.py
cd harmonizare/work/static_mask
python3 02_cells.py; python3 02_cells.py   # second call finishes remaining years
python3 03_features.py
python3 06_final.py   # mask + cell_static_share + impact tables
python3 07_sites.py >/dev/null && python3 09_top_sites.py >/dev/null
python3 08_fig.py
