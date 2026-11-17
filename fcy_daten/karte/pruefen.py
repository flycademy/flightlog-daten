"""Prüfung der ICAO-Optik vor dem Veröffentlichen: Verzeichnis karte.bin und alle Bündel der Zyklen darin.

  - Verzeichnis lesbar, höchstens zwei Zyklen, je Zyklus Gültigkeit 28 Tage, Umriss Deutschlands vorhanden
  - jedes Bündel: Kennung FCYK, Größe und Prüfsumme wie im Verzeichnis, Kopf (Zyklus, Gitter), Index innerhalb der Datei,
    jede Kachel ein WebP
  - ganz Deutschland (--voll): Kacheln je Zoomstufe über einer Mindestzahl, Kachel über EDVE (52,32° N, 10,56° E) in allen Stufen
Aufruf: python -m fcy_daten.karte.pruefen <karte.bin> [--voll | --gebiet]
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import sys

from . import buendel as BU

MIN = {8: 40, 9: 150, 10: 500, 11: 2000, 12: 8000}       # Kacheln (Maßstab 1) für ganz Deutschland mindestens


def kachel(z, lon, lat):
    n = 2 ** z
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)


def lies_buendel(pfad):
    with open(pfad, "rb") as f:
        d = f.read()
    assert d[:4] == b"FCYK", "Kennung"
    n = struct.unpack("<I", d[4:8])[0]
    k = json.loads(d[8:8 + n])
    return d, k


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    pfad = argv[0]; voll = "--voll" in argv
    v = BU.verzeichnis_lesen(pfad)
    ordner = os.path.dirname(pfad)
    fehler = []
    assert 1 <= len(v["zyklen"]) <= 2, "Zyklen im Verzeichnis"
    if not v.get("deckung"):
        fehler.append("Umriss Deutschlands fehlt")
    for z in v["zyklen"]:
        anzahl = {}; edve = set()
        for name, m in z["dateien"].items():
            p = os.path.join(ordner, name)
            if not os.path.exists(p):
                continue                                  # Zyklus aus dem vorigen Verzeichnis, nicht neu gerechnet
            d, k = lies_buendel(p)
            if len(d) != m["groesse"] or hashlib.sha256(d).hexdigest() != m["sha256"]:
                fehler.append(f"{name}: Größe oder Prüfsumme"); continue
            if k.get("zyklus") != z["zyklus"]:
                fehler.append(f"{name}: Zyklus im Kopf {k.get('zyklus')}")
            for gk, g in k["gitter"].items():
                zz, s = map(int, gk.split("x"))
                for i in range(g["nx"] * g["ny"]):
                    o, l = struct.unpack("<II", d[g["ab"] + 8 * i:g["ab"] + 8 * i + 8])
                    if o == 0xFFFFFFFF:
                        continue
                    if o + l > len(d) or d[o:o + 4] != b"RIFF" or d[o + 8:o + 12] != b"WEBP":
                        fehler.append(f"{name}: Kachel {gk}/{i} beschädigt"); break
                    if s == 1:
                        anzahl[zz] = anzahl.get(zz, 0) + 1
                    x, y = g["tx0"] + i % g["nx"], g["ty0"] + i // g["nx"]
                    if (x, y) == kachel(zz, 10.56, 52.32):
                        edve.add((zz, s))
        if voll:
            for zz, mn in MIN.items():
                if anzahl.get(zz, 0) < mn:
                    fehler.append(f"Zyklus {z['zyklus']}: Zoom {zz} nur {anzahl.get(zz, 0)} Kacheln (mindestens {mn})")
            for zz in range(8, 13):
                if (zz, 1) not in edve:
                    fehler.append(f"Zyklus {z['zyklus']}: keine Kachel über EDVE in Zoom {zz}")
        print(f"Zyklus {z['zyklus']} ({z['ab']} – {z['bis']}): Kacheln je Zoom {dict(sorted(anzahl.items()))}, "
              f"{len(z['dateien'])} Bündel, {sum(m['groesse'] for m in z['dateien'].values()) / 1e6:.0f} MB", flush=True)
    if fehler:
        print("FEHLER:\n  " + "\n  ".join(fehler[:30])); return 1
    print("Prüfung bestanden"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
