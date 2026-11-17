# flightlog-daten

Daten für den FlyCademy Flight Log (training.flycademy.de/flightlog), aufbereitet mit GitHub Actions und als Download im
Release **„daten“** veröffentlicht. Der Datendienst des Flight Log (`private/flightlog/dienst.php`) holt sie sich von
dort selbst in den nicht öffentlichen Datenordner; dafür braucht es kein FTP-Konto und keine Zugangsdaten. Der Flight
Log fragt nur den eigenen Server; kein Browser spricht mit DWD, Copernicus, GeoNames, open flightmaps, OurAirports, DFS oder GitHub.

| Job | Quelle | Wann | Datei auf dem Server |
| --- | --- | --- | --- |
| Wind ICON-D2 | Deutscher Wetterdienst, ICON-D2 (opendata.dwd.de) | alle 3 Stunden | `private/flightlog/daten/wx/wind.bin` |
| Gelände | Copernicus DEM GLO-30 (AWS Open Data), Gipfel aus GeoNames | von Hand, einmal | `private/flightlog/daten/gelaende.bin` |
| Orte | GeoNames (download.geonames.org) | monatlich | `private/flightlog/daten/orte.bin` |
| Luftraum | open flightmaps, OFMX Deutschland (snapshots.openflightmaps.org) | täglich | `private/flightlog/daten/luftraum.bin` (bis Build 25v) |
| Luftraum DFS | DFS, Datensatz „ED Airspace“ (aip.dfs.de/datasets); Flugplätze, Meldepunkte und Umriss aus `luftraum.bin` | täglich (im Job Luftraum) | `private/flightlog/daten/luftraum-dfs.bin` (ab Build 25w) |
| Pisten | OurAirports, `runways.csv` (davidmegginson.github.io/ourairports-data) | wöchentlich (montags) | `private/flightlog/daten/pisten.bin` |
| Hindernisse | DFS, Datensatz „ED Obstacles Area 1“ (aip.dfs.de/datasets), laufender und nächster AIRAC-Zyklus | täglich | `private/flightlog/daten/hindernisse.bin` |

## Was die Jobs rechnen

- **Wind:**
  - u, v und t der ICON-D2-Modellflächen werden auf feste Höhen umgerechnet: 1000–8000 ft in 1000-ft-Schritten, dazu 10 000, 12 000 und 14 000 ft MSL.
  - Danach mittelt der Job sie auf ein 0,1°-Gitter, 0 bis 48 Stunden, jede Stunde (der Lauf selbst kommt alle 3 Stunden).
  - An jedem Flugplatz im Gebiet (OurAirports) kommen stündliche Bodenwerte dazu. Die Temperatur wird auf die Platzhöhe umgerechnet.
  - Vor dem Veröffentlichen prüft der Job die Werte und vergleicht einige Plätze mit Open-Meteo (Modell icon_d2).
- **Gelände:**
  - Je 30″-Zelle (rund 0,5 NM) der höchste Geländepunkt aus Copernicus GLO-30, für 35–60° N und 10° W–30° E.
  - Das Radar-Höhenmodell gibt spitze Gipfel zu niedrig wieder (Großglockner rund 3675 statt 3798 m). Darum hebt der Job jede Zelle mit einem höheren vermessenen Gipfel aus GeoNames auf dessen Höhe an. Er senkt nie ab. Gipfelhöhen mehr als 250 m über dem Gelände gelten als Datenfehler und stehen im Protokoll.
- **Orte:**
  - Orte, Ortsteile, Berge und Seen von DE, AT, CH, LI, LU, NL, BE, DK, PL, CZ, SK, HU, SI, HR, IT und FR.
  - Angezeigt wird der deutsche Name, wenn GeoNames einen hat.
- **Luftraum:**
  - Für den laufenden und den nächsten AIRAC-Zyklus die Übersicht `publicationServices/ED_<Zyklus>.xml` lesen und das OFMX-Archiv laden (`ofmx_ed/isolated`: nur Deutschland). Der nächste Zyklus steht etwa eine Woche vor Beginn bereit; bis dahin enthält die Datei nur den laufenden.
  - Lufträume mit Art, Klasse, Name, Unter- und Obergrenze, Zeitplan und Bemerkung; den Umriss liefert die Shape-Extension von open flightmaps (Bögen aufgelöst). Umrisse vereinfacht auf rund 20 m. Ohne Höhen (Sammel-Einträge) und FIR, UIR, FIS-Sektoren und Entwürfe fehlen in der Liste; die FIR ergeben den Bereich, in dem die App diese Daten statt des openAIP-Kartenbilds zeigt.
  - Flugplätze (AD, Segelflug, UL; ohne Hubschrauberlandeplätze) und alle VFR-Meldepunkte.
  - Vor dem Veröffentlichen: Prüfsummen, Mindestanzahlen, Stichproben (EDVE in der CTR Braunschweig, EDDH, EDDM, EDDF), Bereich in Mitteleuropa.
- **Luftraum DFS (ab Build 25w, Georgi 15.11.2026: „Lufträume von der DFS“):**
  - Die Übersicht der DFS (`scripts/getAmdtData.php?amdt=0` und `=1`) nennt den Datensatz `ED_Airspace_StrokedBorders` des laufenden und des nächsten Zyklus. In die Datei kommen die Zyklen, die `luftraum.bin` hat und die die DFS führt; fehlt der laufende bei der DFS, bricht der Schritt ab und der Server behält die vorige Datei.
  - Je Luftraum Art, Kennung, Name, Klasse, Unter- und Obergrenze, Zeitplan aus den Timesheets (Sommer/Winter, Daten, SR/SS, Sommerzeit-Ausgleich), Bemerkungen. Bögen und Kreise auf dem WGS84-Ellipsoid aufgelöst, Umrisse wie bisher auf rund 20 m vereinfacht. Zusammengesetzte Lufträume: je Teil ein Eintrag mit dessen Grenzen.
  - Arten wie bisher in der App: CTR (auch Sektoren), TMA (Luftraum C/D), CLASS (Luftraum E; landesweit „AREA“), TMZ, RMZ, ATZ, R (ED-R, auch AMC), D (ED-D), HPGLDR (Fallschirmsprung), GLDR (Segelflugsektoren), LFA (militärische Tieffluggebiete); neu ACR (Kunstflug) und UAV (Flugmodelle/UAS). Nicht übernommen: Sektoren, CTA/UTA, FIS-Sektoren, FRA, NPZ, Gates, DLG-ATS, FBZ (nur Flugplanung), PROTECT außer LFA, D_OTHER, Luftraum G.
  - Was die DFS nicht führt, bleibt aus open flightmaps, gekennzeichnet mit `q: "ofm"`: Naturschutzgebiete, Segelflug- und Fallschirmsprunggebiete ohne Gegenstück (gleiche Fläche ≥ 60 %) im DFS-Datensatz. Flugplätze, VFR-Meldepunkte und Umriss Deutschlands kommen unverändert aus `luftraum.bin`.
  - Vor dem Veröffentlichen: wie `luftraum.bin`, dazu Quellenangabe DFS (CC BY 4.0), Mindestanzahlen je Art aus dem DFS-Datensatz, Ergänzungen nur in den genannten Arten.
- **Pisten:**
  - Je Platz mit vierstelliger Kennung und je offener Bahnrichtung mit Kennung 01–36: Kennung, Richtung (Zahl × 10), Länge und Länge abzüglich versetzter Schwelle in m, Belag.
  - Gerechnet genau wie die App bis Build 25j im Browser aus derselben CSV (geprüft an über 3000 Plätzen: gleich).
  - Je Anfangsbuchstabe der Kennung ein gepackter Teil, damit der Dienst je Abfrage nur einen kleinen Teil liest.
  - Vor dem Veröffentlichen: Prüfsummen, Mindestanzahlen, Wertebereiche, Stichproben (EDVE 08/26, EDDH, EDDF, EDVM, LOWI).
- **Hindernisse (ab Build 25s):**
  - Die Übersicht der DFS (`scripts/getAmdtData.php?amdt=0` und `=1`) nennt den Datensatz des laufenden und des nächsten Zyklus. Der Job lädt beide und vereinigt sie: Ein Hindernis zählt, sobald es in einem der beiden steht, mit der größeren Höhe (auf der sicheren Seite).
  - Je Hindernisteil Lage, Spitze in ft MSL (aufgerundet), Höhe über Grund, Art, Befeuerung; je 1°-Kachel gepackt.
  - Abdeckung: Die DFS führt nur Hindernisse in Deutschland. Je 30″-Zelle (wie das Gelände) ein Bit „ganz in Deutschland“, aus dem Umriss in `luftraum.bin` (FIR, um 300 m nach innen gesetzt). Berührt ein MSA-Korridor eine Zelle ohne Bit, meldet der Flight Log den Abschnitt als „ohne Hindernisdaten“.
  - Der Flight Log rechnet damit die MSA wie die Übungskarte der Theorie (Georgi 15.11.2026): MEF = höchste Erhebung im Korridor (Gelände + 300 ft oder Hindernis, je höher) + 100 ft, aufgerundet auf volle 100 ft.
  - Vor dem Veröffentlichen: Prüfsumme, laufender Zyklus gilt, Mindestanzahlen, Wertebereiche, Abdeckung an Stichproben (EDVE, EDOV, EDDM, Nordsee innen; Prag, Straßburg, Salzburg, Amsterdam außen).

Das Dateiformat beschreibt `fcy_daten/format.py`. Gelesen werden die Dateien von `private/flightlog/dienst.php` im Paket des Flight Log.

## So kommen die Daten auf den Server

1. Jeder Job rechnet, prüft und lädt seine Datei mit einer Beschreibung (`….json`: Größe, SHA-256, Fassung) in das Release `daten` hoch. Dafür reicht das eingebaute `GITHUB_TOKEN`; es gibt keine Secrets.
2. `dienst.php` holt sich die Dateien von `https://github.com/flycademy/flightlog-daten/releases/download/daten/…`:
   - fehlt eine Datei, sofort;
   - sonst im Hintergrund nach der Antwort, Wind spätestens alle 10 Minuten, Luftraum alle 6 Stunden, Gelände, Orte, Pisten und Hindernisse täglich (Hindernisse nach einer Woche ohne Prüfung vor der Antwort).
3. Der Dienst tauscht eine Datei nur aus, wenn Größe und Prüfsumme zur Beschreibung passen. Klappt ein Abruf nicht, bleibt die vorige Datei.

**Einrichten:** nichts. Gelände und Orte einmal von Hand starten (Actions → **Gelände** bzw. **Orte** → „Run workflow“), ebenso **Hindernisse** beim ersten Mal, damit die Datei vor dem ersten Lauf nach Plan da ist. Danach laufen Wind (alle 3 Stunden), Luftraum und Hindernisse (täglich), Pisten (wöchentlich) und Orte (monatlich) von selbst.

## Prüfen

- **Ergebnisse ansehen:** Mit „Ergebnis ablegen“ landet die erzeugte Datei im Zweig `ergebnis-…`, zum Nachprüfen.
- **Tests:** `python tests/test_wind.py`, `python tests/test_gelaende_orte.py`, `python tests/test_veroeffentlichen.py`, `python tests/test_luftraum.py`, `python tests/test_luftraum_dfs.py`, `python tests/test_pisten.py` und `python tests/test_hindernisse.py` laufen mit künstlichen Daten ohne Netz. Sie laufen auch bei jedem Push.

## Lizenzen der Daten

- **Wind:** Quelle Deutscher Wetterdienst. Die Daten sind verändert: auf feste Höhen und ein 0,1°-Gitter umgerechnet.
- **Gelände:** Copernicus DEM GLO-30, verändert (Höchstwert je 30″-Zelle, angehoben auf Gipfelhöhen aus GeoNames, CC BY 4.0). Vorgeschriebener Hinweis:
  „produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM-30.“
- **Orte:** GeoNames, CC BY 4.0.
- **Luftraum:** open flightmaps association, OFMA General Users' License ([openflightmaps.org/about](https://openflightmaps.org/about/)): Nutzung auch kommerziell; open flightmaps ist immer als Quelle zu nennen; Fehler sind an open flightmaps zu melden, und die App gibt ihren Nutzern dafür einen Weg (Link in der Statuszeile der Karte). Die Daten sind nicht zertifiziert und nie Primärquelle für die Navigation; maßgeblich bleiben ICAO-Karte, AIP und NOTAM. Verändert: umgewandelt, Umrisse vereinfacht.
- **Lufträume (luftraum-dfs.bin):** © DFS Deutsche Flugsicherung GmbH, Datensatz ED Airspace, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Verändert: umgewandelt, Umrisse vereinfacht, Arten zusammengefasst. Flugplätze, Meldepunkte, Umriss und die Ergänzungen: open flightmaps wie oben. Maßgeblich bleiben ICAO-Karte, AIP, NOTAM und AUP.
- **Flugplätze und Pisten:** OurAirports, gemeinfrei. Maßgeblich bleiben die Angaben der AIP.
- **Hindernisse:** © DFS Deutsche Flugsicherung GmbH, Datensatz ED Obstacles Area 1, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Verändert: umgewandelt, laufender und nächster AIRAC-Zyklus vereinigt. Maßgeblich bleiben ICAO-Karte, AIP und NOTAM.
