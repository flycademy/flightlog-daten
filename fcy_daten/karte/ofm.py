"""Flugplätze aus open flightmaps (OFMX) für die ICAO-Optik: Frequenz des Platzes (TWR, sonst INFO/RADIO, sonst andere)
und Pisten (Länge, Belag, rechtweisende Richtung). Lizenz: OFMA General Users' License (openflightmaps.org/about).

Aufruf: python -m fcy_daten.karte.ofm --zyklus 2611 --aus <ofm_plaetze.json> [--roh <OFMX-Datei speichern>] [--ofmx <OFMX von Platte>]
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET

from .. import luftraum as LR
from .. import netz

RANG = ["TWR", "AFIS", "INFO", "RADIO", "A/G", "UNICOM", "CTAF", "APP"]


def holen(zyklus: str, region: str = "ed") -> bytes:
    xml = netz.hole(f"{LR.QUELLE}/publicationServices/{region.upper()}_{zyklus}.xml", ok404=True)
    if not xml:
        raise SystemExit(f"open flightmaps: kein Zyklus {zyklus}")
    u = LR.lies_uebersicht(xml, zyklus)
    ofmx, _ = LR.aus_zip(netz.hole(u["ofmx"], timeout=180), region)
    return ofmx


def _t(el, pfad):
    x = el.find(pfad) if el is not None else None
    return (x.text or "").strip() if x is not None and x.text else ""


def lies(ofmx: bytes) -> dict:
    """→ {ICAO: {mhz, ruf, pisten: [{laenge_m, fest, kurs_rw}]}}"""
    root = ET.fromstring(ofmx)
    uni_ahp = {}                                   # Dienststelle (Unit) → Platz
    for u in root.iter("Uni"):
        uid = u.find("UniUid")
        ahp = _t(u, "AhpUid/codeId")
        if uid is not None and ahp:
            uni_ahp[_t(uid, "txtName")] = ahp
    ser_ahp = {}
    for s in root.iter("Ser"):
        uid = s.find("SerUid")
        if uid is None:
            continue
        uni = _t(uid, "UniUid/txtName")
        key = (uni, _t(uid, "codeType"), _t(uid, "noSeq"))
        if uni in uni_ahp:
            ser_ahp[key] = (uni_ahp[uni], _t(uid, "codeType"))
    out = {}
    for f in root.iter("Fqy"):
        uid = f.find("FqyUid")
        su = uid.find("SerUid") if uid is not None else None
        if su is None:
            continue
        key = (_t(su, "UniUid/txtName"), _t(su, "codeType"), _t(su, "noSeq"))
        if key not in ser_ahp:
            continue
        ahp, typ = ser_ahp[key]
        mhz = _t(uid, "valFreqTrans") or _t(f, "valFreqTrans")
        if not mhz:
            continue
        ruf = _t(f, "Cdl/txtCallSign") or ""
        r = RANG.index(typ) if typ in RANG else len(RANG)
        e = out.setdefault(ahp, {"pisten": []})
        if "rang" not in e or r < e["rang"]:
            try:
                e.update({"mhz": f"{float(mhz):.3f}", "ruf": ruf, "art": typ, "rang": r})
            except ValueError:
                pass
    rwy = {}
    for r in root.iter("Rwy"):
        uid = r.find("RwyUid")
        ahp = _t(uid, "AhpUid/codeId") if uid is not None else ""
        if not ahp:
            continue
        try:
            ln = float(_t(r, "valLen") or 0)
        except ValueError:
            ln = 0
        uom = _t(r, "uomDimRwy").upper()
        if uom == "FT":
            ln *= 0.3048
        comp = _t(r, "codeComposition").upper()
        rwy[(ahp, _t(uid, "txtDesig"))] = {"laenge_m": int(round(ln / 5) * 5), "fest": comp[:3] in ("ASP", "CON", "PEM", "BIT", "CEM", "ASPH"),
                                           "kurs_rw": None}
    for d in root.iter("Rdn"):
        uid = d.find("RdnUid")
        ru = uid.find("RwyUid") if uid is not None else None
        if ru is None:
            continue
        k = (_t(ru, "AhpUid/codeId"), _t(ru, "txtDesig"))
        if k in rwy and rwy[k]["kurs_rw"] is None:
            try:
                rwy[k]["kurs_rw"] = float(_t(d, "valTrueBrg"))
            except ValueError:
                pass
    for (ahp, _), v in rwy.items():
        if v["laenge_m"] > 0:
            out.setdefault(ahp, {"pisten": []})["pisten"].append(v)
    for e in out.values():
        e.pop("rang", None)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zyklus", required=True); ap.add_argument("--aus", required=True)
    ap.add_argument("--roh"); ap.add_argument("--ofmx")
    a = ap.parse_args(argv)
    d = open(a.ofmx, "rb").read() if a.ofmx else holen(a.zyklus)
    if a.roh:
        open(a.roh, "wb").write(d)
    P = lies(d)
    json.dump(P, open(a.aus, "w", encoding="utf-8"), ensure_ascii=False)
    mit = sum(1 for e in P.values() if e.get("mhz"))
    print(f"open flightmaps {a.zyklus}: {len(P)} Plätze, davon {mit} mit Frequenz, {sum(len(e['pisten']) for e in P.values())} Pisten; "
          f"EDVE: {P.get('EDVE')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
