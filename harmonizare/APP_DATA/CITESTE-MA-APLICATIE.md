# Date pentru aplicație — tot ce trebuie e în acest folder

Valori **lunare**, 2000-11 … 2025-12, pe grilă de 0,25° (~28 km), pe **două scări**. Nimic nu se calculează cu ML la rulare:
aplicația doar citește coloana scării alese și adună.

## Fișierele
| Fișier | La ce folosește |
|---|---|
| `cells_monthly/final_{an}.parquet` | datele pe celulă: pentru orice dreptunghi desenat pe hartă |
| `country_month.csv` | gata agregat pe 230 de țări (cu rang, eroare tipică, încredere) |
| `region_month.csv` | la fel, pe 14 regiuni mari + `GLOBAL` |
| `country_season.csv`, `region_season.csv` | profilul sezonier: pentru fiecare lună calendaristică, mediana, media, p10, p90 (2003–2025), cât la sută din an arde în luna aceea și rangul lunii în sezon |
| `country_year.csv`, `region_year.csv` | totaluri anuale și rangul fiecărui an („care ani au ars cel mai mult”) |
| `country_trend.csv`, `region_trend.csv` | tendința 2003–2025: % pe an (Theil–Sen), cu test de semnificație |
| `cell_country.parquet` | din ce țară face parte fiecare celulă (`ix, iy, country`) |
| `accuracy_modis_scale.csv`, `accuracy_viirs_scale.csv` | tabelul de erori pe mărimea dreptunghiului și numărul de detecții |
| `validation_by_country.csv` | eroarea conversiei pe fiecare țară (test 2018–2021) |
| `famous_fires.csv`, `fig_*.png` | material pentru demo / pitch |
| `cell_static_share.parquet` | celule dominate de surse industriale (opțional, pentru avertisment) |

## Coloanele din `cells_monthly`
- `ix, iy` — celula: `lon = (ix + 0.5) * 0.25 - 180`, `lat = (iy + 0.5) * 0.25 - 90`
- `year, month, daynight` — `daynight` e `D` (trecerile de zi) sau `N` (trecerile de noapte). **Totalul lunar = D + N.**
- **Scara MODIS:** `n_eq` (detecții), `frp_eq` (putere, MW), interval `lo_n, hi_n, lo_frp, hi_frp`, `source`
  (`terra_backfill` / `aqua` / `viirs_harmonized`)
- **Scara VIIRS:** `n_veq`, `frp_veq`, interval `lo_nv, hi_nv, lo_frpv, hi_frpv`, `source_v`
  (`terra_to_viirs` / `aqua_to_viirs` / `viirs`)
- `flag` — `ok` sau `rescale` (lună cu câteva zile lipsă, deja corectată)
- O celulă-lună care lipsește din fișier = zero detecții.

## Cum calculezi un dreptunghi
1. Ia celulele cu `ix` între `floor((lon_min + 180) / 0.25)` și `floor((lon_max + 180) / 0.25)`, la fel `iy` cu latitudinea.
2. Pentru fiecare `(year, month)` adună `n_eq` (sau `n_veq`) pe celule și pe `D` + `N`.
3. Rangul lunii: compară cu aceeași lună calendaristică din anii 2003–2025 (23 de ani). Rang 1 = luna-record.
   „Top 5%” înseamnă rang 1; „top 10%” înseamnă rang 1–2.
4. Încrederea, după detecțiile pe scara MODIS (`n_eq`) din dreptunghi în luna respectivă:

| Detecții/lună în dreptunghi | Eroare tipică | Etichetă |
|---|---|---|
| ≥ 1.000 | ~9% | mare |
| 100–999 | ~14% | medie |
| 10–99 | ~25% | scăzută |
| < 10 | — | fără cifră: „puține focuri” (sau arată totalul anual) |

Eroarea se aplică doar valorilor **convertite** (`source` ≠ `aqua` pe scara MODIS; `source_v` ≠ `viirs` pe scara VIIRS).
Valorile măsurate direct nu au eroare de conversie. În `country_month.csv` și `region_month.csv` e deja calculat:
`typ_err_pct_modis`, `typ_err_pct_viirs`, `confidence`, `rank_modis`, `rank_viirs`.

## Reguli de afișare (ca să nu apară cifre proaste pe ecran)
- Arată implicit **totalul zi + noapte**. Noaptea separat doar dacă sunt ≥ 100 de detecții de noapte pe lună.
- **Scara VIIRS, noaptea, înainte de 2012:** nu afișa cifre pe dreptunghiuri mici; doar pe țară/regiune.
- Ascunde eticheta „record” dacă luna are sub ~50 de detecții în zona aleasă.
- Pe hartă, pentru puncte individuale, folosiți detecțiile FIRMS originale (CSV); aceste fișiere sunt doar pentru calendar și statistici.

## Ce înseamnă cele două scări
- **MODIS:** „câte detecții ar fi raportat MODIS Aqua”. 2002–2021 sunt măsurători reale; restul sunt convertite.
- **VIIRS:** „câte detecții ar fi raportat VIIRS”. 2012–2025 sunt măsurători reale; 2000–2011 sunt convertite din MODIS.
Clasamentul lunilor iese aproape identic pe ambele scări. Scara VIIRS are numere de ~5–6 ori mai mari.

## Coloane adăugate pentru cerințele din enunțul NASA
În `country_month.csv` / `region_month.csv`:
- `median_modis`, `mean_modis`, `median_viirs`, `mean_viirs` — valoarea normală a acelei luni calendaristice (2003–2025)
- `anom_pct_modis`, `anom_pct_viirs` — abaterea lunii față de mediana istorică, în % (ex. +218 = de 3,2 ori peste normal)

Enunțul cere explicit: „compare the burning activity of the current month against the historical median”,
„which periods of the year see more fires” (→ `*_season.csv`), „which years had more burning activity” (→ `*_year.csv`),
„trends” (→ `*_trend.csv`). Pentru un dreptunghi desenat, aplicația calculează aceleași lucruri din `cells_monthly`:
mediana pe aceeași lună calendaristică din 2003–2025, apoi `100 * (valoare / mediană - 1)`.
