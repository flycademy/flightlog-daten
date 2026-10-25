"""Künstliche Datendateien (wind.bin, gelaende.bin, orte.bin) für die Tests der Server-Abfrage (dienst.php) und der App.

Wind (0,1°-Gitter 50–54° N, 8–13° E, Lauf = Parameter):
  u = 10 + 0,002·ft + 0,1·s + (lat − 52) kt,  v = −5 + 0,5·(lon − 10) kt,  t = 15 − 2·ft/1000 °C
  fehlt (unter Gelände): lat ≥ 53,5 und ft ≤ 2000
Plätze: EDVE, EDDH, EDDV, EDVM — t2m = 10 + 0,1·s, td2m = 5, pmsl = 1013 + 0,1·s, u10 = 5, v10 = 0, vmax10 = 12 (kt); vmax10 fehlt bei +0 h
Gelände (Kacheln 50–54° N, 8–13° E): Zelle (Zeile r von Nord, Spalte c) = 10·(lat−50) + (lon−8) + r + c  [m];
  in N52E010 ein Gipfel 999 m in Zeile 40, Spalte 66; N53E008 ist Meer; N50E012 fehlt
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F  # noqa: E402

HOEHEN = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 10000, 12000, 14000]
SCHRITTE = list(range(0, 49))
BODEN = list(range(0, 49))
G = {"lat0": 50.0, "lon0": 8.0, "d": 0.1, "nlat": 41, "nlon": 51}


def wind_felder():
    s = np.array(SCHRITTE, float)[:, None, None, None]
    ft = np.array(HOEHEN, float)[None, :, None, None]
    lat = (G["lat0"] + np.arange(G["nlat"]) * G["d"])[None, None, :, None]
    lon = (G["lon0"] + np.arange(G["nlon"]) * G["d"])[None, None, None, :]
    shp = (len(SCHRITTE), len(HOEHEN), G["nlat"], G["nlon"])
    u = np.broadcast_to(10 + 0.002 * ft + 0.1 * s + (lat - 52), shp).copy()
    v = np.broadcast_to(-5 + 0.5 * (lon - 10) + 0 * s + 0 * ft + 0 * lat, shp).copy()
    t = np.broadcast_to(15 - 2 * ft / 1000 + 0 * s + 0 * lat + 0 * lon, shp).copy()
    maske = np.broadcast_to((lat >= 53.5 - 1e-9) & (ft <= 2000), shp)
    for a in (u, v, t):
        a[maske] = np.nan
    return u, v, t


def platz_reihe():
    b = np.zeros((len(BODEN), 6))
    for i, st in enumerate(BODEN):
        b[i] = [10 + 0.1 * st, 5, 1013 + 0.1 * st, 5, 0, 12 if st > 0 else np.nan]
    return b


def gelaende_kacheln():
    k = {}
    for la in range(50, 54):
        for lo in range(8, 13):
            if (la, lo) == (53, 8):
                k[(la, lo)] = "meer"; continue
            if (la, lo) == (50, 12):
                k[(la, lo)] = None; continue
            r = np.arange(120)[:, None]; c = np.arange(120)[None, :]
            a = (10 * (la - 50) + (lo - 8) + r + c).astype(np.int16)
            if (la, lo) == (52, 10):
                a[40, 66] = 999
            k[(la, lo)] = a
    return k


ORTE = [
    ("Braunschweig", "Niedersachsen", "DE", 52.26594, 10.52673, 248292, "P", "2945024"),
    ("Wolfsburg", "Niedersachsen", "DE", 52.42452, 10.7815, 123064, "P", "2805753"),
    ("Gifhorn", "Niedersachsen", "DE", 52.47774, 10.5511, 41000, "P", "2920236"),
    ("Waggum", "Niedersachsen", "DE", 52.32, 10.55, 0, "X", "6551111"),
    ("Bad Harzburg", "Niedersachsen", "DE", 51.88268, 10.56157, 21700, "P", "2953416"),
    ("Brocken", "Sachsen-Anhalt", "DE", 51.8, 10.6167, 0, "T", "2911111"),
    ("Steinhuder Meer", "Niedersachsen", "DE", 52.46, 9.34, 0, "H", "2922222"),
    ("München", "Bayern", "DE", 48.13743, 11.57549, 1260391, "P", "2867714"),
    ("Mönchengladbach", "Nordrhein-Westfalen", "DE", 51.18539, 6.44172, 261454, "P", "2869894"),
    ("Neustadt am Rübenberge", "Niedersachsen", "DE", 52.50462, 9.45871, 44000, "P", "2864276"),
    ("Neustadt an der Weinstraße", "Rheinland-Pfalz", "DE", 49.35009, 8.13886, 53000, "P", "2864435"),
    ("Helmstedt", "Niedersachsen", "DE", 52.2279, 11.0097, 25000, "P", "2906595"),
    ("Zürich", "Zurich", "CH", 47.36667, 8.55, 341730, "P", "2657896"),
    ("Kraków", "Lesser Poland", "PL", 50.06143, 19.93658, 755050, "P", "3094802"),
]


def orte_zeilen():
    rows = []
    for name, land1, cc, la, lo, ew, kl, gid in ORTE:
        keys = {F.normiere(name): 0}
        if name == "München":
            keys.update({"munich": 0, "monaco di baviera": 0})
        for k in list(keys):
            for w in k.split(" ")[1:]:
                if len(w) >= 4 and w not in keys:
                    keys[w] = 1
        for k, teil in keys.items():
            rows.append((k, gid, name, land1, cc, la, lo, ew, kl, teil))
    return rows


def schreibe_alle(ordner: str, lauf_iso: str) -> None:
    os.makedirs(os.path.join(ordner, "wx"), exist_ok=True)
    u, v, t = wind_felder()
    pl = [(c, platz_reihe()) for c in ("EDVE", "EDDH", "EDDV", "EDVM")]
    F.schreibe_wind(os.path.join(ordner, "wx", "wind.bin"),
                    {"modell": "ICON-D2", "lauf": lauf_iso, "erzeugt": lauf_iso, "quelle": "Testdaten",
                     "hoehen_ft": HOEHEN, "hoehe": "MSL", "schritte_h": SCHRITTE, "boden_schritte_h": BODEN, "gitter": G},
                    u, v, t, pl)
    F.schreibe_gelaende(os.path.join(ordner, "gelaende.bin"),
                        {"lat0": 50, "lat1": 54, "lon0": 8, "lon1": 13, "n": 120, "quelle": "Testdaten", "erzeugt": lauf_iso},
                        gelaende_kacheln())
    F.schreibe_orte(os.path.join(ordner, "orte.bin"), {"quelle": "Testdaten", "erzeugt": lauf_iso}, orte_zeilen())


if __name__ == "__main__":
    import datetime as dt
    ordner = sys.argv[1]
    if len(sys.argv) > 2:
        lauf = sys.argv[2]
    else:
        n = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
        n -= dt.timedelta(hours=n.hour % 3 + 3)
        lauf = n.strftime("%Y-%m-%dT%H:00:00Z")
    schreibe_alle(ordner, lauf)
    print(ordner, lauf)
