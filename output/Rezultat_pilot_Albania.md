# Experiment exploratoriu: Albania 2024

Am descărcat MODIS de la NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/data/country/modis/2024/modis_2024_Albania.csv . Datele VIIRS Suomi NPP au fost recuperate din arhiva locală; vezi CITESTE-MA.txt. Acest experiment nu este o armonizare științific validată.

Pentru fiecare sursă am păstrat `type=0` (incendiu de vegetație presupus, nu confirmat) și am ales sateliții Aqua și Suomi NPP. Am împărțit spațiul în celule egale ca suprafață de 5 km. Pentru fiecare lună, am numărat combinațiile distincte celulă + zi UTC + zi/noapte care au cel puțin o detecție. Nu sunt numere de incendii, iar prezența în aceeași celulă pe aceeași zi nu garantează că cei doi sateliți au observat același foc.

Din șase luni impare am învățat factorul 0,3845 prin regresie liniară prin origine: indice MODIS estimat = 0,3845 × indice VIIRS. Am verificat pe șase luni pare; această împărțire este un test demonstrativ foarte mic, nu verificare independentă pe alt an sau altă regiune. Au fost utilizate 439 din 796 de rânduri MODIS (Aqua, type 0) și 3.070 din 3.175 VIIRS (type 0).

| Lunile de test, 2024 | MODIS Aqua observat | VIIRS observat | MODIS estimat din VIIRS |
|---|---:|---:|---:|
| Februarie | 13 | 50 | 19,2 |
| Aprilie | 15 | 57 | 21,9 |
| Iunie | 1 | 28 | 10,8 |
| August | 152 | 584 | 224,6 |
| Octombrie | 5 | 38 | 14,6 |
| Decembrie | 1 | 3 | 1,2 |

Eroarea absolută medie pe test a fost 17,5 unități celulă-zi/noapte pe lună, față de 95,5 atunci când folosim direct valoarea VIIRS drept predicție MODIS. Acest baseline este intenționat simplu; îmbunătățirea nu demonstrează acuratețe față de incendiile reale. Modelul a supraestimat toate cele șase luni, inclusiv august (224,6 vs 152). Asta este un avertisment clar că factorul nu este robust.

Limitări: CSV-urile conțin doar detecții, fără măști complete de nori și acoperire. Zero în acest tabel înseamnă zero detecții înregistrate, nu că știm că nu a fost foc sau că zona a fost observată. Nu controlăm diferențele de trecere, nori, unghi și detectabilitate. Activitatea observată de Aqua nu este adevăr de teren. O singură țară și un singur an nu testează generalizarea; lunile nu sunt neapărat independente și sezonul poate domina factorul. Nu folosiți 0,3845 pentru alți ani sau regiuni.

Reproducere din folderul proiectului: `python3 output/test_pilot_albania.py`. Rezultatele numerice complete sunt în `rezultate_pilot_albania.json`. Următorul test are nevoie de mai mulți ani și regiuni, ani întregi ținuți separat pentru test și, pentru a distinge lipsa focului de lipsa observării, de măștile L2 și geolocalizarea necesară.
