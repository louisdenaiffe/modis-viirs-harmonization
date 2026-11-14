"""Country table and A/B split, stratified by fire regime and balanced by fire volume.

    python scripts/make_split.py data_raw/country_stats.csv splits/country_split.csv

Inputs: per country x year x sensor counts and fire-weighted centroids from
``scripts/country_stats.py``.

Columns of the output:
- ``gfed_region``: one of the 14 GFED basis regions (Giglio et al. 2013). It is assigned from
  the fire-weighted VIIRS centroid by simple latitude/longitude rules, plus explicit
  overrides for countries the rules would get wrong. A country spanning two regions gets the
  one holding its fire centroid, for example the United States gets TENA (Alaska is BONA) and
  DR Congo gets SHAF.
- ``regime``: dominant fire regime (boreal, savanna, tropical_forest, agricultural,
  mediterranean, steppe). Explicit for every country with >= ~1000 type-0 VIIRS
  detections/year, by GFED-region default for the rest. This is a judgement label at country
  level; see METHOD.md.
- ``viirs_type0_per_year``: mean type-0 VIIRS S-NPP detections per year, 2012-2024 (missing
  years count as 0). ``centroid_lat`` / ``centroid_lon``: fire-weighted mean position.
- ``half``: A or B. Within each regime, countries are taken by decreasing volume and each goes
  to the half with the smaller regime volume so far (ties: fewer countries). Romania is
  pinned to B (out-of-sample check from the earlier prototype).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REGION_OVERRIDE = {
    "United_States": "TENA", "Canada": "BONA", "Greenland": "BONA", "Saint_Pierre_and_Miquelon": "BONA",
    "Bahamas": "CEAM", "Bermuda": "TENA", "Cuba": "CEAM", "Turks_and_Caicos_Islands": "CEAM",
    "Panama": "CEAM", "Costa_Rica": "CEAM", "Trinidad_and_Tobago": "NHSA", "Ecuador": "NHSA",
    "Russian_Federation": "BOAS", "Mongolia": "CEAS", "Kazakhstan": "CEAS", "China": "CEAS",
    "Taiwan": "CEAS", "Hong_Kong": "CEAS", "Japan": "CEAS", "Republic_of_Korea": "CEAS",
    "Dem_Rep_Korea": "CEAS", "Kyrgyzstan": "CEAS", "Tajikistan": "CEAS", "Uzbekistan": "CEAS",
    "Turkmenistan": "CEAS", "Afghanistan": "MIDE", "Pakistan": "SEAS", "Iran": "MIDE",
    "Turkey": "MIDE", "Georgia": "EURO", "Armenia": "MIDE", "Azerbaijan": "MIDE",
    "Cyprus": "MIDE", "Yemen": "MIDE", "Oman": "MIDE", "Djibouti": "NHAF", "Somalia": "NHAF",
    "Eritrea": "NHAF", "Sudan": "NHAF", "Mauritania": "NHAF", "Niger": "NHAF", "Mali": "NHAF",
    "Chad": "NHAF", "Libya": "MIDE", "Egypt": "MIDE", "Algeria": "MIDE", "Morocco": "MIDE",
    "Tunisia": "MIDE", "Cape_Verde": "NHAF", "Kenya": "NHAF", "Uganda": "NHAF",
    "Gabon": "SHAF", "Equatorial_Guinea": "NHAF", "Sao_Tome_and_Principe": "NHAF",
    "Democratic_Republic_of_the_Congo": "SHAF", "Republic_of_Congo": "SHAF",
    "Philippines": "SEAS", "Sri_Lanka": "SEAS", "Maldives": "SEAS", "Singapore": "EQAS",
    "Brunei_Darussalam": "EQAS", "Malaysia": "EQAS", "Indonesia": "EQAS",
    "Papua_New_Guinea": "EQAS", "Timor-Leste": "EQAS", "Solomon_Islands": "EQAS",
    "Guam": "AUST", "Northern_Mariana_Islands": "AUST", "Palau": "AUST",
    "Federated_States_of_Micronesia": "AUST", "Kiribati": "AUST", "Nauru": "AUST",
    "Antarctica": "AUST", "Heard_I_and_McDonald_Islands": "AUST",
    "French_Southern_and_Antarctic_Lands": "AUST", "Falkland_Islands": "SHSA",
    "South_Georgia_and_South_Sandwich_Islands": "SHSA", "Saint_Helena": "SHAF",
    "Reunion": "SHAF", "Mauritius": "SHAF", "Seychelles": "SHAF", "Comoros": "SHAF",
    "Mayotte": "SHAF", "Madagascar": "SHAF", "Iceland": "EURO", "Svalbard_and_Jan_Mayen": "EURO",
    "Faeroe_Islands": "EURO", "Malta": "EURO", "Israel": "MIDE", "Palestine": "MIDE",
    "Lebanon": "MIDE", "Jordan": "MIDE", "Syria": "MIDE", "Iraq": "MIDE",
}


def gfed_region(country, lat, lon):
    if country in REGION_OVERRIDE:
        return REGION_OVERRIDE[country]
    if lon < -30:                                   # Americas + Atlantic
        if lat >= 50:
            return "BONA"
        if lat >= 24:
            return "TENA"
        if lat >= 0 and lon > -78 and lat < 13:
            return "NHSA"
        if lat >= 0:
            return "CEAM"
        return "SHSA"
    if lon > 150 or lon < -150 or (lon > 110 and lat < -10):
        return "AUST"
    if lon <= 60:                                   # Europe, Africa, Middle East
        if lat >= 36:
            return "EURO"
        if lat >= 17:
            return "MIDE"
        if lat >= 0:
            return "NHAF"
        return "SHAF"
    if lat >= 30:
        return "CEAS"
    if lat < 8 and lon > 95:
        return "EQAS"
    return "SEAS"


REGIME = {
    # boreal
    **dict.fromkeys(["Russian_Federation", "Canada", "Finland", "Sweden", "Norway", "Iceland",
                     "Greenland", "Estonia", "Latvia", "Svalbard_and_Jan_Mayen"], "boreal"),
    # savanna and grassland
    **dict.fromkeys(["Democratic_Republic_of_the_Congo", "Angola", "Zambia", "Mozambique",
                     "South_Sudan", "Central_African_Republic", "Tanzania", "Nigeria",
                     "Madagascar", "Guinea", "Ethiopia", "Chad", "Ghana", "Cameroon",
                     "South_Africa", "Sudan", "Mali", "Cote_d_Ivoire", "Zimbabwe", "Uganda",
                     "Sierra_Leone", "Senegal", "Benin", "Botswana", "Burkina_Faso", "Malawi",
                     "Namibia", "Togo", "Guinea-Bissau", "Kenya", "Niger", "Swaziland",
                     "The_Gambia", "Burundi", "Somalia", "Mauritania", "Lesotho", "Eritrea",
                     "Rwanda", "Australia", "Venezuela", "Colombia", "Paraguay", "Bolivia",
                     "Argentina", "Uruguay", "Fiji", "Vanuatu", "New_Caledonia", "Cuba",
                     "Djibouti", "Comoros", "Mayotte", "Reunion", "Mauritius"], "savanna"),
    # tropical forest, deforestation and shifting cultivation
    **dict.fromkeys(["Brazil", "Indonesia", "Myanmar", "Lao_PDR", "Cambodia", "Peru",
                     "Republic_of_Congo", "Papua_New_Guinea", "Liberia", "Gabon",
                     "Equatorial_Guinea", "Malaysia", "Ecuador", "Guatemala", "Honduras",
                     "Nicaragua", "Belize", "Mexico", "Guyana", "Suriname", "French_Guiana",
                     "Timor-Leste", "Costa_Rica", "Panama", "El_Salvador", "Brunei_Darussalam",
                     "Solomon_Islands", "Sri_Lanka", "Dominican_Republic", "Haiti", "Jamaica",
                     "Trinidad_and_Tobago", "Bhutan"], "tropical_forest"),
    # agricultural burning (crop residue, pasture, prescribed)
    **dict.fromkeys(["India", "China", "Thailand", "Vietnam", "Bangladesh", "Pakistan", "Nepal",
                     "Philippines", "United_States", "Ukraine", "Iraq", "Iran", "Syria", "Egypt",
                     "Turkey", "Germany", "Poland", "France", "United_Kingdom", "Romania",
                     "Bulgaria", "Serbia", "Belarus", "Hungary", "Moldova", "Japan",
                     "Republic_of_Korea", "Dem_Rep_Korea", "Taiwan", "Uzbekistan",
                     "Saudi_Arabia", "Oman", "Yemen", "Libya", "Azerbaijan", "Georgia",
                     "Armenia", "Bosnia_and_Herzegovina", "Slovakia", "Austria", "Czech_Republic",
                     "Netherlands", "Belgium", "Denmark", "Lithuania", "Slovenia", "Kosovo",
                     "Luxembourg", "Switzerland", "Ireland", "New_Zealand", "Qatar", "Kuwait",
                     "United_Arab_Emirates", "Bahrain"], "agricultural"),
    # mediterranean
    **dict.fromkeys(["Spain", "Portugal", "Italy", "Greece", "Morocco", "Algeria", "Tunisia",
                     "Israel", "Lebanon", "Cyprus", "Croatia", "Albania", "Montenegro",
                     "Macedonia_Former_Yugoslav_Republic_of", "Chile", "Jordan", "Palestine",
                     "Malta"], "mediterranean"),
    # steppe and dry grassland of central Asia
    **dict.fromkeys(["Kazakhstan", "Mongolia", "Kyrgyzstan", "Afghanistan", "Tajikistan",
                     "Turkmenistan"], "steppe"),
}
REGION_DEFAULT_REGIME = {"BONA": "boreal", "BOAS": "boreal", "TENA": "agricultural",
                         "CEAM": "tropical_forest", "NHSA": "tropical_forest",
                         "SHSA": "tropical_forest", "EURO": "agricultural", "MIDE": "agricultural",
                         "NHAF": "savanna", "SHAF": "savanna", "CEAS": "agricultural",
                         "SEAS": "agricultural", "EQAS": "tropical_forest", "AUST": "savanna"}
PINNED = {"Romania": "B"}
YEARS = range(2012, 2025)


def country_table(stats: pd.DataFrame) -> pd.DataFrame:
    v = stats[(stats["sensor"] == "viirs-snpp") & stats["year"].isin(YEARS)]
    m = stats[(stats["sensor"] == "modis") & stats["year"].isin(YEARS)]
    w = v["n"].clip(lower=1)
    g = v.assign(wl=v["lat"] * w, wo=v["lon"] * w, w=w).groupby("country")
    t = pd.DataFrame({
        "viirs_type0_per_year": g["n_type0"].sum() / len(YEARS),
        "viirs_all_per_year": g["n"].sum() / len(YEARS),
        "n_years_viirs": g["year"].nunique(),
        "centroid_lat": g["wl"].sum() / g["w"].sum(),
        "centroid_lon": g["wo"].sum() / g["w"].sum(),
    })
    mm = m.groupby("country")
    t["modis_type0_per_year"] = (mm["n_type0"].sum() / len(YEARS)).reindex(t.index).fillna(0)
    t["n_years_modis"] = mm["year"].nunique().reindex(t.index).fillna(0).astype(int)
    t["gfed_region"] = [gfed_region(c, la, lo) for c, la, lo in
                        zip(t.index, t["centroid_lat"], t["centroid_lon"])]
    t["regime"] = [REGIME.get(c, REGION_DEFAULT_REGIME[r]) for c, r in zip(t.index, t["gfed_region"])]
    t["regime_source"] = np.where(t.index.isin(list(REGIME)), "explicit", "region_default")
    return t.reset_index().rename(columns={"index": "country"})


def split(t: pd.DataFrame) -> pd.Series:
    half = pd.Series(index=t["country"], dtype=object)
    for regime, g in t.groupby("regime"):
        load = {"A": 0.0, "B": 0.0}
        cnt = {"A": 0, "B": 0}
        for c, vol in g.sort_values(["viirs_type0_per_year", "country"],
                                    ascending=[False, True])[["country", "viirs_type0_per_year"]].values:
            if c in PINNED:
                h = PINNED[c]
            else:
                h = min(("A", "B"), key=lambda k: (load[k], cnt[k], k))
            half[c] = h
            load[h] += vol
            cnt[h] += 1
    return half


if __name__ == "__main__":
    stats = pd.read_csv(sys.argv[1])
    t = country_table(stats)
    t["half"] = split(t).reindex(t["country"]).to_numpy()
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["country", "half", "gfed_region", "regime", "regime_source", "viirs_type0_per_year",
            "viirs_all_per_year", "modis_type0_per_year", "centroid_lat", "centroid_lon",
            "n_years_viirs", "n_years_modis"]
    t = t.sort_values(["regime", "viirs_type0_per_year"], ascending=[True, False])[cols]
    t.round({"viirs_type0_per_year": 1, "viirs_all_per_year": 1, "modis_type0_per_year": 1,
             "centroid_lat": 3, "centroid_lon": 3}).to_csv(out, index=False)
    bal = t.pivot_table(index="regime", columns="half", values="viirs_type0_per_year",
                        aggfunc=["sum", "count"]).round(0)
    print(bal.to_string())
    reg = t.pivot_table(index="gfed_region", columns="half", values="viirs_type0_per_year",
                        aggfunc="sum").fillna(0).round(0)
    print(reg.to_string())
    print(t.groupby("half")["viirs_type0_per_year"].agg(["sum", "count"]))
