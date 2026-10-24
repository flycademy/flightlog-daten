"""Ortsnamen für die Ortssuche des Flight Log aus GeoNames (CC BY 4.0).

Orte (Städte, Dörfer, Ortsteile), Berge und Seen der Länder unten. Angezeigt wird der deutsche Name, wenn GeoNames einen hat
(alternateNamesV2, Sprache „de“: München, Köln, Mailand), sonst der Name vor Ort. Suchschlüssel: normierter Name (format.normiere),
dazu jedes weitere Wort ab 4 Buchstaben („Harzburg“ findet „Bad Harzburg“) und bei Orten ab 20 000 Einwohnern
die lateinisch geschriebenen Namen anderer Sprachen („Mailand“, „Prag“). Ausgabe: orte.bin (Format: format.py).

Aufruf: python -m fcy_daten.orte --aus out/orte.bin [--laender DE AT …] [--quelle URL]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import zipfile

from . import format as F
from . import netz

QUELLE = "https://download.geonames.org/export/dump"
LAENDER = ["DE", "AT", "CH", "LI", "LU", "NL", "BE", "DK", "PL", "CZ", "SK", "HU", "SI", "HR", "IT", "FR"]
# Klassen: P = Ort, X = Ortsteil, T = Berg/Hügel, H = See/Stausee
P_AUS = {"PPLH", "PPLQ", "PPLW", "PPLCH"}
T_JA = {"MT", "MTS", "PK", "PKS", "HLL", "HLLS"}
H_JA = {"LK", "LKS", "RSV", "LKN"}
DEUTSCH = {"Lower Saxony": "Niedersachsen", "Bavaria": "Bayern", "North Rhine-Westphalia": "Nordrhein-Westfalen",
           "Saxony": "Sachsen", "Saxony-Anhalt": "Sachsen-Anhalt", "Thuringia": "Thüringen", "Hesse": "Hessen",
           "Baden-Wuerttemberg": "Baden-Württemberg", "Baden-Württemberg": "Baden-Württemberg",
           "Baden-Wurttemberg": "Baden-Württemberg", "State of Berlin": "Berlin",
           "Rheinland-Pfalz": "Rheinland-Pfalz", "Rhineland-Palatinate": "Rheinland-Pfalz",
           "Mecklenburg-Vorpommern": "Mecklenburg-Vorpommern", "Mecklenburg-Western Pomerania": "Mecklenburg-Vorpommern",
           "Schleswig-Holstein": "Schleswig-Holstein", "Brandenburg": "Brandenburg", "Berlin": "Berlin",
           "Hamburg": "Hamburg", "Bremen": "Bremen", "Saarland": "Saarland",
           "Lower Austria": "Niederösterreich", "Upper Austria": "Oberösterreich", "Styria": "Steiermark",
           "Carinthia": "Kärnten", "Tyrol": "Tirol", "Vienna": "Wien", "Salzburg": "Salzburg",
           "Vorarlberg": "Vorarlberg", "Burgenland": "Burgenland"}
LATEIN = re.compile(r"^[A-Za-zÀ-ɏ' .\-]+$")


# Vorsätze, die vor dem eigentlichen Namen einer Region stehen (deutsche und englische GeoNames-Namen)
VORSATZ = re.compile(r"^(Freistaat|Land|Bundesland|Kanton|Woiwodschaft|Gespanschaft|Komitat|Region|Provinz|Gemeinde|Stadtgemeinde|"
                     r"Urban Municipality of|Municipality of|County of|State of)\s+")
NACHSATZ = re.compile(r"\s+(County|Region|Voivodeship)$")


def regionsname(x: str) -> str:
    x = VORSATZ.sub("", x.strip())
    return NACHSATZ.sub("", x).strip()


def lese_admin1(text: str) -> dict:
    """Code „DE.06“ → (Name, geonameid)."""
    out = {}
    for line in text.splitlines():
        t = line.split("\t")
        if len(t) >= 2:
            out[t[0]] = (t[1], t[3] if len(t) > 3 else "")
    return out


def admin1_namen(admin1: dict, deutsch: dict) -> dict:
    """Code → angezeigter Regionsname: deutscher GeoNames-Name, sonst feste Übersetzung, sonst der Name ohne Vorsatz."""
    out = {}
    for code, (name, gid) in admin1.items():
        if gid and gid in deutsch:
            out[code] = regionsname(deutsch[gid])
        else:
            out[code] = DEUTSCH.get(name) or regionsname(name)
    return out


def deutsche_namen(zipdaten: bytes, ids: set) -> dict:
    """geonameid → deutscher Name (bevorzugter zuerst, ohne umgangssprachliche und historische Namen)."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(zipdaten)) as z:
        name = next(n for n in z.namelist() if n.startswith("alternateNamesV2") and n.endswith(".txt"))
        with z.open(name) as f:
            for raw in io.TextIOWrapper(f, encoding="utf-8"):
                t = raw.rstrip("\n").split("\t")
                if len(t) < 8 or t[2] != "de" or t[1] not in ids:
                    continue
                if (len(t) > 6 and t[6] == "1") or (len(t) > 7 and t[7] == "1"):
                    continue
                bevorzugt = t[4] == "1"
                if t[1] not in out or (bevorzugt and not out[t[1]][1]):
                    out[t[1]] = (t[3], bevorzugt)
    return {k: v[0] for k, v in out.items()}


def ids_aus(tsv: str) -> set:
    return {line.split("\t", 1)[0] for line in tsv.splitlines() if line}


def zeilen_aus(tsv: str, admin1: dict, deutsch: dict | None = None) -> list[tuple]:
    deutsch = deutsch or {}
    rows = []
    for line in tsv.splitlines():
        t = line.split("\t")
        if len(t) < 15:
            continue
        gid, name, ascii_, alt, la, lo, fcl, fco, cc, a1, pop = t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[10], t[14]
        if fcl == "P" and fco not in P_AUS:
            kl = "X" if fco == "PPLX" else "P"
        elif fcl == "T" and fco in T_JA:
            kl = "T"
        elif fcl == "H" and fco in H_JA:
            kl = "H"
        else:
            continue
        try:
            ew = int(pop or 0)
        except ValueError:
            ew = 0
        land1 = admin1.get(f"{cc}.{a1}", "")
        if isinstance(land1, tuple):
            land1 = DEUTSCH.get(land1[0]) or regionsname(land1[0])
        voll = {F.normiere(name), F.normiere(ascii_)}          # ganze Namen: teil = 0
        if gid in deutsch:
            voll.add(F.normiere(deutsch[gid]))
            name = deutsch[gid]
        if ew >= 20000 and alt:
            for x in alt.split(","):
                x = x.strip()
                if 2 < len(x) <= 40 and LATEIN.match(x):
                    voll.add(F.normiere(x))
        schl = {k: 0 for k in voll}
        for k in voll:                                         # innere Wörter: teil = 1
            for x in k.split(" ")[1:]:
                if len(x) >= 4 and x not in schl:
                    schl[x] = 1
        for k, teil in schl.items():
            if len(k) >= 2:
                rows.append((k, gid, name, land1, cc, float(la), float(lo), ew, kl, teil))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--laender", nargs="+", default=LAENDER)
    ap.add_argument("--quelle", default=QUELLE)
    a = ap.parse_args(argv)
    q = a.quelle.rstrip("/")
    admin1_roh = lese_admin1(netz.hole(f"{q}/admin1CodesASCII.txt").decode("utf-8"))
    tsvs = {}
    for cc in a.laender:
        z = zipfile.ZipFile(io.BytesIO(netz.hole(f"{q}/{cc}.zip", timeout=300)))
        tsvs[cc] = z.read(f"{cc}.txt").decode("utf-8")
    ids = set().union(*(ids_aus(t) for t in tsvs.values()))
    ids |= {gid for _, gid in admin1_roh.values() if gid}
    deutsch = deutsche_namen(netz.hole(f"{q}/alternateNamesV2.zip", timeout=900), ids)
    print(f"  deutsche Namen: {len(deutsch)}", flush=True)
    admin1 = admin1_namen(admin1_roh, deutsch)
    rows = []
    for cc, tsv in tsvs.items():
        r = zeilen_aus(tsv, admin1, deutsch)
        print(f"  {cc}: {len(r)} Schlüssel", flush=True)
        rows += r
    kopf = {"quelle": "GeoNames (geonames.org), CC BY 4.0", "laender": a.laender,
            "erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    k = F.schreibe_orte(a.aus, kopf, rows)
    print(f"geschrieben: {a.aus} · {k['anzahl']} Schlüssel", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
