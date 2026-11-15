You are working in Lucille's Fire Globe app folder (the one with index.html, app.js, tools/, data/).
The team repository (git remote "upstream", louisdenaiffe/modis-viirs-harmonization) now has the
final version of the app on branch main, in its webapp/ folder. It replaces the provisional
MODIS view and the per-tile ratios with the team's two conversion models. Your job: bring that
version into this folder, rebuild the data, check it, and then (after asking Lucille) deploy.
Read webapp/HOW_IT_WORKS.md section 4 and webapp/README.md "Update the data" on upstream/main first.

1. Do not run tools/publish_to_team.sh yet. It mirrors this folder over webapp/ with --delete,
   so running it before step 2 would overwrite the new version with the old one.

2. Bring the new code in.
   - git fetch upstream main lucille-fire-globe-v2
   - First compare this folder with upstream/lucille-fire-globe-v2:webapp (ignore data/, .firms_key,
     .gitignore, .wrangler/). main was built on commit 5849ac8 of that branch. If this folder has
     changes that are not in it, stop and show them to Lucille: they must be merged by hand, not
     overwritten.
   - If there are none: git archive upstream/main webapp | tar -x --strip-components=1 -C .
   - Changed files: app.js, index.html, tools/build_world.py, tools/deploy.sh, the three .md files.
     New: tools/get_model_tables.sh, tables/viirs_scale_cells.parquet (49 MB, the MODIS-to-VIIRS model).
     Leave data/raw/ and .firms_key alone.

3. Get what the build needs.
   - pyarrow, in the Python that runs build_world.py (it already has numpy and pandas).
   - tools/get_model_tables.sh fetches the VIIRS-to-MODIS tables from upstream branch
     ianis_harmonization into data/modis_scale_tables/. It has not been tested on this machine:
     check that it leaves 26 files, final_2000.parquet to final_2025.parquet (about 340 MB). If it
     fails, do the same by hand: git archive of harmonizare/APP_DATA/cells_monthly from that branch.

4. Rebuild (README step 2; about 45 minutes; needs about 5 GB free for data/_build):
   python3 tools/build_world.py data/raw/world data/_build World \
       --viirs-scale tables/viirs_scale_cells.parquet --modis-scale data/modis_scale_tables
   Only if it ends without error, swap it in with the rm / mv lines of the README (they now also
   remove data/factors and data/countries.bin).

5. Check the build before going further. Report these to Lucille:
   - data/meta.json has "version": 3, and data/factors/ exists.
   - The last two lines the build prints: the share of each table "in cells where this build has
     no hotspot" should be far below 1% (it was 0.002% and 0.03% on a 2000-2024 test build).
   - data/build_report.csv: viirs_scale should be 20 to 24 million a year for 2003-2011 and close
     to the viirs column for 2013-2020; modis_scale about 2.5 to 3.2 million a year.
   - 2025 and 2026 were not in the test build, so look at those two rows with care. The MODIS
     scale for 2026 is a stopgap (the tables stop in December 2025) and may read about 10% low.

6. Country totals: start tools/serve.py, open http://localhost:8765/?precompute and wait for
   "Saved data/countries.bin" in the bottom-left bar.

7. Test in the browser at http://localhost:8765:
   - no errors in the console;
   - search Brazil: the panel opens; switch VIIRS / MODIS; the MODIS view is labelled
     "MODIS Aqua-equivalent hotspots" and Brazil's total for 2000-2024 is about 6.08 million;
   - draw a small rectangle with Shift + drag and download both CSV files; the hotspot file has
     two weight columns (viirs_equivalent_weight, modis_aqua_equivalent_weight);
   - Play runs, and the fire map dims when switched to MODIS.

8. Stop and ask Lucille before anything leaves this computer. Then, if she agrees:
   - tools/deploy.sh (it now also uploads data/factors and gzips the block files);
   - tools/publish_to_team.sh "Both scales from the team's models" (this pushes to branch
     lucille-fire-globe-v2). Do not push to main yourself.

If a step fails, report the exact error and what you checked; do not change build_world.py's
weights or the model tables to make a check pass.
