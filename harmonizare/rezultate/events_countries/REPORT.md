# events_countries — famous-fires test + country table (14 Nov)

## 1. Answer first
- **The harmonized record finds famous fires in both eras.** 30 documented events. MODIS era (real Aqua, 18 events): 13 are the #1 month for their calendar month since 2003 ("top 5%"), and 15 are top 10%. VIIRS era (converted S-NPP, 2022+, 12 events): 8 are top 5% and 10 are top 10%. **None of the 6 quiet controls is flagged** (their best rank is 6/23, by FRP).
- **The naive splice is biased toward recent years.** In the naive record (Aqua to 2011, raw VIIRS from 2012), 2012+ years take **55 of the 60** top-2 slots across the event boxes. Chance would give about 37; the harmonized record gives 35. Examples from the naive record: Balkans Jul-2007 drops from #1 to #7 because 6 ordinary VIIRS Julys beat it; Black Saturday drops to #3; a quiet Russia Aug-2013 rises to #3.
- **Misses are real but moderate, not errors.** Amazon Aug-2019 (9/23), Bolivia 2019 (9/23), Amazon Sep-2024 (7/23): widely covered, but 2003-2010 burned more, matching INPE. Algeria Aug-2021: 3/23. Romania 2025 (126k ha, EFFIS): 13/23, nothing unusual in the record.
- **Small fires get flagged on tiny numbers.** Maui (17 detections), Ofunato (8), Valparaiso (63) are #1 only because their baseline is near zero; under 100 detections the error is ±25-35%. Show the count next to any badge.
- For Romania, spring 2022 (Mar) ranks **2/23** (top 10%), which agrees with Romsilva's report of 7x more forest fires.

| id | event | peak month | era | n_eq | rank same month n/frp (of 23) | rank all months (of 276) | naive rank same/all |
|---|---|---|---|---|---|---|---|
| GR07 | Greece Peloponnese | 2007-08 | aqua | 1157 | 1/1 | 1 | 2/2 |
| BAL07 | Balkans | 2007-07 | aqua | 2648 | 1/1 | 1 | 7/33 |
| AU09 | Black Saturday | 2009-02 | aqua | 1561 | 1/1 | 5 | 3/25 |
| RU10 | W Russia | 2010-08 | aqua | 8880 | 1/1 | 3 | 1/12 |
| ID15 | Indonesia | 2015-09 | aqua | 26475 | 1/1 | 1 | 1/1 |
| CA16 | Fort McMurray | 2016-05 | aqua | 2330 | 1/1 | 1 | 1/1 |
| CL17 | Chile | 2017-01 | aqua | 5150 | 1/1 | 1 | 1/1 |
| PT17a | Pedrogao Grande | 2017-06 | aqua | 226 | 1/1 | 13 | 1/6 |
| PT17b | Portugal 15-Oct | 2017-10 | aqua | 1068 | 2/1 | 10 | 1/4 |
| AM19 | Amazon | 2019-08 | aqua | 39576 | **9/8** | 22 | 2/8 |
| BO19 | Bolivia | 2019-09 | aqua | 24384 | **9/7** | 16 | 2/4 |
| ID19 | Indonesia | 2019-09 | aqua | 21039 | 2/2 | 5 | 2/3 |
| AU19 | Black Summer | 2019-12 | aqua | 20652 | 1/1 | 1 | 1/1 |
| US20 | California | 2020-09 | aqua | 11850 | 1/1 | 1 | 1/1 |
| TR21 | SW Turkey | 2021-08 | aqua | 795 | 1/1 | 1 | 1/1 |
| GR21 | Greece Evia | 2021-08 | aqua | 871 | 2/2 | 2 | 1/1 |
| DZ21 | Algeria | 2021-08 | aqua | 965 | **3/3** | 3 | 2/2 |
| SA21 | Yakutia | 2021-08 | aqua | 53058 | 1/1 | 1 | 1/1 |
| RO22 | Romania spring | 2022-03 | viirs | 1518 | 2/2 | 3 | 2/2 |
| CL23 | Chile | 2023-02 | viirs | 4957 | 1/1 | 1 | 1/1 |
| CA23 | Canada | 2023-09 | viirs | 37432 | 1/1 | 1 | 1/1 |
| HI23 | Maui (17 det.) | 2023-08 | viirs | 17 | 1/1 | 2 | 1/1 |
| GR23 | Evros | 2023-08 | viirs | 441 | 1/1 | 1 | 1/1 |
| CL24 | Valparaiso | 2024-02 | viirs | 63 | 1/1 | 10 | 1/4 |
| AM24 | Amazon | 2024-09 | viirs | 56962 | **7/8** | 10 | 1/1 |
| BO24 | Bolivia | 2024-09 | viirs | 55109 | 2/4 | 2 | 1/1 |
| US25 | Los Angeles | 2025-01 | viirs | 217 | 1/1 | 5 | 1/3 |
| KR25 | S Korea | 2025-03 | viirs | 197 | 1/1 | 1 | 1/1 |
| JP25 | Ofunato (8 det.) | 2025-02 | viirs | 8 | 1/1 | 1 | 1/1 |
| RO25 | Romania 2025 | 2025-03 | viirs | 437 | **13/9** | 45 | 7/18 |
| controls | GR Aug14, RU 13, VIC Feb11, ID 10, ID 22, CA 20 | | | | 15, 9, 8, 10, 23, 10 | 41-143 | |

## 2. Built
`rezultate/events_countries/`:
- `famous_fires.csv`: 36 rows, with the box/country, window, peak month, ranks, flags, naive ranks and a source URL for each event.
- `cell_country.parquet`: 179,946 cells (ix, iy, country, share, n_points, method, lon, lat).
- `country_month.csv`: 203k rows covering 225 countries x D/N/ALL x 2000-10..2025-12. Months with no fire are included as zeros.

To reproduce: `python3 work/events_countries/b1_cell_country.py all && python3 work/events_countries/b2_country_tables.py && python3 work/events_countries/a1_famous_fires.py` (under 10 s; b1 recreates the deleted `_cc_*` intermediates).

## 3. Method
- **Events:** I summed n_eq and frp_eq (day+night) over every cell whose centre lies in the box (or the country), for each month from 2003 to 2025. The event's peak month is ranked against the same calendar month in all 23 years and against all 276 months. "Top 5%" means #1 of 23 on counts or FRP; "top 10%" means top 2.
- **Country lookup:** each cell gets the country with the most FIRMS detections in it, using MODIS and VIIRS points from 2015, 2019 and 2021. 19% of fire cells had no points in those years, but they hold only 1.53% of n_eq. I filled them from the nearest assigned cell within 1°; 375 cells stay unassigned (0.001%). 3.3% of n_eq sits in border cells where the majority share is below 80%.
- **pct_rank** = share of reference years (2003-2025) whose value is less than or equal to this one. 1.0 means the record month. It is empty before 2003.

**Usage note for the developers:** filter `country_month.csv` to `daynight='ALL'` for the calendar. With 23 reference years, "top 5%" means `pct_rank == 1.0` (the record) and "top 10%" means `pct_rank >= 0.956` (rank 1-2). Do not use `>= 0.95`, because that also catches rank 2. For an area, join `cell_country` or a box to `final_*.parquet` on (ix, iy). Hide the badge when n_eq < 50.

## 4. Caveats
- Boxes are hand-drawn rectangles (the Amazon box includes some Cerrado). Sources are Wikipedia/NASA EO/news pages, not checked against official burned-area statistics. I could not find which month Romania's 2025 burned area fell in.
- Countries come from FIRMS file names (offshore and disputed cells follow FIRMS). No static-source mask.

## 5. Needs
None.
