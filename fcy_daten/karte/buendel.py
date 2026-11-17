"""Kacheln der ICAO-Optik zu Bündeln für dienst.php (Format wie harz-elbe.bin aus Build 25v) und ein Verzeichnis karte.bin.

Je AIRAC-Zyklus:
  karte-<Zyklus>-u.bin           Übersicht: Zoomstufen 8 bis 10 für ganz Deutschland
  karte-<Zyklus>-<B>-<L>.bin     Zoomstufen 11 und 12 der Region B…B+2° N, L…L+2° E (Mitte der Kachel entscheidet)
Bündel: b"FCYK", uint32 Kopflänge, Kopf (JSON), je Zoomstufe und Maßstab ein Gitter mit 8 Byte je Kachel (Anfang, Länge;
0xFFFFFFFF = keine Kachel), dann die WebP-Bilder.
Verzeichnis karte.bin: b"FCYM", uint32 Länge, JSON {format, zyklen: [{zyklus, ab, bis, stand, regionen, dateien: {name: {groesse, sha256}}}],
  deckung (Umriss Deutschlands, vereinfacht, [[lon, lat], …] je Teil), quellen, lizenz}

Aufruf: python -m fcy_daten.karte.buendel --kacheln <Kachelordner> --zyklus 2611 --ab 2026-10-29 --aus <Ordner> [--verzeichnis karte.bin --alt <karte.bin>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import struct

REGION = 2.0
UEBERSICHT_ZMAX = 10
QUELLEN = ("Topografie: © GeoBasis-DE / BKG (2026), dl-de/by-2-0, Daten verändert · Lufträume, Funkfeuer, Hindernisse: © DFS Deutsche "
           "Flugsicherung GmbH, CC BY 4.0, verändert · Gelände: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus "
           "Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved · Flugplätze: "
           "OurAirports (gemeinfrei), open flightmaps (OFMA General Users' License) · VFR-Meldepunkte: open flightmaps")


def region(z, x, y):
    n = 2 ** z
    lon = (x + 0.5) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return int(math.floor(lat / REGION) * REGION), int(math.floor(lon / REGION) * REGION)


def schreibe(pfad, kopf, kacheln):
    """kacheln: {(z, s, x, y): Dateipfad} → Bündel; Rückgabe {groesse, sha256, n}"""
    gitter, eintraege = {}, []
    for (z, s) in sorted({(k[0], k[1]) for k in kacheln}):
        xs = [k[2] for k in kacheln if k[0] == z and k[1] == s]; ys = [k[3] for k in kacheln if k[0] == z and k[1] == s]
        tx0, tx1, ty0, ty1 = min(xs), max(xs), min(ys), max(ys)
        liste = [kacheln.get((z, s, x, y)) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
        gitter[f"{z}x{s}"] = {"tx0": tx0, "ty0": ty0, "nx": tx1 - tx0 + 1, "ny": ty1 - ty0 + 1}
        eintraege.append((f"{z}x{s}", liste))
    kopf = dict(kopf); kopf.update({"gitter": gitter, "n": len(kacheln)})
    for _ in range(3):
        kb = json.dumps(kopf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        pos = 8 + len(kb)
        for name, liste in eintraege:
            gitter[name]["ab"] = pos; pos += 8 * len(liste)
        kopf["gitter"] = gitter
    kb = json.dumps(kopf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(kb) < 65536, len(kb)
    pos = 8 + len(kb)
    for name, liste in eintraege:
        assert gitter[name]["ab"] == pos, (name, gitter[name]["ab"], pos); pos += 8 * len(liste)
    daten_ab = pos
    tmp = pfad + ".neu"
    with open(tmp, "wb") as f:
        f.write(b"FCYK" + struct.pack("<I", len(kb)) + kb)
        off = daten_ab; idx = []
        for name, liste in eintraege:
            for fn in liste:
                if fn:
                    n = os.path.getsize(fn); idx.append(struct.pack("<II", off, n)); off += n
                else:
                    idx.append(struct.pack("<II", 0xFFFFFFFF, 0))
        f.write(b"".join(idx))
        assert f.tell() == daten_ab
        for name, liste in eintraege:
            for fn in liste:
                if fn:
                    b = open(fn, "rb").read(); assert b[:4] == b"RIFF" and b[8:12] == b"WEBP", fn
                    f.write(b)
    os.replace(tmp, pfad)
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return {"groesse": os.path.getsize(pfad), "sha256": h.hexdigest(), "n": len(kacheln)}


def sammle(ordner):
    out = {}
    for z in sorted(os.listdir(ordner)):
        if not z.isdigit():
            continue
        for x in os.listdir(os.path.join(ordner, z)):
            for fn in os.listdir(os.path.join(ordner, z, x)):
                if not fn.endswith(".webp"):
                    continue
                y, s = (fn[:-8], 2) if fn.endswith("@2x.webp") else (fn[:-5], 1)
                out[(int(z), s, int(x), int(y))] = os.path.join(ordner, z, x, fn)
    return out


def verzeichnis_schreiben(pfad, inhalt):
    b = json.dumps(inhalt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(pfad + ".neu", "wb") as f:
        f.write(b"FCYM" + struct.pack("<I", len(b)) + b)
    os.replace(pfad + ".neu", pfad)


def verzeichnis_lesen(pfad):
    d = open(pfad, "rb").read()
    assert d[:4] == b"FCYM"
    n = struct.unpack("<I", d[4:8])[0]
    return json.loads(d[8:8 + n].decode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kacheln", required=True); ap.add_argument("--zyklus", required=True); ap.add_argument("--ab", required=True)
    ap.add_argument("--aus", required=True); ap.add_argument("--deckung", help="deckung.json (Umriss Deutschlands, vereinfacht)")
    ap.add_argument("--alt", help="bisheriges karte.bin (andere Zyklen übernehmen)"); ap.add_argument("--stand", default="")
    a = ap.parse_args(argv)
    os.makedirs(a.aus, exist_ok=True)
    K = sammle(a.kacheln)
    ab = dt.date.fromisoformat(a.ab); bis = ab + dt.timedelta(days=28)
    kopf0 = {"format": "FCYK", "zyklus": a.zyklus, "ab": a.ab, "bis": bis.isoformat(), "stand": a.stand or a.ab, "quellen": QUELLEN,
             "hinweis": "ICAO-Optik der FlyCademy im Stil der Übungskarte; Lernmaterial, nicht zur Navigation"}
    gruppen = {"u": {k: v for k, v in K.items() if k[0] <= UEBERSICHT_ZMAX}}
    for k, v in K.items():
        if k[0] > UEBERSICHT_ZMAX:
            b, l = region(k[0], k[2], k[3])
            gruppen.setdefault(f"{b}-{l}", {})[k] = v
    dateien = {}
    for g, kk in sorted(gruppen.items()):
        if not kk:
            continue
        name = f"karte-{a.zyklus}-{g}.bin"
        kopf = dict(kopf0); kopf["teil"] = g
        r = schreibe(os.path.join(a.aus, name), kopf, kk)
        dateien[name] = {"groesse": r["groesse"], "sha256": r["sha256"], "n": r["n"]}
        print(f"  {name}: {r['n']} Kacheln, {r['groesse'] / 1e6:.1f} MB", flush=True)
    zy = {"zyklus": a.zyklus, "ab": a.ab, "bis": bis.isoformat(), "stand": a.stand or a.ab, "region_grad": REGION,
          "uebersicht_zmax": UEBERSICHT_ZMAX, "zoom": [min(k[0] for k in K), max(k[0] for k in K)], "dateien": dateien}
    alt = verzeichnis_lesen(a.alt) if a.alt and os.path.exists(a.alt) else {"zyklen": []}
    heute = dt.date.today().isoformat()
    zyklen = [z for z in alt.get("zyklen", []) if z["zyklus"] != a.zyklus and z["bis"] > heute] + [zy]
    zyklen.sort(key=lambda z: z["ab"])
    inhalt = {"format": "FCYM", "zyklen": zyklen[-2:], "quellen": QUELLEN,
              "deckung": json.load(open(a.deckung)) if a.deckung else alt.get("deckung"),
              "erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    verzeichnis_schreiben(os.path.join(a.aus, "karte.bin"), inhalt)
    print(f"karte.bin: Zyklen {[z['zyklus'] for z in inhalt['zyklen']]}, {sum(d['groesse'] for d in dateien.values()) / 1e6:.0f} MB für {a.zyklus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
