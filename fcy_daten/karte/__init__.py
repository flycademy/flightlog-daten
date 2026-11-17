"""ICAO-Optik für ganz Deutschland: Kartenkacheln im Stil der Übungskarte Harz–Elbe (Theorie, Entwurf 2.0) aus offenen Daten.

Teile:
  daten.py     Topografie (BKG DLM250), Grenze, Flugplätze (BKG, OurAirports, Platzhöhen des Flight Log), Höhen (BKG DGM200)
  gelaende.py  Höhenschichten und Schummerung aus Copernicus GLO-30 als Raster in Web-Mercator
  luftfahrt.py Lufträume, Funkfeuer, Hindernisse (DFS, CC BY 4.0) und VFR-Meldepunkte (open flightmaps) je AIRAC-Zyklus
  zeichne.py   Beschriftung je Zoomstufe für ganz Deutschland, dann Blöcke zeichnen und in Kacheln schneiden
  buendel.py   Kacheln zu Bündeln für dienst.php (Übersicht und Regionen)

Nur Lernmaterial, nicht zur Navigation.
"""
