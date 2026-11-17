"""Lufträume Deutschlands aus dem DFS-Datensatz „ED Airspace“ (AIXM 5.1, CC BY 4.0), je AIRAC-Zyklus.

Georgi 15.11.2026 (Nr. 5): Der Datenjob „Luftraum“ nimmt die Lufträume aus dem DFS-Datensatz statt aus open flightmaps.
Flugplätze, VFR-Meldepunkte und der Umriss Deutschlands bleiben aus open flightmaps (Nr. 8: „open flightmaps bleibt“).

Ablauf (aufgerufen aus fcy_daten.luftraum):
  1. Die Übersichtsseiten der DFS (aip.dfs.de/datasets, scripts/getAmdtData.php?amdt=0 und 1, wie beim Job „Hindernisse“)
     nennen den Datensatz ED_Airspace_StrokedBorders des laufenden und des nächsten Zyklus. „StrokedBorders“: Grenzen
     als Linienzüge ausgeschrieben, ohne Verweise auf gemeinsame Grenzen.
  2. Je Luftraum (AirspaceTimeSlice) Art, örtliche Art, Kennung, Name, Klasse, Unter-/Obergrenze, Zeitplan (Timesheets),
     Bemerkungen. Umrisse: Linienzüge, Bögen und Kreise (gml:ArcByCenterPoint, CircleByCenterPoint) auf dem WGS84-
     Ellipsoid aufgelöst (pyproj). Zusammengesetzte Lufträume (contributorAirspace, nur BASE/UNION) bekommen je Teil
     (Art PART) einen eigenen Eintrag mit den Grenzen des Teils; Verweise auf eigenständige Lufträume (z. B. Sektoren
     einer CTR) erscheinen über diese selbst.
  3. Arten wie bisher in der App (open flightmaps):
       CTR, CTR_P → CTR          CLASS C/D (regional) → TMA      CLASS sonst → CLASS (landesweit: Name „AREA“/„ALPINE AREA“)
       RAS TMZ/RMZ/ATZ → TMZ/RMZ/ATZ                             R, OTHER:R_AMC → R           OTHER:D_AMC → D
       A PJA → HPGLDR (Fallschirmsprung)   A GLD → GLDR (Segelflug)   PROTECT „MIL LOW FLYING AREA“ → LFA
     neu: A ACR → ACR (Kunstflug)   A UAV → UAV (Flugmodelle/UAS)
     nicht übernommen (für den Sichtflug nicht gebraucht oder ohne Bedeutung für die Karte): Sektoren, CTA/UTA, FIS-
     Sektoren, FRA, NPZ, Gates, DLG-ATS, FBZ (nur Flugplanung), PROTECT außer LFA, D_OTHER, Luftraum G (landesweit).
  4. Was die DFS nicht führt, kommt weiter aus open flightmaps, mit Kennzeichen q = "ofm": Naturschutzgebiete (NRA),
     Segelfluggebiete (GLDR, I-GLDR) und Fallschirmsprunggebiete (HPGLDR) ohne Gegenstück im DFS-Datensatz
     (Gegenstück = gleiche Fläche, Überdeckung ≥ 60 %).
  5. Umrisse wie bisher vereinfacht (rund 20 m) und kodiert (fcy_daten.luftraum).

Lizenz: © DFS Deutsche Flugsicherung GmbH, Datensatz ED Airspace, CC BY 4.0 (creativecommons.org/licenses/by/4.0);
verändert: umgewandelt, Umrisse vereinfacht, Arten zusammengefasst. Maßgeblich bleiben ICAO-Karte, AIP, NOTAM und AUP.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import xml.etree.ElementTree as ET

from . import netz

DFS = "https://aip.dfs.de/datasets/"
UEBERSICHT = DFS + "scripts/getAmdtData.php?amdt={n}"
DATEI = DFS + "scripts/getItem.php?amdt={n}&content={name}"
NAME = re.compile(r"content=(ED_Airspace_StrokedBorders_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_[a-z]+\.xml)")
AIRAC = re.compile(r"AIRAC\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})")
MONATE = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
NS = {"aixm": "http://www.aixm.aero/schema/5.1.1", "gml": "http://www.opengis.net/gml/3.2", "xlink": "http://www.w3.org/1999/xlink"}
_A = "{%s}" % NS["aixm"]
_G = "{%s}" % NS["gml"]
_XL = "{%s}href" % NS["xlink"]
LIZENZ = ("© DFS Deutsche Flugsicherung GmbH, Datensatz ED Airspace, CC BY 4.0 (creativecommons.org/licenses/by/4.0); "
          "verändert: umgewandelt, Umrisse vereinfacht, Arten zusammengefasst")
OFM_ERGAENZT = {"NRA", "GLDR", "I-GLDR", "HPGLDR"}     # was die DFS nicht führt, bleibt aus open flightmaps
UEBERDECKUNG = 0.6
LAENDER = re.compile(r"/(BADEN-WUERTTEMBERG|BAYERN|BERLIN|BRANDENBURG|BREMEN|HAMBURG|HESSEN|MECKLENBURG-VORPOMMERN|NIEDERSACHSEN|"
                     r"NORDRHEIN-WES\w*|RHEINLAND-PFALZ|SAARLAND|SACHSEN|SACHSEN-ANHALT|SCHLESWIG-HOLSTEIN|THUERINGEN)\s*$")
TAGE = {"MON": "Mo", "TUE": "Di", "WED": "Mi", "THU": "Do", "FRI": "Fr", "SAT": "Sa", "SUN": "So", "ANY": "täglich",
        "WORK_DAY": "werktags", "BEF_WORK_DAY": "vor Werktagen", "AFT_WORK_DAY": "nach Werktagen", "HOL": "Feiertage",
        "BUSY_FRI": "Fr", "BEF_HOL": "vor Feiertagen", "AFT_HOL": "nach Feiertagen"}
EREIGNIS = {"SR": "SR", "SS": "SS", "BMCT": "BMCT", "EECT": "EECT"}


# ----------------------------------------------------------------------------------------------
# Übersicht der DFS
# ----------------------------------------------------------------------------------------------
def lies_uebersicht(html: str, n: int) -> dict | None:
    """{n, name, airac (JJJJ-MM-TT)} oder None"""
    a = AIRAC.search(html)
    t = NAME.search(html)
    if not a or not t:
        return None
    return {"n": n, "name": t.group(1), "airac": f"{int(a.group(3)):04d}-{MONATE[a.group(2)]:02d}-{int(a.group(1)):02d}"}


def uebersicht(n: int) -> dict | None:
    return lies_uebersicht(netz.hole(UEBERSICHT.format(n=n), timeout=60).decode("utf-8", "replace"), n)


def lade(u: dict) -> bytes:
    return netz.hole(DATEI.format(n=u["n"], name=u["name"]), timeout=300)


# ----------------------------------------------------------------------------------------------
# Geometrie (WGS84)
# ----------------------------------------------------------------------------------------------
_GEOD = None


def _geod():
    global _GEOD
    if _GEOD is None:
        from pyproj import Geod
        _GEOD = Geod(ellps="WGS84")
    return _GEOD


def _ll(txt: str) -> list[tuple[float, float]]:
    """gml:posList (lat lon lat lon …) → [(lon, lat), …]"""
    v = [float(x) for x in txt.split()]
    return [(v[i + 1], v[i]) for i in range(0, len(v) - 1, 2)]


def _radius_m(el) -> float:
    r = float(el.text)
    u = (el.get("uom") or "NM").upper()
    return r * {"NM": 1852.0, "[NMI_I]": 1852.0, "KM": 1000.0, "M": 1.0, "FT": 0.3048}.get(u, 1852.0)


def _bogen(c, r, a0, a1, vorher):
    """Bogen um c mit Radius r von a0 nach a1. AIXM nennt die Winkel mathematisch (gegen den Uhrzeigersinn ab Ost) oder
    als Peilung; genommen wird die Lesart, deren Anfang am vorigen Punkt liegt."""
    G = _geod()
    best = None
    for art in ("peil", "math"):
        s, e = (a0, a1) if art == "peil" else (90 - a0, 90 - a1)
        d = e - s
        n = max(8, int(abs(d) / 3))
        pts = [G.fwd(c[0], c[1], s + d * i / n, r)[:2] for i in range(n + 1)]
        if vorher is None:
            return pts
        abstand = G.inv(vorher[0], vorher[1], pts[0][0], pts[0][1])[2]
        if best is None or abstand < best[0]:
            best = (abstand, pts)
    return best[1]


def _kreis(c, r):
    G = _geod()
    return [G.fwd(c[0], c[1], az, r)[:2] for az in range(0, 361, 4)]


def ring(kurve) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for seg in kurve.iter():
        tag = seg.tag
        if tag in (_G + "GeodesicString", _G + "LineStringSegment"):
            pl = seg.find(_G + "posList")
            pts += _ll(pl.text) if pl is not None else [_ll(x.text)[0] for x in seg.findall(_G + "pos")]
        elif tag == _G + "ArcByCenterPoint":
            pp = seg.find(_G + "pointProperty")
            c = _ll((pp.find(".//" + _G + "pos") if pp is not None else seg.find(_G + "pos")).text)[0]
            pts += _bogen(c, _radius_m(seg.find(_G + "radius")), float(seg.find(_G + "startAngle").text),
                          float(seg.find(_G + "endAngle").text), pts[-1] if pts else None)
        elif tag == _G + "CircleByCenterPoint":
            pts += _kreis(_ll(seg.find(".//" + _G + "pos").text)[0], _radius_m(seg.find(_G + "radius")))
    return pts


# ----------------------------------------------------------------------------------------------
# AIXM lesen
# ----------------------------------------------------------------------------------------------
def _t(el, pfad: str) -> str | None:
    x = el.find(pfad, NS)
    return x.text.strip() if x is not None and x.text is not None and x.text.strip() else None


def _grenze(vol, k: str):
    """(Wert, Einheit, Bezug) der Unter-/Obergrenze eines AirspaceVolume oder None"""
    e = vol.find(f"aixm:{k}Limit", NS)
    if e is None or not (e.text or "").strip():
        return None
    return (e.text.strip(), e.get("uom"), _t(vol, f"aixm:{k}LimitReference"))


def _zeitplaene(ts) -> list[dict]:
    out = []
    for act in ts.findall("aixm:activation/aixm:AirspaceActivation", NS):
        if (_t(act, "aixm:status") or "ACTIVE") not in ("ACTIVE", "INTERMITTENT"):
            continue
        for t in act.findall("aixm:timeInterval/aixm:Timesheet", NS):
            out.append({k: _t(t, "aixm:" + k) for k in ("timeReference", "startDate", "endDate", "day", "dayTil", "startTime",
                                                        "startEvent", "endTime", "endEvent", "daylightSavingAdjust", "excluded")})
    return out


def lies_aixm(daten: bytes) -> dict:
    """AIXM-Datei → {uid: {typ, lokal, kennung, name, klasse, notes, zp, vol, teile}}"""
    raum = {}
    for _, el in ET.iterparse(io.BytesIO(daten), events=("end",)):
        if el.tag != _A + "Airspace":
            continue
        uid = _t(el, "gml:identifier")
        for ts in el.findall(".//aixm:AirspaceTimeSlice", NS):
            e = {"typ": _t(ts, "aixm:type"), "lokal": _t(ts, "aixm:localType"), "kennung": _t(ts, "aixm:designator"),
                 "name": _t(ts, "aixm:name"), "klasse": _t(ts, ".//aixm:AirspaceLayerClass/aixm:classification"),
                 "notes": [], "zp": _zeitplaene(ts), "vol": [], "teile": []}
            for n in ts.findall("aixm:annotation/aixm:Note", NS):
                txt = " ".join((x.text or "").strip() for x in n.findall(".//aixm:LinguisticNote/aixm:note", NS)).strip()
                if txt:
                    e["notes"].append((_t(n, "aixm:propertyName"), _t(n, "aixm:purpose"), txt))
            for gc in ts.findall("aixm:geometryComponent/aixm:AirspaceGeometryComponent", NS):
                op = _t(gc, "aixm:operation") or "BASE"
                vol = gc.find("aixm:theAirspaceVolume/aixm:AirspaceVolume", NS)
                if vol is None:
                    continue
                ex = vol.find(".//gml:PolygonPatch/gml:exterior", NS)
                if ex is not None:
                    p = ring(ex)
                    if len(p) >= 4:
                        e["vol"].append({"p": p, "u": _grenze(vol, "lower"), "o": _grenze(vol, "upper"), "op": op})
                for dep in vol.findall("aixm:contributorAirspace/aixm:AirspaceVolumeDependency", NS):
                    th = dep.find("aixm:theAirspace", NS)
                    if th is not None:
                        e["teile"].append({"ref": th.get(_XL, "").split(":")[-1], "op": op,
                                           "u": _grenze(vol, "lower"), "o": _grenze(vol, "upper")})
            raum[uid] = e
        el.clear()
    return raum


# ----------------------------------------------------------------------------------------------
# Umwandlung in die Einträge der App (wie open flightmaps)
# ----------------------------------------------------------------------------------------------
def grenze_app(g) -> list | None:
    """(Wert, Einheit, Bezug) → [ALT|HEI|STD, Wert, FT|FL|M] wie bisher (open flightmaps)"""
    if g is None:
        return None
    w, u, b = g
    u = (u or "FT").upper()
    if w.upper() in ("GND", "SFC"):
        return ["HEI", 0, "FT"]
    if w.upper() == "UNL":
        return ["STD", 999, "FL"]
    try:
        v = float(w)
    except ValueError:
        return None
    v = int(v) if v == int(v) else v
    if u == "FL":
        return ["STD", v, "FL"]
    bez = {"SFC": "HEI", "MSL": "ALT", "STD": "STD", "W84": "ALT"}.get((b or "MSL").upper(), "ALT")
    return [bez, v, "M" if u == "M" else "FT"]


def art(e: dict) -> str | None:
    t, lt, k = e["typ"], e["lokal"], e["klasse"]
    kn = e["kennung"] or ""
    if t in ("CTR", "CTR_P"):
        return "CTR"
    if t == "CLASS":
        if k == "G":
            return None             # Luftraum G (landesweit unter E bzw. über FL 660): stand bisher nicht in den Daten
        return "CLASS" if kn.startswith("EDCL") or k not in ("B", "C", "D") else "TMA"
    if t == "RAS" and lt in ("TMZ", "RMZ", "ATZ"):
        return lt
    if t in ("R", "OTHER:R_AMC", "P"):
        return "R"
    if t in ("D", "OTHER:D_AMC"):
        return "D"
    if t == "A":
        return {"PJA": "HPGLDR", "GLD": "GLDR", "ACR": "ACR", "UAV": "UAV"}.get(lt)
    if t == "PROTECT" and lt == "MIL LOW FLYING AREA":
        return "LFA"
    return None


def name_app(e: dict, a: str) -> str:
    kn, n = e["kennung"] or "", (e["name"] or e["kennung"] or "").strip()
    if a == "CLASS" and kn.startswith("EDCL") and kn[4:] in ("C", "CN", "E", "EN", "CS", "ES"):
        return "ALPINE AREA" if kn[4:] in ("CS", "ES") else "AREA"   # landesweite Einträge: in der App nur in der Abfrage
    m = re.match(r"^ED([RDP])(\d\w*)$", kn)
    if a in ("R", "D") and m:
        return f"ED-{m.group(1)} {m.group(2)} {n}"
    if a in ("R", "D"):
        return f"ED-{'R' if a == 'R' else 'D'} {n}"
    m = re.match(r"^ETLFA0*(\d+)$", kn)
    if a == "LFA" and m:
        return f"LFA {m.group(1)} {n}"
    if e["typ"] == "A":
        n = LAENDER.sub("", n).strip()
    return n


def _tag(c: str | None) -> str:
    return TAGE.get(c or "", (c or "").title())


def _datum(s: str | None) -> str:
    if not s:
        return ""
    if s == "SDLST":
        return "Beginn der Sommerzeit"
    if s == "EDLST":
        return "Ende der Sommerzeit"
    m = re.match(r"^(\d\d)-(\d\d)$", s)
    return f"{m.group(1)}.{m.group(2)}." if m else s


TAG_REIHE = ["ANY", "WORK_DAY", "MON", "TUE", "WED", "THU", "FRI", "BUSY_FRI", "SAT", "SUN", "BEF_WORK_DAY", "AFT_WORK_DAY", "HOL",
             "BEF_HOL", "AFT_HOL"]


def _zeitraum(s0: str | None, s1: str | None) -> str:
    if (s0, s1) == ("SDLST", "EDLST"):
        return "Sommer"
    if (s0, s1) == ("EDLST", "SDLST"):
        return "Winter"
    if (s0 or s1) and (s0, s1) != ("01-01", "31-12"):
        return f"{_datum(s0)}–{_datum(s1)}"
    return ""


def zeitplan_text(zp: list[dict]) -> str | None:
    """Timesheets → kurzer Text wie bisher („Mo–Fr 05:00–17:00 UTC“): je Zeitraum (Sommer/Winter/Daten) die Tage mit
    gleicher Zeit zusammengefasst; Zeiten mit Sommerzeit-Ausgleich sind während der Sommerzeit 1 Std früher (UTC)."""
    gruppen: dict = {}
    for t in zp:
        d0, d1 = t["day"], t["dayTil"]
        tage = _tag(d0) + ("" if not d1 or d1 == d0 else "–" + _tag(d1))
        a = t["startTime"] or EREIGNIS.get(t["startEvent"] or "", t["startEvent"] or "")
        b = t["endTime"] or EREIGNIS.get(t["endEvent"] or "", t["endEvent"] or "")
        if t["startTime"] and t["startEvent"]:
            a = f"{t['startEvent']} ({t['startTime']})"
        if t["endTime"] and t["endEvent"]:
            b = f"{t['endEvent']} ({t['endTime']})"
        ganz = a in ("00:00", "") and b in ("24:00", "00:00", "")
        zeit = "ganztags" if ganz else f"{a}–{b}"
        uhr = not ganz and bool(re.search(r"\d\d:\d\d", a + b))
        dst = uhr and (t["daylightSavingAdjust"] or "").upper() == "YES"
        k = (_zeitraum(t["startDate"], t["endDate"]), zeit, uhr, dst, (t["excluded"] or "").upper() == "YES")
        gruppen.setdefault(k, []).append((TAG_REIHE.index(d0) if d0 in TAG_REIHE else 99, tage))
    if not gruppen:
        return None
    zeitraeume: dict = {}
    for (zr, zeit, uhr, dst, aus), tage in gruppen.items():
        s = ("außer " if aus else "") + "/".join(x[1] for x in sorted(tage)) + " " + zeit
        zeitraeume.setdefault(zr, []).append((min(x[0] for x in tage), s, uhr, dst))
    uhr_alle = [x for v in zeitraeume.values() for x in v if x[2]]
    dst_alle = bool(uhr_alle) and all(x[3] for x in uhr_alle)
    teile = []
    for zr, v in zeitraeume.items():
        s = ", ".join(x[1] + (" (im Sommer 1 Std früher)" if x[3] and not dst_alle else "") for x in sorted(v))
        teile.append(f"{zr}: {s}" if zr else s)
    return "; ".join(teile) + (" UTC" if uhr_alle else "") + (" (während der Sommerzeit 1 Std früher)" if dst_alle else "")


def _zeilen(s: str | None) -> str | None:
    """Zeilenumbrüche behalten, Leerraum je Zeile kürzen (wie fcy_daten.luftraum)"""
    if not s:
        return None
    z = [re.sub(r"\s+", " ", x).strip() for x in s.replace("\r", "").split("\n")]
    return "\n".join(x for x in z if x) or None


def eintraege(raum: dict) -> tuple[list[dict], dict]:
    """→ ([{t, k, n, a, u, o, z, zt, zr, r, s, pts}], Zählung) — pts noch unkodiert [(lon, lat), …]"""
    out, zaehl = [], {"aus": {}, "ohne_grenze": 0, "teile": 0}
    for uid, e in raum.items():
        if e["typ"] == "PART":
            continue
        a = art(e)
        if a is None:
            k = f"{e['typ']}/{e['lokal'] or ''}".rstrip("/")
            zaehl["aus"][k] = zaehl["aus"].get(k, 0) + 1
            continue
        quellen = [(v["p"], v["u"], v["o"]) for v in e["vol"]]
        for t in e["teile"]:
            q = raum.get(t["ref"])
            if not q or q["typ"] != "PART" or t["op"] not in ("BASE", "UNION"):
                continue            # verweist auf einen eigenständigen Luftraum: der erscheint selbst
            for v in q["vol"]:
                quellen.append((v["p"], t["u"] or v["u"], t["o"] or v["o"]))
                zaehl["teile"] += 1
        notes = e["notes"]
        z = next((x[2] for x in notes if x[0] == "activation" and x[1] == "DESCRIPTION"), None)
        zr = _zeilen("\n".join(x[2] for x in notes if x[0] == "activation" and x[1] == "REMARK"))
        r = _zeilen("\n".join(x[2] for x in notes if x[0] != "activation" and x[1] in ("REMARK", "DESCRIPTION")))
        zt = zeitplan_text(e["zp"]) if z != "H24" else None
        for pts, u, o in quellen:
            U, O = grenze_app(u), grenze_app(o)
            if U is None or O is None:
                zaehl["ohne_grenze"] += 1
                continue
            x = {"t": a, "n": name_app(e, a), "u": U, "o": O, "pts": pts}
            if e["klasse"]:
                x["k"] = e["klasse"]
            if e["kennung"]:
                x["a"] = e["kennung"]
            if z:
                x["z"] = z
            if zt:
                x["zt"] = zt
            if zr and zr not in ("H24",):
                x["zr"] = zr
            if r:
                x["r"] = r
            if (z and z != "H24") or e["typ"] in ("OTHER:R_AMC", "OTHER:D_AMC"):
                x["s"] = 1
            out.append(x)
    return out, zaehl


def ergaenze_ofm(lr_dfs: list[dict], lr_ofm: list[dict], umriss) -> tuple[list[dict], dict]:
    """Einträge aus open flightmaps, die die DFS nicht führt (OFM_ERGAENZT ohne Gegenstück), mit q = "ofm" anhängen.
    umriss(e) → shapely-Fläche eines Eintrags (DFS: aus pts, ofm: aus p)."""
    from shapely.strtree import STRtree
    D = [umriss(e) for e in lr_dfs]
    baum = STRtree(D)
    dazu, gleich = [], 0
    for e in lr_ofm:
        if e["t"] not in OFM_ERGAENZT:
            continue
        P = umriss(e)
        treffer = False
        for i in baum.query(P):
            Q = D[i]
            if P.intersects(Q):
                u = P.union(Q).area
                if u > 0 and P.intersection(Q).area / u >= UEBERDECKUNG:
                    treffer = True
                    break
        if treffer:
            gleich += 1
            continue
        x = dict(e)
        x["q"] = "ofm"
        dazu.append(x)
    arten = {}
    for x in dazu:
        arten[x["t"]] = arten.get(x["t"], 0) + 1
    return dazu, {"ergaenzt": arten, "schon_bei_dfs": gleich}


def zyklus_von(airac: str) -> str:
    """„2026-10-29“ → AIRAC-Kennung „2611“ (wie fcy_daten.luftraum.zyklus)"""
    from .luftraum import zyklus
    return zyklus(dt.datetime.fromisoformat(airac + "T00:00:00+00:00"))[0]


# ----------------------------------------------------------------------------------------------
# Datei luftraum-dfs.bin: Lufträume der DFS, Flugplätze, Meldepunkte und Umriss aus luftraum.bin (open flightmaps)
# ----------------------------------------------------------------------------------------------
def inhalt(ofm: dict, raum: dict, dfs: dict) -> tuple[dict, dict]:
    """Ein Zyklus: ofm = Inhalt aus luftraum.bin, raum = gelesene AIXM-Datei, dfs = Übersicht {name, airac}."""
    from shapely.geometry import Polygon
    from . import format as F
    from .luftraum import TOL_LR, kodiere, vereinfache
    roh, z = eintraege(raum)
    lr = []
    for x in roh:
        p, b = kodiere(vereinfache(x.pop("pts"), TOL_LR))
        if len(p) < 6:
            z["ohne_grenze"] += 1
            continue
        x["p"], x["b"] = p, b
        lr.append(x)
    flaeche = lambda e: Polygon(F.umriss_aus(e["p"])).buffer(0)
    dazu, zo = ergaenze_ofm(lr, ofm["lr"], flaeche)
    z.update(zo)
    lr += dazu
    lr.sort(key=lambda e: (e["t"], e["n"], e["b"]))
    return ({"zyklus": ofm["zyklus"], "ab": ofm["ab"], "bis": ofm["bis"], "stand": ofm["stand"],
             "stand_lr": dfs["airac"] + " (" + dfs["name"] + ")", "quelle": "DFS (Lufträume), open flightmaps (Plätze, Meldepunkte, Ergänzungen)",
             "lr": lr, "ad": ofm["ad"], "dp": ofm["dp"], "de": ofm["de"]}, z)


def main(argv=None) -> int:
    import argparse
    import sys
    from . import format as F
    ap = argparse.ArgumentParser(description="Lufträume der DFS in die Luftraum-Datei des Flight Log (luftraum-dfs.bin)")
    ap.add_argument("--ofm", required=True, help="luftraum.bin aus fcy_daten.luftraum (Plätze, Meldepunkte, Umriss, Ergänzungen)")
    ap.add_argument("--aus", required=True)
    ap.add_argument("--xml", nargs="*", default=[], help="DFS-Dateien statt Abruf, je „Zyklus=Datei“ (z. B. 2611=ED_Airspace….xml) — für Tests")
    a = ap.parse_args(argv)
    d = open(a.ofm, "rb").read()
    K = F.kopf_lesen(d, b"FCYL")
    vorgabe = dict(x.split("=", 1) for x in a.xml)
    dfs = {}
    if not vorgabe:
        for n in (0, 1):
            u = uebersicht(n)
            if u:
                dfs[zyklus_von(u["airac"])] = u
        print("DFS ED Airspace: " + ", ".join(f"{k} ab {u['airac']} ({u['name']})" for k, u in sorted(dfs.items())), flush=True)
    inhalte = []
    for zk in K["zyklen"]:
        k = zk["zyklus"]
        ofm = F.lese_luftraum(d, k)
        if k in vorgabe:
            daten, u = open(vorgabe[k], "rb").read(), {"name": vorgabe[k].split("/")[-1], "airac": ofm["ab"][:10]}
        elif k in dfs:
            u = dfs[k]
            daten = lade(u)
        else:
            if k == K["zyklen"][0]["zyklus"]:
                raise SystemExit(f"DFS-Datensatz für den Zyklus {k} nicht verfügbar")
            print(f"  Zyklus {k}: bei der DFS nicht verfügbar — nicht in der Datei", flush=True)
            continue
        i, z = inhalt(ofm, lies_aixm(daten), u)
        arten = {}
        for e in i["lr"]:
            arten[e["t"]] = arten.get(e["t"], 0) + 1
        print(f"  Zyklus {k}: {len(i['lr'])} Lufträume (" + ", ".join(f"{t} {n}" for t, n in sorted(arten.items())) + "), "
              f"davon aus open flightmaps ergänzt: " + ", ".join(f"{t} {n}" for t, n in sorted(z["ergaenzt"].items())) +
              f"; Teile {z['teile']}; nicht übernommen: " + ", ".join(f"{t} {n}" for t, n in sorted(z["aus"].items())) +
              (f"; ohne Grenzen/Umriss {z['ohne_grenze']}" if z["ohne_grenze"] else ""), flush=True)
        inhalte.append(i)
    if not inhalte:
        raise SystemExit("keine Zyklen")
    kopf = {"quelle": "Lufträume: DFS (" + LIZENZ + "); Flugplätze, VFR-Meldepunkte, Umriss Deutschlands, Naturschutz-, Segelflug- "
                      "und Fallschirmsprunggebiete ohne Gegenstück bei der DFS: open flightmaps (" + K.get("quelle", "") + ")",
            "region": K.get("region", "ED"), "erzeugt": K.get("erzeugt", ""),
            "lauf": " ".join(f"{i['zyklus']}@{i['stand']}+{i['stand_lr'].split(' ')[0]}" for i in inhalte)}
    R = F.schreibe_luftraum(a.aus, kopf, inhalte)
    print(f"geschrieben: {a.aus} · " + " · ".join(f"{z['zyklus']}: {z['lr']} Lufträume, {z['bytes'] // 1024} kB" for z in R["zyklen"]), flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
