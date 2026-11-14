# simul_overpass: Aqua-MODIS vs S-NPP-VIIRS seen at the same time (|Δt| ≤ 10 min)

## 1. Answer first
1. **MODIS detection curve, measured** (2015, 2019, 2021; 4.26 M VIIRS ~1 km clusters, of which 3.76 M day and 0.50 M night). The table gives the cluster FRP at which Aqua detects with 50% / 90% probability (tolerant match):
   - Day, all scans: 14 / 125 MW.
   - Day by scan: nadir (1.0–1.5 km) 10 / 72 MW; 1.5–2 km 14 / 99; 2–3 km 19 / 143; edge (3–4.8 km) 32 / 271 MW.
   - Night: all 8.7 / 48 MW; nadir 6.7 / 31 MW; edge 11.8 / 91 MW.
   - Night thresholds are lower and the swath edge is about 3× worse than nadir by day. Both are what the physics predicts.
   - Even for fires ≥100 MW, P only reaches 0.88. About 10% of misses do not depend on fire size (clouds, timing, geolocation).
2. **MODIS cannot see most VIIRS detections, but it sees most of the FRP.** In cells where Aqua was looking, Aqua missed:
   - Day: 60% of VIIRS clusters, 52% of VIIRS pixels, 33% of VIIRS FRP.
   - Night: 75% of clusters, 66% of pixels, 37% of FRP.
3. **When both sensors see the same fire, summed FRP is close to conserved.** Inside the MODIS footprint, ΣFRP_VIIRS / FRP_MODIS is 0.93 at nadir and 1.02 at the edge by day (overall 0.95), and 0.94 overall at night.
   - Day polynomial: R(s) = 0.925 + 0.0013·s + 0.0039·s² (RMS residual 0.013). Night: R(s) = 0.844 + 0.049·s + 0.0006·s² (RMS 0.067).
   - Per pixel the scatter is large: 16–84% of pixels fall between 0.24 and 1.8 (log10 SD 0.41).
   - So FRP needs only a small scan correction. Counts are what differ.
4. **No single FRP floor is a reasonable pseudo-MODIS.** Clusters are scored as kept/dropped against "Aqua detected" (tolerant match).
   - Day, 10 MW floor: cluster count matches (1.02×) but FRP comes out 23% too high; precision 0.62, recall 0.63.
   - Day, 20 MW floor: FRP matches (1.01×) but counts halve (0.52×).
   - Night: 5 MW matches counts (1.08×, FRP +25%, precision 0.58, recall 0.63); 10 MW matches FRP (1.03×, counts 0.52×).
   - Recommendation: apply the scan-dependent logistic curve probabilistically (`detection_curve_fit.csv`), or calibrate counts and FRP separately.
5. **Grid-cell scale** (2015, 2016, 2019, 2020, 2021; 161–188 k day and 14–18 k night coincident cell-overpasses per year; 80% between 30°S and 20°N):
   - VIIRS/Aqua FRP ratio: 0.85–0.88 day (stable across years), 1.13–1.46 night.
   - Count ratio: 3.0 day, 8.9–11.5 night.
   - S-NPP fire cells where Aqua was demonstrably looking: Aqua also detected fire in 50% (day) / 24% (night), and those cells hold 85% / 82% of the S-NPP FRP.
   - The reverse: S-NPP saw 93% / 98% of Aqua's fire cells.

## 2. What I built
Scripts are in `work/simul_overpass/` and are run from that folder. Outputs are in `rezultate/simul_overpass/`.
- `s1_pairs.py <years>` → `s1_summary.py`: overpass pairing and one-sided rates → `s1_*.csv`.
- `s3_detect.py <year> <months>` → `s3_fit.py`: detection curve → `fig_detection_curve.png`, `detection_curve_fit.csv`, `detection_curve_bins.csv`.
- `s2_footprint.py <year> <months>` → `s2_fit.py`: footprint FRP comparison → `fig_frp_ratio_vs_scan.png`, `frp_ratio_vs_scan.csv`, `frp_ratio_vs_scan_polyfit.csv`.
- `s5_floor.py`: FRP-floor test → `viirs_frp_floor.csv`.
- Rerunning needs the `op_*` grid files, which have now been deleted, and `data/points` for 2015, 2019 and 2021.

## 3. Method in plain words
- **Pairing:** an Aqua overpass and an S-NPP overpass in the same 0.25° cell within 10 minutes.
- **"Aqua was looking":** Aqua detected fire in one of the 8 neighbouring cells within ±10 min. The own cell is excluded, so isolated fires are not counted as seen just because Aqua detected them.
- **Clusters:** S-NPP pixels (type 0, confidence ≥ nominal) of one overpass, grouped into 0.01° sub-cells with their FRP summed.
- **Footprint box:** a MODIS footprint is a box of scan km east–west by track km north–south. That the scan runs exactly east–west is an approximation.
- **Strict vs tolerant match:**
  - *Strict*: the cluster centroid lies inside the nominal box.
  - *Tolerant*: the box is doubled. MODIS's along-scan sensitivity is triangular and twice the pixel width, and geolocation offsets add to that.
  - Strict matching flags 36% of day MODIS pixels as "no VIIRS inside"; with the 2× box this falls to 7.8% (night: 2.6%). So most strict misses are box geometry, not real MODIS-only fires. That is why tolerant is the headline.
  - Strict results for comparison: P50 = 36 MW day / 19 MW night; a fit with a plateau gives a top of 0.79 / 0.82.
- **View-geometry proxy:** Aqua's mean scan size in the same cell and overpass, or in the neighbouring cells if Aqua had no detection there. It is a proxy, not the true scan angle at the cluster.
- **Logistic fit:** binomial maximum likelihood in log10(FRP).

**VIIRS pixels per MODIS pixel** (when at least one): day 2.0 at nadir → 5.5 at the edge; night 3.4 → 12.0. The footprint area ratio is 7.8 → 60, so fires fill only a small part of a MODIS pixel.

## 4. Caveats
- **Measured:** everything above.
- **Assumed:** box footprints, the scan proxy, and the 0.01° sub-cell as the "fire" unit (not a MODIS pixel).
- The floor test compares VIIRS clusters with detected clusters, not with MODIS pixel counts.
- "Was looking" favours fire-active areas.
- 1–10 min of fire evolution between the two views is included.
- Step 4 (duplicates) was skipped on request.

## 5. Needs
None. The intermediate files have been deleted. Only the scripts and these outputs remain.
