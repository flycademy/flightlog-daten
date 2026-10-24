# flightlog-daten

Daten für den FlyCademy Flight Log (training.flycademy.de/flightlog), aufbereitet mit GitHub Actions und per FTPS in den
nicht öffentlichen Datenordner der Lernplattform geladen. Der Flight Log fragt nur den eigenen Server; kein Browser
spricht mit DWD, Copernicus oder GeoNames.

| Job | Quelle | Wann | Datei auf dem Server |
| --- | --- | --- | --- |
| Wind ICON-D2 | Deutscher Wetterdienst, ICON-D2 (opendata.dwd.de) | alle 3 Stunden | `private/flightlog/daten/wx/wind.bin` |
| Gelände | Copernicus DEM GLO-30 (AWS Open Data) | von Hand, einmal | `private/flightlog/daten/gelaende.bin` |
| Orte | GeoNames (download.geonames.org) | monatlich | `private/flightlog/daten/orte.bin` |

## Was die Jobs rechnen

- **Wind:**
  - u, v und t der ICON-D2-Modellflächen werden auf feste Höhen umgerechnet: 1000–8000 ft in 1000-ft-Schritten, dazu 10 000, 12 000 und 14 000 ft MSL.
  - Danach mittelt der Job sie auf ein 0,1°-Gitter, 0 bis 48 Stunden, alle 3 Stunden.
  - An jedem Flugplatz im Gebiet (OurAirports) kommen stündliche Bodenwerte dazu. Die Temperatur wird auf die Platzhöhe umgerechnet.
  - Vor dem Hochladen prüft der Job die Werte und vergleicht einige Plätze mit Open-Meteo (Modell icon_d2).
- **Gelände:** je 30″-Zelle (rund 0,5 NM) der höchste Geländepunkt, für 35–60° N und 10° W–30° E.
- **Orte:**
  - Orte, Ortsteile, Berge und Seen von DE, AT, CH, LI, LU, NL, BE, DK, PL, CZ, SK, HU, SI, HR, IT und FR.
  - Angezeigt wird der deutsche Name, wenn GeoNames einen hat.

Das Dateiformat beschreibt `fcy_daten/format.py`. Gelesen werden die Dateien von `private/flightlog/dienst.php` im Paket des Flight Log.

## Einrichten

1. **Plesk:**
   - Ein **zusätzliches FTP-Konto** anlegen, Verzeichnis `/private/flightlog/daten`.
   - So kann das Konto nur dort schreiben, nicht in die Lernplattform.
2. **GitHub:** Settings → Secrets and variables → Actions → New repository secret:
   - `FTP_HOST`: `w11.pixelx.cloud`
   - `FTP_USER`: Name des neuen FTP-Kontos
   - `FTP_PASS`: dessen Passwort
   - `FTP_DIR`: leer lassen. Nur setzen, wenn das Konto nicht direkt im Datenordner beginnt.
3. **Erster Lauf:** Unter Actions zuerst **Gelände** und **Orte**, dann **Wind ICON-D2** mit „Run workflow“ starten. Danach laufen Wind und Orte von selbst.

Solange die Secrets fehlen, rechnen die Jobs trotzdem und bleiben grün, laden aber nichts hoch. Im Lauf steht dann die Warnung **„Nicht hochgeladen“**. Sind die Secrets eingetragen, aber falsch, schlägt der Lauf fehl.

Die Uploads gehen über explizites FTPS (TLS). Jede Datei wird zuerst unter `….neu` abgelegt und dann umbenannt.
So sieht der Flight Log nie eine halbe Datei.

## Prüfen

- **Ergebnisse ansehen:** Mit „Ergebnis ablegen“ landet die erzeugte Datei im Zweig `ergebnis-…`, zum Nachprüfen.
- **Tests:** `python tests/test_wind.py` und `python tests/test_gelaende_orte.py` laufen mit künstlichen Daten ohne Netz. Sie laufen auch bei jedem Push.

## Lizenzen der Daten

- **Wind:** Quelle Deutscher Wetterdienst. Die Daten sind verändert: auf feste Höhen und ein 0,1°-Gitter umgerechnet.
- **Gelände:** Copernicus DEM GLO-30. © DLR e.V. 2010–2014 und © Airbus Defence and Space GmbH 2014–2018, bereitgestellt unter COPERNICUS durch die Europäische Union und die ESA. Die Daten sind verändert: Höchstwert je Zelle.
- **Orte:** GeoNames, CC BY 4.0.
- **Flugplätze:** OurAirports, gemeinfrei.
