#!/bin/bash
# Fetch the team's VIIRS-to-MODIS tables (Ianis's model, branch ianis_harmonization of the team
# repository) into data/modis_scale_tables/, where tools/build_world.py reads them:
#
#     tools/get_model_tables.sh
#
# About 340 MB, one file per year. They stay out of git (data/ is never committed) and are not
# uploaded to the website. The MODIS-to-VIIRS table (Louis's model) is small enough to live in
# git: tables/viirs_scale_cells.parquet.
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="$(git -C "$APP" remote | grep -x upstream || echo origin)"
DEST="$APP/data/modis_scale_tables"
git -C "$APP" fetch -q "$REMOTE" ianis_harmonization
rm -rf "$DEST"
mkdir -p "$DEST"
git -C "$APP" archive FETCH_HEAD harmonizare/APP_DATA/cells_monthly | tar -x -C "$DEST" --strip-components=3
echo "$(ls "$DEST" | wc -l | tr -d ' ') tables in $DEST"
