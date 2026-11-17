"""Grunddaten der ICAO-Optik für ganz Deutschland (unabhängig vom AIRAC-Zyklus).

  topo.pkl     Ebenen aus dem BKG DLM250 (Wald, Ortslagen, Gewässer, Straßen, Bahn, Bahnhöfe, Pisten) und der Umriss
               Deutschlands (AX_Gebiet_Nationalstaat), alles in Web-Mercator (EPSG:3857, Meter)
  plaetze.json Flugplätze: Lage, Kennung, Name und Art aus dem BKG DLM250; Höhe aus der Platzliste des Flight Log
               (dieselbe Zahl, mit der der Flight Log rechnet), sonst OurAirports; Pisten und Frequenz aus open flightmaps
               (falls übergeben), sonst OurAirports
  dgm200.npz   Geländehöhen 200 m (BKG DGM200) für Höhenpunkte und MEF, wie auf der Übungskarte

Quellen: © GeoBasis-DE / BKG (2026) dl-de/by-2-0 (Daten verändert); OurAirports (gemeinfrei); open flightmaps (OFMA GUL).
Aufruf: python -m fcy_daten.karte.daten --dlm <dlm250_ebenen> --dgm <dgm200_utm32s.tif> --oa <Ordner OurAirports>
        --hoehen <platzhoehen.json> [--ofm-ad <ofm_plaetze.json>] --aus <Arbeitsordner>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import pickle
import re

import numpy as np
import pyogrio
import shapely
from pyproj import Transformer
from shapely.ops import linemerge, unary_union

U2M = Transformer.from_crs(25832, 3857, always_xy=True)
L2M = Transformer.from_crs(4326, 3857, always_xy=True)
M2L = Transformer.from_crs(3857, 4326, always_xy=True)

ART = {"5511": "Internationaler Flughafen", "5512": "Regionalflughafen", "5513": "Regionalflughafen", "5521": "Verkehrslandeplatz",
       "5522": "Sonderlandeplatz", "5530": "Hubschrauberflugplatz", "5550": "Segelfluggelände", "5560": "Sonderlandeplatz"}
RANG = ["Internationaler Flughafen", "Regionalflughafen", "Verkehrslandeplatz", "Sonderlandeplatz", "Segelfluggelände", "Hubschrauberflugplatz"]
KLINIK_ORT = {"ED2263", "ED2298", "ED2054", "ED2003"}   # wie Übungskarte: Hubschrauberplätze mitten im Ort, sehr wahrscheinlich Krankenhaus
KLINIK = re.compile(r"klinik|krhs|krankenhaus|hochschule|spital|herzzentrum|hospital|clinic|medical|kh\b|uniklinik", re.I)


def _proj(geoms, tr):
    if len(geoms) == 0:
        return geoms
    return shapely.transform(geoms, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))


def _s(v):
    if v is None:
        return ""
    return str(v)


def lies(dlm: str, name: str, felder: list[str]):
    meta, _, geom, fd = pyogrio.raw.read(os.path.join(dlm, name + ".shp"), columns=felder)
    g = _proj(shapely.from_wkb(geom), U2M)
    namen = list(meta["fields"])                         # Reihenfolge wie in der Datei, nicht wie angefragt
    props = [{f: _s(fd[namen.index(f)][k]) for f in felder} for k in range(len(g))]
    return g, props


def _teile(g, art):
    out = []
    for q in getattr(g, "geoms", [g]):
        if q.geom_type == art and not q.is_empty:
            out.append(q)
    return out


def topo(dlm: str) -> dict:
    T = {}
    g, p = lies(dlm, "veg02_f", ["OBJART_TXT"])
    T["wald"] = [q for x in g for q in _teile(x, "Polygon")]
    g, p = lies(dlm, "sie01_f", ["NAM"])
    T["orte"] = [(q, pp["NAM"]) for x, pp in zip(g, p) for q in _teile(x, "Polygon")]
    g, p = lies(dlm, "gew01_f", ["NAM"])
    T["wasser"] = [q for x in g for q in _teile(x, "Polygon")]
    g, p = lies(dlm, "gew01_l", ["WDM", "NAM"])
    T["fluesse"] = [(q, pp["WDM"], pp["NAM"]) for x, pp in zip(g, p) if pp["WDM"] in ("1310", "1320") for q in _teile(x, "LineString")]
    g, p = lies(dlm, "ver01_l", ["WDM", "BEZ"])
    T["strassen"] = [(q, pp["WDM"], pp["BEZ"].split("#")[-1]) for x, pp in zip(g, p) if pp["WDM"] in ("1301", "1303", "1305")
                     for q in _teile(x, "LineString")]
    g, p = lies(dlm, "sie01_p", ["NAM"])
    T["doerfer"] = [(x, pp["NAM"]) for x, pp in zip(g, p) if x.geom_type == "Point"]
    g, p = lies(dlm, "ver03_l", ["OBJART_TXT", "ZUS", "GLS"])
    klassen = {"ein": [], "mehr": [], "still": []}
    for x, pp in zip(g, p):
        if pp["OBJART_TXT"] != "AX_Bahnstrecke":
            continue
        k = "still" if pp["ZUS"] == "2100" else "mehr" if pp["GLS"] == "2000" else "ein"
        klassen[k] += _teile(x, "LineString")
    for k, v in klassen.items():
        m = linemerge(v) if v else None
        T["bahn_" + k] = [q for q in getattr(m, "geoms", [m]) if q is not None and q.length > 0] if m is not None else []
    g, p = lies(dlm, "ver06_p", ["OBJART_TXT", "BFK", "ZUS"])
    T["bahnhoefe"] = [x for x, pp in zip(g, p) if pp["OBJART_TXT"] == "AX_Bahnverkehrsanlage" and pp["BFK"] == "1010" and not pp["ZUS"]]
    g, p = lies(dlm, "ver06_l", ["OBJART_TXT", "ART"])
    T["pisten"] = [q for x, pp in zip(g, p) if pp["OBJART_TXT"] == "AX_Flugverkehrsanlage" and pp["ART"] == "1310"
                   for q in _teile(x, "LineString")]
    g, p = lies(dlm, "geb01_f", ["OBJART_TXT"])
    de = unary_union([x for x, pp in zip(g, p) if pp["OBJART_TXT"] == "AX_Gebiet_Nationalstaat"]).buffer(0)
    T["de"] = de
    return T


def _oa(oa_dir: str):
    rd = lambda n: list(csv.DictReader(open(os.path.join(oa_dir, n), encoding="utf-8")))
    ap = [a for a in rd("airports.csv") if a["iso_country"] == "DE" and a["latitude_deg"]]
    rw, fq = {}, {}
    for r in rd("runways.csv"):
        rw.setdefault(r["airport_ref"], []).append(r)
    for r in rd("airport-frequencies.csv"):
        fq.setdefault(r["airport_ref"], []).append(r)
    return ap, rw, fq


FQ_RANG = ["TWR", "INFO", "A/G", "AFIS", "UNIC", "CTAF", "RDO", "MULTICOM"]


def _oa_frequenz(liste) -> str:
    best = None
    for r in liste or []:
        t = (r.get("type") or "").upper(); d = (r.get("description") or "").lower()
        if t not in FQ_RANG or not r.get("frequency_mhz"):
            continue
        if t == "AFIS" and re.search(r"langen|bremen|münchen|munchen|information", d):
            continue                                   # FIS, nicht der Platz
        k = FQ_RANG.index(t)
        if best is None or k < best[0]:
            best = (k, r["frequency_mhz"])
    if not best:
        return ""
    f = float(best[1])
    return f"{f:.3f}"


def plaetze(dlm: str, oa_dir: str, hoehen: dict, ofm_ad: dict | None = None) -> list[dict]:
    bkg = []
    g, p = lies(dlm, "ver04_f", ["ART", "BEZ", "NAM", "NTZ", "ZUS"])
    for x, pp in zip(g, p):
        if pp["ART"] in ART and pp["ZUS"] != "2100":
            bkg.append((x.representative_point(), pp, "Fläche"))
    g, p = lies(dlm, "ver06_p", ["OBJART_TXT", "ART", "BEZ", "NAM", "ZUS"])
    for x, pp in zip(g, p):
        if pp["OBJART_TXT"] == "AX_Flugverkehrsanlage" and pp["ART"] in ART and pp["ZUS"] != "2100":
            bkg.append((x, pp, "Punkt"))
    ap, rw, fq = _oa(oa_dir)
    oa_pt = [(a, L2M.transform(float(a["longitude_deg"]), float(a["latitude_deg"]))) for a in ap]
    gesehen, out = set(), []
    for pt, pp, form in bkg:
        code = pp["BEZ"]; art = ART[pp["ART"]]
        if code and code in gesehen:
            continue
        heli = art == "Hubschrauberflugplatz"
        kand = [a for a, _ in oa_pt if code and code in (a["ident"], a["gps_code"], a.get("icao_code", ""), a["local_code"])]
        if heli:
            kand = [a for a in kand if a["type"] == "heliport"]
        if not kand:
            nah = sorted(((math.hypot(xy[0] - pt.x, xy[1] - pt.y) * math.cos(math.radians(51)), a) for a, xy in oa_pt
                          if (a["type"] == "heliport") == heli), key=lambda t: t[0])[:1]
            kand = [a for d, a in nah if d < 600]
        oa = kand[0] if kand else None
        if oa and oa["type"] == "closed":
            continue
        name = pp["NAM"] or (oa or {}).get("name") or ""
        if heli and (KLINIK.search(name) or (oa and KLINIK.search(oa["name"] or "")) or code in KLINIK_ORT):
            continue                                   # Krankenhaus-Landeplätze nicht (wie Übungskarte)
        lon, lat = M2L.transform(pt.x, pt.y)
        q = {"kennung": code, "name": name, "art": art, "x": pt.x, "y": pt.y, "lon": round(lon, 5), "lat": round(lat, 5),
             "mil": code.startswith("ET") or pp.get("NTZ") == "3000", "hoehe_ft": None, "mhz": "", "pisten": [], "quelle_hoehe": ""}
        if code in hoehen:
            q["hoehe_ft"] = int(hoehen[code]); q["quelle_hoehe"] = "Flight Log"
        elif oa and oa["elevation_ft"]:
            q["hoehe_ft"] = int(round(float(oa["elevation_ft"]))); q["quelle_hoehe"] = "OurAirports"
        o = (ofm_ad or {}).get(code)
        if o:
            q["mhz"] = o.get("mhz") or ""
            q["pisten"] = o.get("pisten") or []
        if oa and not q["mhz"]:
            q["mhz"] = _oa_frequenz(fq.get(oa["id"]))
        if oa and not q["pisten"]:
            for r in rw.get(oa["id"], []):
                if r["closed"] == "1" or not r["length_ft"]:
                    continue
                q["pisten"].append({"laenge_m": int(round(float(r["length_ft"]) * 0.3048 / 5) * 5),
                                    "fest": (r["surface"] or "").upper()[:3] in ("ASP", "CON", "PEM", "BIT", "CEM"),
                                    "kurs_rw": float(r["le_heading_degT"]) if r["le_heading_degT"] else None})
        if code:
            gesehen.add(code)
        out.append(q)
    mitk = [(q["x"], q["y"]) for q in out if q["kennung"]]
    out = [q for q in out if q["kennung"] or not any(math.hypot(q["x"] - a, q["y"] - b) < 1600 for a, b in mitk)]
    out.sort(key=lambda q: (RANG.index(q["art"]), q["kennung"] or "~", q["name"]))
    return out


def dgm(pfad: str) -> dict:
    import rasterio
    with rasterio.open(pfad) as r:
        a = r.read(1).astype(np.float32); t = r.transform
        a[a == r.nodata] = np.nan
    return {"hoehe_m": a, "x0": t.c, "y0": t.f, "pix": t.a}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dlm", required=True); ap.add_argument("--dgm", required=True); ap.add_argument("--oa", required=True)
    ap.add_argument("--hoehen", required=True); ap.add_argument("--ofm-ad"); ap.add_argument("--aus", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.aus, exist_ok=True)
    T = topo(a.dlm)
    with open(os.path.join(a.aus, "topo.pkl"), "wb") as f:
        pickle.dump(T, f, protocol=pickle.HIGHEST_PROTOCOL)
    print("Topografie:", {k: (len(v) if isinstance(v, list) else v.geom_type) for k, v in T.items()}, flush=True)
    h = json.load(open(a.hoehen, encoding="utf-8"))
    h = h.get("hoehen", h)
    ofm = json.load(open(a.ofm_ad, encoding="utf-8")) if a.ofm_ad else None
    P = plaetze(a.dlm, a.oa, h, ofm)
    json.dump(P, open(os.path.join(a.aus, "plaetze.json"), "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print("Flugplätze:", len(P), dict(Counter(q["art"] for q in P)), "Höhe aus", dict(Counter(q["quelle_hoehe"] for q in P)), flush=True)
    d = dgm(a.dgm)
    np.savez_compressed(os.path.join(a.aus, "dgm200.npz"), hoehe_m=d["hoehe_m"], meta=np.array([d["x0"], d["y0"], d["pix"]]))
    print("DGM200:", d["hoehe_m"].shape, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
