# Armonizarea MODIS + VIIRS — ce am făcut, cum funcționează, ce folosiți în aplicație

14 noiembrie 2026 · NASA Space Apps · track „Harmonization of MODIS and VIIRS Hot Spots”

## CE FOLOSIȚI: folderul `APP_DATA/`
Tot ce are nevoie aplicația e în `harmonizare/APP_DATA/`, cu instrucțiuni în `APP_DATA/CITESTE-MA-APLICATIE.md`.
Datele sunt pe două scări (MODIS și VIIRS), lunar, cu sursă, interval, rang și nivel de încredere.
Se reface cu: `04_build_final.py` (repetat până scrie DONE) → `05_summaries.py` → `08_app_package.py`.
Detecțiile Parquet (`data/points`) au fost șterse ca să nu ocupe disc; se refac cu `01_ingest.py` dacă mai e nevoie.

## ACTUALIZARE (14 nov., seara) — cifrele de mai jos le înlocuiesc pe cele din restul documentului
Trei îmbunătățiri aplicate și seria reconstruită:
1. **Mască de surse statice** (rafinării, flăcări de gaze, lavă): scoate 0,2% din detecțiile de zi și ~3% din cele de noapte
   (VIIRS 3,5%, Aqua 2,7%). Script: `scripts/06_apply_mask.py`; masca: `rezultate/static_mask/static_mask_001.parquet`.
2. **Latitudini mari** (Canada, Siberia), ziua: factori separați peste/sub 60°N, pe cea mai puternică trecere din zi.
3. **2000–2002**: conversia Terra → Aqua folosește anii cei mai apropiați (2003–2006).

Eroare față de Aqua real, test 2018–2021, după aceste schimbări:

| | Global | Regiune mediană | Cea mai slabă regiune |
|---|---|---|---|
| Detecții, zi | +2,6% | 2,1% | 6,1% |
| FRP, zi | +1,6% | 2,9% | 8,4% |
| Detecții, noapte | +1,6% | 5,5% | 31% |
| FRP, noapte | −2,3% | 3,3% | 34% |

Pe țări (139 de țări, ziua): eroare mediană 4,5%; 74% din țări sub 10%, 91% sub 20%. Noaptea (79 de țări): mediană 10%.
Tabel: `rezultate/final/validation_by_country.csv`. Direcția inversă (MODIS → scara VIIRS) e testată în
`rezultate/final/direction_test.csv`: ziua aceeași exactitate, noaptea mai slabă.
Tabelul lunar fără mască e păstrat în `data/grid/monthly_025_nomask/`; factorii vechi în `*_nomask.*`.
Notă: `accuracy_by_scale.csv` a fost calculat înainte de mască; ordinele de mărime rămân valabile.

## Pe scurt
Am construit o serie unică de activitate a focurilor, 2000–2025, pe grilă de 0,25°, lunar, separat zi/noapte,
în unități „echivalent MODIS Aqua”. Trecerea de la MODIS la VIIRS nu mai produce salt:

| | Adunat simplu (naiv) | Armonizat |
|---|---|---|
| Salt 2011 → 2012 (apare VIIRS) | ×5,03 | ×1,03 |

## Cât de bună e conversia VIIRS → echivalent Aqua
Calibrată pe 2012–2017, verificată pe ani pe care nu i-a văzut. Eroare față de Aqua real, global:

| | VIIRS brut | Armonizat, test 2018–2021 | Armonizat, 2022–2023 |
|---|---|---|---|
| Detecții, zi | +401% | +3,0% | +2,0% |
| FRP, zi | +27% | +1,6% | +0,7% |
| Detecții, noapte | +2931% | +2,6% | +6,8% |
| FRP, noapte | +129% | −4,0% | −3,5% |

Pe regiuni (14 regiuni, test 2018–2021): eroare mediană 3,0% ziua și 5,6% noaptea la detecții;
cea mai slabă regiune 12,7% ziua (America de Nord boreală) și 36,8% noaptea.
Noaptea rămâne partea slabă: tratați valorile de noapte pe regiuni mici cu prudență.

## Metoda, în 6 pași
1. **Curățare.** Păstrăm doar `type = 0` (foc de vegetație) și scoatem detecțiile cu încredere scăzută.
2. **Aceeași unitate.** Agregăm pe celule de 0,25°, pe lună, separat zi și noapte. Armonizăm numărul de
   detecții și FRP-ul. Am testat și „zile active” / „celule active”: sunt mai instabile (eroare 16–33% față de 10–23%).
3. **Pereche corectă.** VIIRS (Suomi NPP) se compară cu Aqua, fiindcă trec la aceeași oră (~13:30).
4. **Conversia de zi.** Factor = raport Aqua/VIIRS pe regiune × sezon, rafinat pe celulă (celulele cu puține
   date împrumută factorul blocului de 2° și al regiunii).
5. **Conversia de noapte.** Ponderi pe clase de putere a pixelilor VIIRS. Motivul: 80% din pixelii VIIRS de noapte
   au sub 3 MW, iar MODIS vede doar ~1% din ei.
6. **Lipirea seriei.**
   - nov. 2000 – iun. 2002: Terra convertit în echivalent Aqua (factori pe regiune × lună; eroare globală ~3%)
   - iul. 2002 – dec. 2021: Aqua real
   - din ian. 2022: VIIRS convertit
   - lunile cu satelit căzut se înlocuiesc cu celălalt senzor; lunile parțiale se rescalează.

## De ce nu putem continua pur și simplu cu MODIS
Orbitele MODIS alunecă. Ora de trecere măsurată în date: Aqua 13:37 → 14:55 (2025), Terra 10:28 → 09:14 (2025).
Față de VIIRS armonizat, ziua, global: Aqua rămâne în ±2% până în 2025, dar Terra scade cu 10% (2022),
17% (2023), 31% (2024) și 42% (2025). Cine adună Terra + Aqua vede o „scădere a incendiilor” care nu e reală.

## Fișierele de folosit în aplicație (`rezultate/final/`)
| Fișier | Ce conține |
|---|---|
| `parts/final_{an}.parquet` | seria finală pe celulă: `ix, iy, year, month, daynight, n_eq, frp_eq, lo_*, hi_*, source, flag` |
| `region_month.csv` | aceeași serie pe 14 regiuni + GLOBAL, cu interval, sursă și `pct_rank_n` (percentila lunii față de aceeași lună din 2003–2025) |
| `validation_by_region.csv` | eroarea conversiei pe regiune și perioadă |
| `annual_global.csv` | totaluri anuale: naiv vs armonizat |
| `fig_harmonization_summary.png` | graficul „înainte/după” pentru pitch |

Celula: `lon = (ix + 0,5) × 0,25 − 180`, `lat = (iy + 0,5) × 0,25 − 90`. Pentru o zonă desenată pe hartă, adunați
`n_eq` din celulele din interior. „Luna asta e în top 5%” = `pct_rank_n ≥ 0,95`.
`source` spune de unde vine valoarea: `terra_backfill`, `aqua`, `viirs_harmonized`.

## Cum se reproduce (din folderul proiectului)
```
python3 harmonizare/scripts/01_ingest.py      # CSV -> Parquet (repetați până termină)
python3 harmonizare/scripts/02_grid.py        # treceri pe grilă 0,25°
python3 harmonizare/scripts/03_monthly.py     # tabel lunar
python3 harmonizare/scripts/eval_common.py    # testul comun + metodele de bază
python3 harmonizare/scripts/04_build_final.py # seria finală
python3 harmonizare/scripts/05_summaries.py   # tabele, validare, grafic
```
Factorii: `rezultate/calib_ratio/factors.parquet` (zi), `rezultate/calib_physics_ml/p1_weights.csv` (noapte),
`rezultate/qc_stability/terra_to_aqua_factors.csv` (2000–2002). Rapoartele agenților: `rezultate/*/REPORT.md`.

## Ce NU e făcut / limite
- **Masca de surse statice** (rafinării, oțelării): neterminată. Ne bazăm doar pe eticheta `type`, care în VIIRS
  versiunea 2 e raportată ca imperfectă. Poate umfla valorile de noapte în zone cu flăcări de gaze.
- **Curba de detecție:** făcută pe 3 ani (2015, 2019, 2021), cu forma pixelului MODIS aproximată; vezi secțiunea de mai jos.
  același loc, Aqua vede foc în 50% (zi) / 24% (noapte) din celulele unde vede VIIRS, dar acelea conțin ~85% din FRP.
- **Fără măști de nori** (produsele L2): un „zero” înseamnă „nicio detecție”, nu „sigur n-a ars”.
- **Valorile zilnice** nu sunt armonizate; folosiți-le doar pentru afișarea punctelor pe hartă.
- **După 2021** conversia nu mai poate fi verificată perfect, fiindcă Aqua alunecă; verificarea pe 2022–2023 e bună,
  cea pe 2024–2025 arată abateri mai mari noaptea (+21%), probabil din cauza lui Aqua.
- **Viitor:** Suomi NPP a fost oprit pe 2 nov. 2026. Pentru date noi trebuie NOAA-20, cu un factor NOAA-20 → Suomi NPP
  (nefăcut; arhiva voastră conține doar Suomi NPP).

## Curățenie pe disc (14 nov., după-amiază)
Am șters fișierele intermediare mari (folderul a scăzut de la 13 GB la ~3 GB). Au rămas: tabelul lunar
(`data/grid/monthly_025`), seria finală, factorii, rapoartele și detecțiile Parquet doar pentru 2015, 2019, 2021.
Dacă aveți nevoie din nou de toate detecțiile în Parquet sau de tabelul de treceri, rulați `01_ingest.py` și `02_grid.py`
(~10 minute, ~11 GB). CSV-urile originale nu au fost atinse.

## Cât de exactă e o zonă desenată în aplicație (test 2018–2021)
Exactitatea depinde de **cât foc e în zonă**, nu de cât de mare e zona.

| Detecții echivalent MODIS pe lună, în zona aleasă | Eroare tipică | Ce afișați |
|---|---|---|
| ≥ 1.000 | ~±10% | încredere mare |
| 100–999 | ~±15% | încredere medie |
| 10–99 | ~±25–35% | încredere scăzută, cu interval |
| sub 10 | nu se poate da o cifră lunară | „puține focuri” sau totalul anual |

Totalurile anuale sunt cam de două ori mai exacte (6–7% la ≥ 1.000 detecții pe an). FRP-ul are nevoie de ~10× mai multă
activitate pentru aceeași exactitate. Un sezon extrem, diferit de anii de calibrare (ex. Yakutia 2019–2021), poate fi greșit cu ±40%.
Tabelul complet pentru aplicație: `rezultate/calib_physics_ml/accuracy_by_scale.csv`.

## Ce au arătat focurile văzute simultan de ambii sateliți (2015, 2019, 2021)
- MODIS ratează 60% din focurile VIIRS ziua (75% noaptea), dar acelea conțin doar 33% (37%) din putere.
- MODIS are 50% șanse să vadă un foc de la ~14 MW ziua și ~9 MW noaptea; la marginea imaginii pragul de zi urcă la 32 MW.
- Când ambii văd focul, puterea se potrivește (VIIRS/MODIS = 0,95 ziua, 0,94 noaptea).
- Un singur prag de putere pe VIIRS nu poate potrivi și detecțiile, și puterea — de aceea le calibrăm separat.
Detalii și grafic: `rezultate/simul_overpass/REPORT.md`, `fig_detection_curve.png`.
