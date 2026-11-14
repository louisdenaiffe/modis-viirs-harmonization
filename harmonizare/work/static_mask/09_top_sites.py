"""top_static_sites.csv: 30 strongest masked sites (0.1 deg) by default-filter detections removed, with likely identity
(identities = analyst judgement from coordinates; 'likely' = not verified against a catalogue)."""
import pandas as pd
ID = ['Fagradalsfjall eruption 2021, Iceland (volcano)', 'Cumbre Vieja eruption 2021, La Palma (volcano)', 'Piton de la Fournaise, Reunion (volcano)',
 'Kilauea, Hawaii (volcano)', 'Cumbre Vieja eruption 2021, La Palma (volcano)', 'Holuhraun eruption 2014-15, Iceland (volcano)',
 'gas flares, Yurubcheno-Tokhomskoye oil field area, E Siberia (likely)', 'gas flares, Gachsaran oil field, Iran (likely)',
 'gas flares, West Qurna/Basra oil fields, Iraq (likely)', 'gas flares, Gachsaran oil field, Iran (likely)', 'Wolf volcano 2015, Galapagos',
 'gas flares, Kirkuk-area oil/gas fields, Iraq (likely)', 'Shiveluch, Kamchatka (volcano)', 'gas flares, Sakha oil fields (Talakan/Srednebotuobinskoye), E Siberia (likely)',
 'Bontang LNG plant, East Kalimantan (industrial flare)', 'gas flares, Hassi Messaoud oil field, Algeria', 'gas flares, Shabwah/Marib oil fields, Yemen (likely)',
 'gas flares, Hassi Messaoud oil field, Algeria', 'gas flares, Illizi basin (In Amenas/Ohanet), Algeria (likely)', 'gas flares, Maysan oil fields (Halfaya), Iraq (likely)',
 'gas flares, Badra/Ilam fields, Iraq-Iran border (likely)', 'gas flares, Gachsaran oil field, Iran (likely)', 'UNCERTAIN: Veracruz lowlands, Mexico (sugar mill / industry?)',
 'eMalahleni (Witbank) coalfield / industry, South Africa (likely)', 'gas flares, Gachsaran oil field, Iran (likely)', 'coal/coking industry, Shenmu-Ordos, China (likely)',
 'gas flares, Urengoy/Tarko-Sale gas fields, West Siberia (likely)', 'gas flares, Majnoon oil field, Iraq (likely)', 'gas flares, Maysan oil fields, Iraq (likely)',
 'gas flares, Egyptian Western Desert oil fields (likely)']
d = pd.read_csv('top_static_sites_raw.csv').head(len(ID))
d['n_days'] = d[['max_days_snpp', 'max_days_modis']].max(axis=1).astype(int)
d['sensor'] = 'SNPP+MODIS'; d.loc[d.n0q_aqua.fillna(0) < 0.02 * d.n0q_removed, 'sensor'] = 'SNPP (MODIS ~0)'
d['likely_identity'] = ID
d['night_share'] = (d.n0q_N / d.n0q_removed).round(2)
d[['lat', 'lon', 'n_days', 'sensor', 'likely_identity', 'reason', 'n0q_removed', 'n0q_snpp', 'n0q_aqua', 'night_share', 'max_months_snpp', 'mean_frp', 'n_flag1', 'n_flag2', 'n_flag3']].to_csv('../../rezultate/static_mask/top_static_sites.csv', index=False)
v = pd.read_csv('top_volcano_raw.csv')
v['likely_identity'] = ['Nyiragongo, DR Congo', 'Kilauea, Hawaii', 'Nyamuragira, DR Congo', 'Semeru, Java', 'Karangetang, Sulawesi', 'Ibu, Halmahera', 'Yasur, Vanuatu',
  'Sangay, Ecuador', 'Ambrym, Vanuatu', 'Fuego, Guatemala', 'Erebus, Antarctica', 'Santiaguito, Guatemala', 'Erta Ale, Ethiopia', 'Nevados de Chillan, Chile', 'Sangeang Api, Indonesia']
v.drop(columns=['gx', 'gy']).to_csv('../../rezultate/static_mask/top_volcano_cells.csv', index=False)
print(d[['lat','lon','n_days','sensor','likely_identity','n0q_removed','night_share']].to_string())
