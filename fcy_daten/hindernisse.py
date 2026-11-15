"""Luftfahrthindernisse aus dem DFS-Datensatz „ED Obstacles Area 1“ (AIXM 5.1, CC BY 4.0) für die MSA des Flight Log.

  python -m fcy_daten.hindernisse --aus out/hindernisse.bin [--xml datei.xml …] [--umriss luftraum.bin]

Ablauf:
  1. Die Übersichtsseiten der DFS (aip.dfs.de/datasets, scripts/getAmdtData.php?amdt=0 und 1) nennen den Datensatz des
     laufenden und des nächsten AIRAC-Zyklus. Beide laden. Der nächste fehlt bis etwa vier Wochen vor seinem Beginn; dann
     nur der laufende.
  2. Je Hindernisteil (VerticalStructurePart) Lage, Höhe der Spitze über MSL (elevation) und Höhe über Grund
     (verticalExtent), Art und Befeuerung. Beide Zyklen werden vereinigt: Ein Hindernis zählt, sobald es in einem der
     beiden Zyklen steht, mit der größeren Höhe. So kennt die MSA neue Hindernisse schon vor dem Zyklus, in dem sie
     erscheinen; ein gestrichenes Hindernis zählt bis zum Ende des laufenden Zyklus weiter (auf der sicheren Seite).
  3. Abdeckung: Die DFS führt nur Hindernisse in Deutschland. Der Umriss Deutschlands kommt aus luftraum.bin (FIR,
     open flightmaps) desselben Release, um 300 m nach innen gesetzt. Je 30″-Zelle (wie die Geländekacheln) ein Bit:
     1 = Zelle ganz im Umriss, die Hindernisse dort sind vollständig. Eine MSA, deren Korridor eine Zelle ohne Bit
     berührt, meldet die App als „ohne Hindernisdaten“.
  4. Datei FCYH schreiben (fcy_daten/format.py): je 1°-Kachel ein gzip-JSON. Gleiche Eingabe → gleiche Datei.

Die Regel der MSA steht in der App (Build 25s, Georgi 15.11.2026: wie die Übungskarte der Theorie):
  MEF = höchste Erhebung im Korridor (Gelände + 300 ft oder Hindernis, je höher) + 100 ft, aufgerundet auf volle 100 ft.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

from . import format as F
from . import netz

DFS = "https://aip.dfs.de/datasets/"
UEBERSICHT = DFS + "scripts/getAmdtData.php?amdt={n}"
DATEI = DFS + "scripts/getItem.php?amdt={n}&content={name}"
LUFTRAUM = "https://github.com/flycademy/flightlog-daten/releases/download/daten/luftraum.bin"
NAME = re.compile(r"content=(ED_Obstacles_Area_1_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_[a-z]+\.xml)")
AIRAC = re.compile(r"AIRAC\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})")
MONATE = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
NS_A = "{http://www.aixm.aero/schema/5.1.1}"
NS_G = "{http://www.opengis.net/gml/3.2}"
N = 120                     # Zellen je 1° (30″), wie gelaende.bin
INNEN_GRAD = 0.003          # Umriss um rund 300 m nach innen (luftraum.bin ist auf 0,002° vereinfacht)
LIZENZ = "CC BY 4.0 (creativecommons.org/licenses/by/4.0), © DFS Deutsche Flugsicherung GmbH; verändert: umgewandelt, zwei Zyklen vereinigt"


def _ft(el) -> float | None:
    if el is None or not (el.text or "").strip():
        return None
    v = float(el.text)
    u = (el.get("uom") or "FT").upper()
    return v / 0.3048 if u == "M" else v


def lies_xml(daten: bytes) -> list[dict]:
    """AIXM-Datei → Hindernisteile [{lat, lon, msl, agl, typ, licht}] (msl, agl in ft)."""
    out = []
    for _, el in ET.iterparse(io.BytesIO(daten), events=("end",)):
        if el.tag != NS_A + "VerticalStructure":
            continue
        for ts in el.iter(NS_A + "VerticalStructureTimeSlice"):
            styp = (ts.findtext(NS_A + "type") or "").strip()
            licht = (ts.findtext(NS_A + "lighted") or "").strip().upper() == "YES"
            for p in ts.iter(NS_A + "VerticalStructurePart"):
                pos = p.find(".//" + NS_G + "pos")
                msl = _ft(p.find(".//" + NS_A + "elevation"))
                if pos is None or msl is None:
                    continue
                la, lo = (float(x) for x in pos.text.split()[:2])
                out.append({"lat": la, "lon": lo, "msl": msl, "agl": _ft(p.find(NS_A + "verticalExtent")),
                            "typ": ((p.findtext(NS_A + "type") or "").strip() or styp or "OTHER"), "licht": licht})
        el.clear()
    return out


def vereinige(listen: list[list[dict]]) -> list[dict]:
    """Gleiche Lage (1e-6°) → ein Hindernis mit der größten Höhe."""
    m: dict[tuple[int, int], dict] = {}
    for L in listen:
        for h in L:
            k = (round(h["lat"] * 1e6), round(h["lon"] * 1e6))
            if k not in m or h["msl"] > m[k]["msl"]:
                m[k] = h
    return [m[k] for k in sorted(m)]


def uebersicht(n: int) -> dict | None:
    """Zyklus n (0 = laufend, 1 = nächster): {name, ab, bis, airac} oder None."""
    html = netz.hole(UEBERSICHT.format(n=n), timeout=60).decode("utf-8", "replace")
    a = AIRAC.search(html)
    t = NAME.search(html)
    if not a or not t:
        return None
    airac = f"{int(a.group(3)):04d}-{MONATE[a.group(2)]:02d}-{int(a.group(1)):02d}"
    return {"n": n, "name": t.group(1), "airac": airac, "datei_ab": t.group(2), "datei_bis": t.group(3)}


def umriss_laden(pfad: str | None):
    """Umriss Deutschlands (FIR) aus luftraum.bin → shapely-Fläche, um INNEN_GRAD nach innen gesetzt."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    d = open(pfad, "rb").read() if pfad else netz.hole(LUFTRAUM, timeout=120)
    j = F.lese_luftraum(d)
    P = [Polygon(F.umriss_aus(p)).buffer(0) for p in j.get("de") or []]
    if not P:
        raise SystemExit("luftraum.bin ohne Umriss Deutschlands")
    u = unary_union(P).buffer(-INNEN_GRAD, join_style=2)
    return u, F.kopf_lesen(d, b"FCYL").get("lauf", "")


def abdeckung(umriss) -> dict[tuple[int, int], bytes | str]:
    """{(lat, lon): "voll" | Bitfeld N×N (Zeile 0 = Nord, Bit i = Zelle i, LSB zuerst)} für jede Kachel, die der Umriss berührt."""
    import numpy as np
    import shapely
    from shapely.geometry import box
    shapely.prepare(umriss)
    x0, y0, x1, y1 = umriss.bounds
    out = {}
    for la in range(math.floor(y0), math.floor(y1) + 1):
        for lo in range(math.floor(x0), math.floor(x1) + 1):
            K = box(lo, la, lo + 1, la + 1)
            if not umriss.intersects(K):
                continue
            if umriss.contains(K):
                out[(la, lo)] = "voll"
                continue
            r, c = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
            s = (la + 1 - (r + 1) / N).ravel(), (lo + c / N).ravel()
            zellen = shapely.box(s[1], s[0], s[1] + 1 / N, s[0] + 1 / N)
            bits = shapely.contains(umriss, zellen)
            out[(la, lo)] = np.packbits(bits.astype(np.uint8), bitorder="little").tobytes()
    return out


def kacheln(hindernisse: list[dict], abd: dict, zyklen: list[str]) -> dict[tuple[int, int], dict]:
    """Inhalt je Kachel: {z: Zyklen, a: voll|teil|keine, m: Bitfeld (base64, nur teil), h: [[lat·1e5, lon·1e5, msl, agl, typ, licht]]}"""
    K: dict[tuple[int, int], dict] = {}
    for k, a in abd.items():
        K[k] = {"z": zyklen, "a": "voll", "h": []} if a == "voll" else {"z": zyklen, "a": "teil", "m": base64.b64encode(a).decode("ascii"), "h": []}
    for h in hindernisse:
        k = (math.floor(h["lat"]), math.floor(h["lon"]))
        if k not in K:
            K[k] = {"z": zyklen, "a": "keine", "h": []}
        K[k]["h"].append([round(h["lat"] * 1e5), round(h["lon"] * 1e5), math.ceil(h["msl"] - 1e-6),
                          None if h["agl"] is None else round(h["agl"]), h["typ"], 1 if h["licht"] else 0])
    for v in K.values():
        v["h"].sort(key=lambda x: (-x[2], x[0], x[1]))
    return K


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--xml", action="append", help="AIXM-Datei(en) von Platte statt von der DFS (Tests): name=pfad")
    ap.add_argument("--umriss", help="luftraum.bin von Platte statt aus dem Release")
    ap.add_argument("--quelle", help="andere Adresse der DFS-Übersicht (Tests)")
    a = ap.parse_args(argv)
    global UEBERSICHT, DATEI
    if a.quelle:
        q = a.quelle.rstrip("/") + "/"
        UEBERSICHT, DATEI = q + "scripts/getAmdtData.php?amdt={n}", q + "scripts/getItem.php?amdt={n}&content={name}"
    zyklen, listen, roh_sha = [], [], []
    if a.xml:
        for x in a.xml:
            name, pfad = x.split("=", 1)
            d = open(pfad, "rb").read()
            m = NAME.search("content=" + name)
            zyklen.append({"airac": m.group(3) if m else name, "name": name, "sha256": hashlib.sha256(d).hexdigest()})
            listen.append(lies_xml(d))
    else:
        for n in (0, 1):
            u = uebersicht(n)
            if u is None:
                if n == 0:
                    raise SystemExit("DFS: laufender Zyklus ohne Datensatz „ED Obstacles Area 1“")
                print("nächster Zyklus: noch kein Datensatz", flush=True)
                continue
            d = netz.hole(DATEI.format(n=n, name=u["name"]), timeout=300)
            if not d.lstrip().startswith(b"<?xml"):
                raise SystemExit(f"DFS: {u['name']} ist keine XML-Datei")
            L = lies_xml(d)
            print(f"geladen: {u['name']} (AIRAC {u['airac']}, {len(d) // 1024 // 1024} MB, {len(L)} Hindernisteile)", flush=True)
            zyklen.append({"airac": u["airac"], "name": u["name"], "sha256": hashlib.sha256(d).hexdigest()})
            listen.append(L)
    H = vereinige(listen)
    umriss, lr_lauf = umriss_laden(a.umriss)
    abd = abdeckung(umriss)
    zy = [z["airac"] for z in zyklen]
    K = kacheln(H, abd, zy)
    lauf = "+".join(zy) + "@" + hashlib.sha256(("|".join(z["sha256"] for z in zyklen) + "|" + lr_lauf).encode()).hexdigest()[:12]
    kopf = {"quelle": "DFS Deutsche Flugsicherung GmbH, ED Obstacles Area 1 (aip.dfs.de/datasets)", "lizenz": LIZENZ,
            "zyklen": zyklen, "umriss": f"FIR Deutschland aus luftraum.bin ({lr_lauf}), {INNEN_GRAD}° nach innen",
            "erzeugt": zy[-1], "lauf": lauf}
    k = F.schreibe_hindernisse(a.aus, kopf, K)
    print(f"geschrieben: {a.aus} · {k['anzahl']} Hindernisteile in {k['kacheln']} Kacheln "
          f"({sum(1 for v in K.values() if v['a'] == 'voll')} ganz, {sum(1 for v in K.values() if v['a'] == 'teil')} teils in Deutschland), "
          f"{os.path.getsize(a.aus) // 1024} kB, Zyklen {', '.join(zy)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
