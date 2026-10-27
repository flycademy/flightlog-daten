"""Pisten aus OurAirports (runways.csv, gemeinfrei) für den Flight Log — wöchentlich.

  python -m fcy_daten.pisten --aus out/pisten.bin [--csv runways.csv]

Ablauf:
  1. runways.csv von OurAirports laden (davidmegginson.github.io/ourairports-data, sonst dasselbe Repository über
     raw.githubusercontent.com). Den Stand nennt der letzte Commit der Datei (GitHub-API), sonst der Abruftag.
  2. Je Zeile mit vierstelliger Platzkennung (A–Z, 0–9; so fragt die App) und nicht geschlossener Bahn je Richtung
     (le, he) mit Kennung 01–36: id, dir = Zahl × 10, len = Länge in m, lda = Länge abzüglich versetzter Schwelle in m,
     surf = Belag. Gerechnet genau wie die App bis Build 25j aus der CSV im Browser (parseRwyCsv): Länge aus ft mit
     0,3048 und kaufmännisch gerundet, Länge 0 = unbekannt, lda nie unter 0, Richtungszahl wie parseInt.
  3. Datei FCYR schreiben (fcy_daten/format.py): je Anfangszeichen der Kennung ein gzip-JSON, damit der Datendienst nur
     einen kleinen Teil liest. „erzeugt“ ist der Stand der Quelle — gleiche Eingabe, gleiche Datei.

Damit ruft der Browser OurAirports (GitHub Pages) nicht mehr ab; die Pisten kommen über den eigenen Datendienst.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import math
import os
import re
import sys

from . import format as F
from . import netz

QUELLEN = ["https://davidmegginson.github.io/ourairports-data/runways.csv",
           "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/runways.csv"]
COMMITS = "https://api.github.com/repos/davidmegginson/ourairports-data/commits?path=runways.csv&per_page=1"
KENNUNG = re.compile(r"^[A-Z0-9]{4}$")
ZAHL = re.compile(r"^[+-]?\d+")
SPALTEN = ["id", "airport_ref", "airport_ident", "length_ft", "width_ft", "surface", "lighted", "closed", "le_ident",
           "le_latitude_deg", "le_longitude_deg", "le_elevation_ft", "le_heading_degT", "le_displaced_threshold_ft",
           "he_ident", "he_latitude_deg", "he_longitude_deg", "he_elevation_ft", "he_heading_degT", "he_displaced_threshold_ft"]


def _js_runden(x: float) -> int:
    """Math.round wie in JavaScript (x.5 nach oben)."""
    return math.floor(x + 0.5)


def _js_zahl(s: str) -> float:
    """parseFloat(s) || 0"""
    m = re.match(r"^\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", s or "")
    if not m:
        return 0.0
    v = float(m.group(0))
    return 0.0 if (v != v) else v


def richtungen(zeile: list[str]) -> list[list]:
    """Eine Zeile der CSV → Richtungen [[id, dir, len, lda, surf], …] (leer bei geschlossener Bahn)."""
    f = zeile + [""] * (20 - len(zeile))
    if f[7] == "1":
        return []
    len_ft = _js_zahl(f[3])
    lang = _js_runden(len_ft * 0.3048) or None
    surf = (f[5] or "").upper()
    out = []
    for ident, disp in ((f[8], f[13]), (f[14], f[19])):
        idn = (ident or "").strip()
        m = ZAHL.match(idn)
        if not idn or not m:
            continue
        n = int(m.group(0))
        if n < 1 or n > 36:
            continue
        d_ft = _js_zahl(disp)
        lda = _js_runden(max(0.0, len_ft - d_ft) * 0.3048) if lang is not None else None
        out.append([idn, n * 10, lang, lda, surf])
    return out


def aufbereiten(text: str) -> dict:
    plaetze: dict[str, list] = {}
    r = csv.reader(io.StringIO(text))
    kopf = next(r)
    if [k.strip() for k in kopf[:20]] != SPALTEN:
        raise SystemExit(f"runways.csv: unerwartete Spalten {kopf[:20]}")
    for z in r:
        if len(z) < 15:
            continue
        k = z[2]
        if not KENNUNG.match(k):
            continue
        rw = richtungen(z)
        plaetze.setdefault(k, []).extend(rw)
    return plaetze


def stand_der_quelle() -> str:
    """Datum des letzten Commits von runways.csv (UTC), sonst heute."""
    try:
        import json
        import requests
        h = {"Accept": "application/vnd.github+json", "User-Agent": netz.UA}
        if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
            h["Authorization"] = "Bearer " + (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        j = requests.get(COMMITS, headers=h, timeout=30).json()
        return j[0]["commit"]["committer"]["date"][:10]
    except Exception:  # noqa: BLE001 — nur für die Anzeige
        return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--csv", help="runways.csv von Platte statt aus dem Netz (Tests)")
    ap.add_argument("--stand", help="Stand der Quelle (JJJJ-MM-TT) statt aus der GitHub-API")
    ap.add_argument("--quelle", action="append", help="andere Adresse(n) für runways.csv (Tests)")
    a = ap.parse_args(argv)
    if a.csv:
        roh = open(a.csv, "rb").read()
    else:
        roh, fehler = None, []
        for u in (a.quelle or QUELLEN):
            try:
                roh = netz.hole(u, timeout=120)
                print(f"geladen: {u} ({len(roh) // 1024} kB)", flush=True)
                break
            except Exception as e:  # noqa: BLE001 — nächste Quelle
                fehler.append(str(e))
        if roh is None:
            raise SystemExit("runways.csv nicht abrufbar: " + " · ".join(fehler))
    plaetze = aufbereiten(roh.decode("utf-8-sig"))
    stand = a.stand or (dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d") if a.csv else stand_der_quelle())
    kopf = {"quelle": "OurAirports (ourairports.com, gemeinfrei)", "stand": stand,
            "csv_sha256": hashlib.sha256(roh).hexdigest(), "erzeugt": stand,
            "lauf": f"{stand}@{hashlib.sha256(roh).hexdigest()[:12]}"}
    K = F.schreibe_pisten(a.aus, kopf, plaetze)
    print(f"geschrieben: {a.aus} · {K['plaetze']} Plätze, {K['richtungen']} Richtungen, {len(K['gruppen'])} Gruppen, "
          f"{os.path.getsize(a.aus) // 1024} kB, Stand {stand}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
