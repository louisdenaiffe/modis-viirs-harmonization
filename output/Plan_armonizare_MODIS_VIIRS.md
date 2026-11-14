# Plan practic: armonizarea detecțiilor MODIS și VIIRS

14 noiembrie 2026 · Plan de lucru pentru NASA Space Apps · Echivalentul istoric este o estimare, nu adevărul despre toate incendiile.

## Ideea în limbaj simplu

Fiecare rând FIRMS este un pixel în care un senzor a detectat o anomalie termică. Nu este automat un incendiu separat, o suprafață arsă sau dovada că nu a existat foc în locurile fără rânduri. VIIRS observă adesea focuri mai mici decât MODIS. Dacă adunăm rândurile, o schimbare de senzor sau de număr de sateliți poate arăta ca o schimbare a incendiilor.

Ținta propusă pentru istoric: un **indice de activitate observată comparabil cu MODIS**, pe regiune și lună. Separat, o hartă operațională păstrează toate detecțiile VIIRS și MODIS cu sursa lor. Indicele nu reprezintă numărul real de incendii, suprafața arsă sau emisii.

## 1. Ce date folosim

- O singură regiune demonstrativă, două sezoane de incendiu contrastante și, dacă descărcarea permite, mai mulți ani din perioada de suprapunere. Alegeți o regiune cu suficiente detecții și perioade fără foc. Păstrați o zonă și ani separați pentru testare.
- Din pagina https://firms.modaps.eosdis.nasa.gov/country/: MODIS din secțiunea MODIS; pentru VIIRS, urmați indicația echipei și verificați setul din secțiunea Data, fără a presupune că NOAA-20 este același lucru cu Suomi NPP. Verificați efectiv antetul și proveniența fișierelor. Pentru istoric, preferați produse standard, cu aceeași colecție/versiune; nu amestecați fără etichete NRT și standard.
- Fixați pentru prima comparație MODIS Aqua și VIIRS Suomi NPP unde câmpul satelit permite identificarea lor, deoarece trecerile lor sunt relativ apropiate. Nu presupuneți că sunt simultane. Stabiliți și documentați exact constelația folosită pentru fiecare an; includeți Terra separat doar după validare. Dacă nu se pot separa sateliții, nu pretindeți comparații între treceri individuale.
- CSV-ul FIRMS conține doar detecții pozitive. Pentru verificarea acoperirii și cazurilor fără foc, achiziționați măștile Level 2 MOD14/MYD14 și VNP14IMG, împreună cu geolocalizare, calitate și clasificarea norilor. Acest pas poate fi limitat la un eșantion de date pentru hackathon. Fără ele, marcați acoperirea drept necunoscută; nu calculați rate de detecție sau omisiune din absența rândurilor CSV.
- Salvați un manifest: sursă, satelit, produs, colecție, tip standard/NRT, interval, regiune, data descărcării, hash fișier, număr de rânduri. Păstrați fișierele originale intacte.

## 2. Curățare fără a pierde informație

Creați o tabelă normalizată: `source`, `satellite`, `product_version`, `latitude`, `longitude`, `acq_datetime_utc`, `daynight`, `scan_km`, `track_km`, `confidence_raw`, `frp_mw`, `type_raw`, `source_file`, `source_row_id`. Citiți ora ca HHMM, inclusiv zerourile inițiale; înregistrați UTC. Validați coordonate, date, câmpuri lipsă și eventuale duplicate identice, dar păstrați originalul. Raportați câte rânduri se elimină și de ce.

Nu transformați automat valorile numerice MODIS și clasele VIIRS în aceeași probabilitate. Filtrele de calitate rămân specifice fiecărui produs, explicite și comparate prin analiză de sensibilitate. Păstrați `daynight` și analizați ziua și noaptea separat la început.

Dacă există `type`, separați tipurile indicate de produs: 0 = presupus incendiu de vegetație, 1 = vulcan, 2 = altă sursă statică, 3 = offshore. Clasa 0 nu garantează adevărul de teren. Dacă tipul lipsește, nu inventați clasa; marcați-o necunoscută. Măștile suplimentare pentru vulcani și industrie sunt opționale, cu sursă și dată documentate; o excludere cu rază fixă poate elimina incendii reale din apropiere.

## 3. Definiți aceeași unitate de comparație

Pentru MVP alegeți o grilă egală ca suprafață de aproximativ 5 × 5 km (valoare de pornire experimentală, nu rezoluție optimă demonstrată). În fiecare celulă, zi locală și fereastră zi/noapte, calculați separat pentru fiecare satelit dacă există cel puțin o detecție. Salvați și momentul UTC și ora locală, fusul și regula de schimbare a datei. Pentru comparația dintre sateliți, păstrați și fereastra de trecere; evitați să confundați ziua calendaristică cu observații simultane.

O celulă activă reprezintă **cel puțin o detecție**, nu celulă arsă integral. Mai multe puncte sau sateliți în aceeași celulă/fereastră se numără o singură dată în indicatorul de prezență, dar punctele rămân disponibile pentru audit. Încercați 2, 5 și 10 km; comparați rezultatele. O grilă comună reduce diferențe, nu elimină diferențele de sensibilitate. Pentru suprafețe arbitrare, stabiliți explicit regula pentru celulele de la margine, sau limitați inițial demonstrația la regiunea predefinită.

`scan × track` oferă dimensiuni aproximative ale pixelului, nu geometria exactă orientată. Nu susțineți că ați calculat suprapunerea exactă a amprentelor din aceste două valori; folosiți geometria Level 2 dacă e disponibilă. Căutarea după distanță este doar aproximativă.

## 4. Comparați senzori în suprapunere

Creați perechi candidate Aqua–Suomi NPP prin celulă sau distanță și timp. Folosiți câteva praguri exploratorii, de exemplu 1, 3 și 5 km și 15, 30 și 60 minute, raportând distanța și diferența de timp. Acestea sunt parametri de experiment, nu praguri NASA. Preferabil intersecția amprentelor reale. Un foc se poate schimba între treceri, deci perechile nu sunt garantat același incendiu. Păstrați grupurile ambigue și cazurile fără pereche; evitați potriviri multiple numărate ca dovezi independente.

Cu măștile L2, construiți pentru fiecare oportunitate o categorie pentru fiecare senzor: foc, fără foc observabil, nor/neobservabil sau lipsă de acoperire. Comparați doar cazuri în care ambii au observat în condiții utilizabile, raportând separat procentele excluse. Tabelele de concordanță măsoară acordul dintre produse, nu acuratețea față de realitate. Pentru acuratețe reală sunt necesare date independente: incendii documentate sau imagini cu rezoluție superioară, potrivite în timp și verificate manual, după disponibilitate.

## 5. Calibrați indicele și arătați incertitudinea

Construiți pe fiecare celulă-lună, zi/noapte și satelit numărul de zile cu detecție și, dacă măștile permit, numărul de zile sau treceri observabile. Alegeți o singură țintă precisă: activitate comparabilă cu Aqua pe aceeași populație de oportunități observabile. Nu transformați ratele în numere absolute fără a defini expunerea și a justifica extrapolarea.

Încercați în ordine: (A) seria Aqua fără calibrare ca referință; (B) un factor simplu, învățat numai pe datele de antrenare, separat pe sezon/zi-noapte dacă eșantionul permite; (C) un model simplu de regresie cu expunerea observabilă și variabile justificate, numai dacă îmbunătățește testul. Păstrați zero-urile observabile și celulele fără foc; nu antrenați numai pe perechi pozitive. Evitați modelele complexe cu date puține. Testați stabilitatea pe ani, regiuni și regimuri de activitate; dacă expunerea nu este cunoscută, prezentați doar un prototip exploratoriu, fără promisiunea unui indice calibrat valid.

Separați antrenarea de test: de exemplu, țineți un an întreg și o subregiune în afara antrenării, cu un al doilea test temporal dacă există date. Raportați eroarea absolută medie, biasul, diferența sezonieră și performanța pentru luni fără foc/puțin foc; comparați cu o referință simplă. Adăugați intervale prin bootstrap pe blocuri independente, de exemplu celule-lună sau regiuni și luni, nu prin tratarea pixelilor vecini drept independenți. Afișați câte cazuri susțin fiecare rezultat. Fără validare independentă, nu promiteți un procent de acuratețe.

Factorul poate fi nedefinit când referința este zero, poate varia puternic în spațiu/timp și poate șterge focuri mici reale. Dacă modelul pică testele sau lipsesc măștile, afișați seriile pe senzori și indicatorul comun ca exploratorii, cu eticheta «comparabilitate nevalidată», nu o singură serie pretins armonizată. Percentilele calculate separat pe fiecare eră nu rezolvă automat schimbarea senzorului.

## 6. FRP, nori și schimbări în constelație

FRP este putere radiativă estimată în MW la momentul trecerii, nu energie acumulată, suprafață arsă sau număr de incendii. La VIIRS 375 m, estimarea FRP folosește și informație de 750 m; zero sau lipsă poate însemna retrieval imposibil, în funcție de produs. Nu adunați FRP din senzori și treceri diferite ca o singură măsurare și nu presupuneți egalitate fizică perfectă între suma VIIRS și MODIS. Dacă îl folosiți, păstrați-l separat pe satelit/trecere, cu valori invalide și saturație marcate, apoi verificați empiric comparabilitatea.

Norii, fumul, unghiul de scanare, diferența dintre ore, variația focului, suprafața, limitele detecției și schimbările de algoritm afectează comparația. Fără date despre acoperire, un zero în CSV este «necunoscut», nu «nu a fost foc». Nu completați golurile alegând VIIRS doar pentru că MODIS nu are puncte. Nu considerați netezirea curbei dovadă de armonizare: un salt poate fi real.

## 7. Aplicația minimă și rezultate de livrat

1. Hartă cu detecții originale, culori după satelit, dată, zi/noapte, tip, calitate și legendă.
2. Calendar lunar al indicelui, doar dacă a trecut testele; altfel afișați separat senzorii și eticheta exploratorie. Vizualizați distinct lipsa datelor de zero observabil.
3. Grafic de comparație înainte/după, eșantioane de validare și intervale de incertitudine. Arătați și schimbările de constelație/produse.
4. Export CSV cu unitate, satelit, regiune, surse, versiune, acoperire, valoare, incertitudine și starea validării. O afirmație de tip «top 5%» se folosește numai cu un istoric comparabil, suficient și validat.

## 8. Ordinea de lucru pentru echipă

- Date: descarcă un singur set complet pentru regiunea pilot și un an de suprapunere; verifică ZIP și antete, creează manifestul și tabela normalizată. Apoi descarcă ani suplimentari și, în paralel, un eșantion L2.
- Știință: definește oportunitatea observabilă, grila și schema de potrivire; construiește analiza de sensibilitate și verifică măștile de nori/type/confidence.
- Modelare: implementează referința simplă și factorul sau regresia; separă testul pe ani/spațiu, calculează erori și intervale. Raportează explicit eșecurile.
- Aplicație: construiește mapă și calendar pe date demonstrative marcate ca atare, conectează datele reale numai după confirmarea schemei; arată lipsurile și proveniența.
- Prezentare: pregătește exemplul unei regiuni, explică diferența dintre detecție și incendiu, prezintă testul și limitările. Fixați livrarea unui flux complet înainte de extindere.

## 9. Situația fișierelor la inspecție

Folderul MODIS local nu conține date. Cele 14 elemente VIIRS din 2012–2025 au extensia `.zip.download` și nu au fost recunoscute ca arhive ZIP complete. Un CSV complet pentru Albania 2024 a fost recuperat dintr-o arhivă incompletă și verificat prin CRC: 3.175 detecții VIIRS Suomi NPP; 2.466 (77,7%) au FRP sub 10 MW. Pragul de 10 MW din RTF ar elimina majoritatea acestor rânduri în acest exemplu. Acest fapt nu demonstrează că pragul este greșit, dar arată necesitatea testării lui; eșantionul singur nu permite calibrarea cu MODIS. Documentul RTF existent este o sursă de idei, nu o validare: pragurile de confidence și FRP, conversia pixelilor în suprafață arsă și substituirea absenței unui punct cu lipsa acoperirii nu trebuie preluate fără dovezi. Planul PDF propune o grilă și un factor; ambele sunt ipoteze de testat, nu garanții de comparabilitate.

## Surse

- Provocarea: https://www.spaceappschallenge.org/2026/challenges/harmonization-of-modis-and-viirs-hot-spots/
- FIRMS și arhive: https://firms.modaps.eosdis.nasa.gov/country/ ; https://firms.modaps.eosdis.nasa.gov/download/ ; https://firms.modaps.eosdis.nasa.gov/content/active_fire/
- Descriere VIIRS FIRMS: https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html
- Ghid NASA MODIS: https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf
- Ghid NASA VIIRS: https://www.earthdata.nasa.gov/sites/default/files/imported/VIIRS_activefire_User_Guide.pdf
- Algoritmul VIIRS 375 m: https://viirsland.gsfc.nasa.gov/PDF/VIIRS_activefire_375m_ATBD.pdf
- Produs VIIRS L2: https://modaps.modaps.eosdis.nasa.gov/services/about/products/viirs-land-c1/VNP14IMG.html
- Fire ESDR / VIIRS 750 m: https://viirsland.gsfc.nasa.gov/Products/NASA/FireESDR.html
