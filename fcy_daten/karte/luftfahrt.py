"""Luftfahrtdaten der ICAO-Optik je AIRAC-Zyklus: Lufträume, Funkfeuer, Hindernisse ab 100 m (DFS, CC BY 4.0) und
VFR-Pflichtmeldepunkte (open flightmaps, aus luftraum.bin), alles in Web-Mercator.

Ausgabe: luftfahrt_<Zyklus>.pkl im Arbeitsordner mit {zyklus, ab, bis, luftraeume, funkfeuer, hindernisse, meldepunkte, quellen}.
Die Lufträume tragen die Merkmale wie in den Kartendaten der Übungskarte (typ, lokal, klasse, kennung, name, unten, oben, zeit).
Aufruf: python -m fcy_daten.karte.luftfahrt --arbeit <Ordner> --luftraum <luftraum.bin> [--n 0|1]
        [--xml Airspace=… --xml Navaids=… --xml Obstacles=…]   (Dateien von Platte statt von der DFS, für Tests)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pickle
import re
import xml.etree.ElementTree as ET

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon

from .. import format as F
from .. import hindernisse as H
from .. import luftraum_dfs as LD
from .. import netz

L2M = Transformer.from_crs(4326, 3857, always_xy=True)
ZEITEN = ("H24", "HX", "HJ", "HN", "HO", "TIMSH")
NS = {"aixm": "http://www.aixm.aero/schema/5.1.1", "gml": "http://www.opengis.net/gml/3.2"}


def _m(lonlat):
    a = np.asarray(lonlat, dtype=float)
    x, y = L2M.transform(a[:, 0], a[:, 1])
    return np.column_stack([x, y])


def _grenze(g):
    """(Wert, Einheit, Bezug) der DFS → {wert, einheit, bezug} wie in den Kartendaten der Übungskarte"""
    if g is None:
        return None
    w, u, b = g
    if w.upper() in ("GND", "SFC"):
        return {"wert": "0", "einheit": "FT", "bezug": "SFC"}
    if w.upper() == "UNL":
        return {"wert": "999", "einheit": "FL", "bezug": "STD"}
    return {"wert": w, "einheit": (u or "FT").upper(), "bezug": (b or "MSL").upper()}


def luftraeume(raum: dict) -> list[dict]:
    out = []
    for uid, e in raum.items():
        if e["typ"] == "PART":
            continue
        quellen = [(v["p"], v["u"], v["o"]) for v in e["vol"]]
        for t in e["teile"]:
            q = raum.get(t["ref"])
            if not q or q["typ"] != "PART" or t["op"] not in ("BASE", "UNION"):
                continue
            for v in q["vol"]:
                quellen.append((v["p"], t["u"] or v["u"], t["o"] or v["o"]))
        zeit = next((x[2].strip() for x in e["notes"] if x[2].strip() in ZEITEN), None)
        for pts, u, o in quellen:
            try:
                poly = Polygon(_m(pts)).buffer(0)
            except Exception:
                continue
            if poly.is_empty:
                continue
            p = {"typ": e["typ"], "lokal": e["lokal"], "klasse": e["klasse"], "kennung": e["kennung"], "name": e["name"],
                 "unten": _grenze(u), "oben": _grenze(o)}
            if zeit:
                p["zeit"] = zeit
            out.append((poly, {k: v for k, v in p.items() if v}))
    return out


def funkfeuer(daten: bytes) -> list[dict]:
    """ED Navaids → [{x, y, lon, lat, art, kennung, name, frequenz}] wie aixm2.py der Theorie (VOR, DME, NDB)."""
    A = lambda t: "{%s}%s" % (NS["aixm"], t)
    out = []
    for _, el in ET.iterparse(__import__("io").BytesIO(daten), events=("end",)):
        if el.tag not in (A("VOR"), A("DME"), A("NDB")):
            continue
        for ts in el:
            for t in ts:
                pos = t.find(".//gml:pos", NS)
                if pos is None:
                    continue
                lat, lon = [float(v) for v in pos.text.split()[:2]]
                g = lambda k: (t.findtext("aixm:" + k, namespaces=NS) or "").strip()
                x, y = L2M.transform(lon, lat)
                out.append({"x": x, "y": y, "lon": lon, "lat": lat, "art": el.tag.split("}")[1], "kennung": g("designator"),
                            "name": g("name"), "frequenz": g("frequency")})
        el.clear()
    return out


def hindernisse(daten: bytes) -> list[dict]:
    """ED Obstacles Area 1 → Hindernisse ab 100 m über Grund [{x, y, typ, befeuert, hoehe_msl_ft, hoehe_agl_ft}]."""
    out = []
    for h in H.lies_xml(daten):
        if h["agl"] is None or h["agl"] < 100 / 0.3048 - 0.5:
            continue
        x, y = L2M.transform(h["lon"], h["lat"])
        out.append({"x": x, "y": y, "typ": h["typ"], "befeuert": "YES" if h["licht"] else "NO",
                    "hoehe_msl_ft": int(round(h["msl"])) if h["msl"] is not None else 0, "hoehe_agl_ft": int(round(h["agl"]))})
    return out


def meldepunkte(lr_bin: bytes, zyklus: str) -> tuple[list[dict], dict]:
    """VFR-Pflichtmeldepunkte (VFR-MRP) aus open flightmaps im Zyklus, wie im Flight Log."""
    k = F.kopf_lesen(lr_bin, b"FCYL")
    z = next((x for x in k["zyklen"] if x["zyklus"] == zyklus), None) or k["zyklen"][0]
    d = F.lese_luftraum(lr_bin, z["zyklus"])
    out = []
    for kenn, name, typ, lat, lon, ad in d["dp"]:
        if typ != "VFR-MRP":
            continue
        x, y = L2M.transform(lon, lat)
        out.append({"x": x, "y": y, "name": kenn, "langname": name, "platz": ad})
    return out, {"zyklus": d["zyklus"], "stand": d.get("stand", "")}


def _uebersicht(n: int) -> str:
    return netz.hole(LD.UEBERSICHT.format(n=n), timeout=60).decode("utf-8", "replace")


def _datei(html: str, art: str):
    m = re.search(r"content=(ED_%s_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_[a-z]+\.xml)" % art, html)
    return m.group(1) if m else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arbeit", required=True); ap.add_argument("--luftraum", required=True)
    ap.add_argument("--n", type=int, default=0); ap.add_argument("--xml", action="append", default=[])
    ap.add_argument("--ab", help="Beginn des AIRAC-Zyklus (JJJJ-MM-TT), nur mit --xml")
    a = ap.parse_args(argv)
    vorgabe = dict(x.split("=", 1) for x in a.xml)
    quellen = {}
    if vorgabe:
        daten = {k: open(v, "rb").read() for k, v in vorgabe.items()}
        quellen = {k: os.path.basename(v) for k, v in vorgabe.items()}
        airac = LD.NAME.search("content=" + quellen.get("Airspace", "")) if "Airspace" in quellen else None
        ab = a.ab or (airac.group(3) if airac else None)
    else:
        html = _uebersicht(a.n)
        u = LD.lies_uebersicht(html, a.n)
        if not u:
            raise SystemExit(f"DFS: Zyklus {a.n} ohne Luftraum-Datensatz")
        ab = u["airac"]
        daten = {}
        for art in ("Airspace", "Navaids"):
            name = _datei(html, "Airspace_StrokedBorders" if art == "Airspace" else art)
            daten[art] = netz.hole(LD.DATEI.format(n=a.n, name=name), timeout=300); quellen[art] = name
        uh = H.uebersicht(a.n)
        if uh:
            daten["Obstacles"] = netz.hole(H.DATEI.format(n=a.n, name=uh["name"]), timeout=300); quellen["Obstacles"] = uh["name"]
    zyklus = LD.zyklus_von(ab) if ab else "?"
    t0 = dt.date.fromisoformat(ab) if ab else None
    raum = LD.lies_aixm(daten["Airspace"])
    L = luftraeume(raum)
    N = funkfeuer(daten["Navaids"])
    Hd = hindernisse(daten["Obstacles"]) if "Obstacles" in daten else []
    M, mz = meldepunkte(open(a.luftraum, "rb").read(), zyklus)
    out = {"zyklus": zyklus, "ab": ab, "bis": (t0 + dt.timedelta(days=28)).isoformat() if t0 else None, "luftraeume": L,
           "funkfeuer": N, "hindernisse": Hd, "meldepunkte": M, "quellen": quellen, "meldepunkte_stand": mz}
    with open(os.path.join(a.arbeit, f"luftfahrt_{zyklus}.pkl"), "wb") as f:
        pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    from collections import Counter
    print(f"Zyklus {zyklus} ab {ab}: {len(L)} Lufträume ({dict(Counter(p['typ'] for _, p in L).most_common(8))}), {len(N)} Funkfeuer, "
          f"{len(Hd)} Hindernisse ab 100 m, {len(M)} Pflichtmeldepunkte (open flightmaps {mz['zyklus']})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
