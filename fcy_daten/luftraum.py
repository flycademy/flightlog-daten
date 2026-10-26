"""Lufträume, Flugplätze und Meldepunkte Deutschlands aus open flightmaps (OFMX, Region ED), je AIRAC-Zyklus.

  python -m fcy_daten.luftraum --aus out/luftraum.bin

Ablauf:
  1. Für den laufenden und den nächsten AIRAC-Zyklus die Übersicht
     https://snapshots.openflightmaps.org/publicationServices/ED_<Zyklus>.xml lesen (Gültigkeit, Dateien mit Zeitstempel).
     Der nächste Zyklus steht dort etwa eine Woche vor Beginn bereit; fehlt er noch, kommt nur der laufende in die Datei.
  2. Die OFMX-Datei ofmx_ed.zip laden. Aus „isolated“ (nur Deutschland, ohne Nachbarländer):
       ofmx_ed.ofmx                  Lufträume (Art, Klasse, Name, Unter-/Obergrenze, Zeitplan), Flugplätze, Meldepunkte
       ofmx_ed_ofmShapeExtension.xml Umriss jedes Luftraums als Polygon (Bögen und Kreise von open flightmaps aufgelöst,
                                     Grenzverläufe auf einen Korridor von 0,03 NM vereinfacht)
     Lufträume mit gleicher Ausdehnung wie ein anderer (Adg/AseUidSameExtent) bekommen dessen Umriss. Ohne Unter- und
     Obergrenze (Sammel-Einträge „AREA“) und die Arten FIR, UIR, SECTOR, DRAFT kommen nicht in die Liste; die FIR bilden
     zusammengefasst den Umriss Deutschlands (de), in dem die App diese Daten statt des openAIP-Kartenbilds zeigt — ohne
     innere Grenzen, damit an den FIR-Grenzen kein Streifen des openAIP-Kartenbilds durchscheint.
  3. Umrisse mit Douglas-Peucker auf 0,0002° (rund 20 m) vereinfachen, auf 1e-5 Grad runden, Differenzen speichern.
  4. Datei FCYL schreiben (fcy_daten/format.py). „erzeugt“ ist der neueste OFMX-Stand — gleiche Eingabe, gleiche Datei,
     damit der Datendienst nur bei neuen Daten neu lädt.

Lizenz: OFMA General Users' License (openflightmaps.org/about): Nutzung auch kommerziell, open flightmaps als Quelle nennen,
Fehler an open flightmaps melden (die App verlinkt dafür). Nicht zertifiziert, nie Primärquelle für die Navigation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

from . import format as F
from . import netz

QUELLE = "https://snapshots.openflightmaps.org"
UTC = dt.timezone.utc
AIRAC_0 = dt.datetime(2020, 1, 2, tzinfo=UTC)
AIRAC_T = dt.timedelta(days=28)
OHNE = {"FIR", "UIR", "SECTOR", "DRAFT"}
AD_ARTEN = {"AD", "GLD", "UL"}
TOL_LR = 0.0002
TOL_DE = 0.002
SCHLIESSEN = 0.002       # Lücken zwischen den FIR-Umrissen bis rund 200 m schließen (Grad)
LIZENZ = ("open flightmaps association, OFMA General Users' License (openflightmaps.org/about): Nutzung auch kommerziell, "
          "Quelle nennen, Fehler an open flightmaps melden; nicht zertifiziert, nie Primärquelle für die Navigation")


# ----------------------------------------------------------------------------------------------
# AIRAC
# ----------------------------------------------------------------------------------------------
def zyklus(t: dt.datetime) -> tuple[str, dt.datetime, dt.datetime]:
    """(Kennung „JJNN“, Beginn, Ende) des Zyklus, der zum Zeitpunkt t gilt."""
    n = (t - AIRAC_0) // AIRAC_T
    ab = AIRAC_0 + n * AIRAC_T
    erstes = AIRAC_0 + math.ceil((dt.datetime(ab.year, 1, 1, tzinfo=UTC) - AIRAC_0) / AIRAC_T) * AIRAC_T
    return f"{ab.year % 100:02d}{(ab - erstes) // AIRAC_T + 1:02d}", ab, ab + AIRAC_T


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------------------------
# Übersicht eines Zyklus
# ----------------------------------------------------------------------------------------------
def lies_uebersicht(xml: bytes, kennung: str) -> dict:
    """{ab, bis, ofmx: URL, stand: Zeitstempel} oder {} (Zyklus oder Datei fehlt)."""
    r = ET.fromstring(xml)
    zy = next((c for c in r.iter("cycle") if c.get("id") == kennung), None)
    if zy is None:
        return {}
    dl = next((d for d in r.iter("download") if (d.get("name") or "").upper() == "OFMX ED"
               and (d.get("inProgress") or "False").lower() != "true" and d.get("URL")), None)
    if dl is None:
        return {}
    url = dl.get("URL")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://") and url[7:].split("/")[0].endswith("openflightmaps.org"):
        url = "https://" + url[7:]
    return {"ab": zy.get("startValidity"), "bis": zy.get("endValidity"), "ofmx": url, "stand": dl.get("timestamp")}


# ----------------------------------------------------------------------------------------------
# Geometrie
# ----------------------------------------------------------------------------------------------
def _rdp(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker; lon mit cos(lat) gestaucht, damit die Toleranz in beiden Richtungen etwa gleich weit reicht."""
    if len(pts) < 4:
        return pts
    k = math.cos(math.radians(sum(p[1] for p in pts) / len(pts)))
    P = [(x * k, y) for x, y in pts]
    keep = [False] * len(P)
    keep[0] = keep[-1] = True
    stack = [(0, len(P) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = P[a]; bx, by = P[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = P[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / L if L > 0 else math.hypot(px - ax, py - ay)
            if d > best:
                best, bi = d, i
        if best > tol and bi > 0:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k_ in zip(pts, keep) if k_]


def vereinfache(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Geschlossenen Ring vereinfachen: in zwei Hälften teilen (Anfang = Ende), damit der Ring nicht zu einer Linie wird."""
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 8:
        return pts
    m = len(pts) // 2
    a = _rdp(pts[:m + 1], tol)
    b = _rdp(pts[m:] + [pts[0]], tol)
    out = a[:-1] + b[:-1]
    return out if len(out) >= 3 else pts


def maske(firs: list[list[tuple[float, float]]]) -> list[list[int]]:
    """FIR-Umrisse → Umriss Deutschlands: vereinigt, kleine Lücken geschlossen, nur Außenringe, vereinfacht, kodiert wie p."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    P = [Polygon(p).buffer(0) for p in firs if len(p) >= 4]
    if not P:
        return []
    u = unary_union(P).buffer(SCHLIESSEN, join_style=2).buffer(-SCHLIESSEN, join_style=2).simplify(TOL_DE, preserve_topology=True)
    teile = [u] if u.geom_type == "Polygon" else [g for g in getattr(u, "geoms", []) if g.geom_type == "Polygon"]
    out = []
    for g in sorted(teile, key=lambda g: -g.area):
        if g.area >= 1e-3:                                   # Splitter unter etwa 3 km² weglassen
            out.append(kodiere([(round(x, 6), round(y, 6)) for x, y in g.exterior.coords])[0])
    return out


def kodiere(pts: list[tuple[float, float]]) -> tuple[list[int], list[int]]:
    """→ (p, b): p erstes Paar absolut, danach Differenzen (1e-5 Grad); b = Rahmen [lon_min, lat_min, lon_max, lat_max]."""
    q = []
    for x, y in pts:
        z = (round(x * 1e5), round(y * 1e5))
        if not q or q[-1] != z:
            q.append(z)
    if len(q) > 1 and q[0] == q[-1]:
        q.pop()
    p = [q[0][0], q[0][1]]
    for (x0, y0), (x1, y1) in zip(q, q[1:]):
        p += [x1 - x0, y1 - y0]
    xs, ys = [z[0] for z in q], [z[1] for z in q]
    return p, [min(xs), min(ys), max(xs), max(ys)]


def _poslist(t: str) -> list[tuple[float, float]]:
    out = []
    for tri in t.split():
        a = tri.split(",")
        out.append((float(a[0]), float(a[1])))
    return out


def _grad(s: str | None) -> float | None:
    """„52.31936111N“ / „010.55888889E“ → Grad"""
    if not s:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)([NSEW])\s*$", s)
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2) in "SW" else v


# ----------------------------------------------------------------------------------------------
# Umwandlung
# ----------------------------------------------------------------------------------------------
def _t(e: ET.Element | None, tag: str) -> str | None:
    if e is None:
        return None
    x = e.find(tag)
    return x.text.strip() if x is not None and x.text is not None and x.text.strip() else None


def _zeilen(s: str | None) -> str | None:
    """Zeilenumbrüche behalten (Bemerkungen sind oft zeilenweise gegliedert), Leerraum je Zeile kürzen."""
    if not s:
        return None
    z = [re.sub(r"[ \t]+", " ", x).strip() for x in s.replace("\r", "").split("\n")]
    return "\n".join(x for x in z if x) or None


def _grenze(ase: ET.Element, wo: str):
    c, v, u = _t(ase, "codeDistVer" + wo), _t(ase, "valDistVer" + wo), _t(ase, "uomDistVer" + wo)
    if c is None or v is None:
        return None
    try:
        w = float(v)
    except ValueError:
        return None
    return [c, int(w) if w == int(w) else w, u or "FT"]


TAGE = {"MON": "Mo", "TUE": "Di", "WED": "Mi", "THU": "Do", "FRI": "Fr", "SAT": "Sa", "SUN": "So", "HOL": "Feiertag",
        "ANY": "täglich", "WD": "werktags", "PWD": "vor Werktagen", "AWD": "nach Werktagen", "LH": "Feiertage", "BH": "Brückentage"}


def zeitplan(att: ET.Element | None) -> tuple[str | None, str | None, str | None]:
    """(codeWorkHr, Zeitplan kurz, Bemerkung)"""
    if att is None:
        return None, None, None
    code = _t(att, "codeWorkHr")
    teile = []
    for ts in att.findall("Timsh"):
        d0, d1 = _t(ts, "codeDay"), _t(ts, "codeDayTil")
        tage = TAGE.get(d0 or "", d0 or "") + ("" if not d1 or d1 == d0 else "–" + TAGE.get(d1, d1))
        w0, w1 = _t(ts, "timeWef"), _t(ts, "timeTil")
        zeit = f"{w0}–{w1}" if w0 and w1 else (w0 or w1 or "")
        v0, v1 = _t(ts, "dateValidWef"), _t(ts, "dateValidTil")
        datum = "" if (v0, v1) in ((None, None), ("01-01", "31-12")) else f" ({v0 or ''}–{v1 or ''})"
        ref = _t(ts, "codeTimeRef") or "UTC"
        teile.append(f"{tage} {zeit}{datum}".strip() + ("" if ref == "UTC" else f" {ref}"))
    rmk = _zeilen(_t(att, "txtRmkWorkHr"))
    kurz = (", ".join(teile) + (" UTC" if teile and all(not re.search(r" UTC\w*$", x) for x in teile) else "")) if teile else None
    return code, kurz, rmk


def wandle(ofmx: bytes, shape: bytes) -> dict:
    """OFMX + Shape-Extension → {lr, ad, dp, de, stand}"""
    S = {}
    for a in ET.fromstring(shape).iter("Ase"):
        uid = a.find("AseUid")
        mid = (uid.get("mid") if uid is not None else None) or a.get("mid")
        pl = a.find("gmlPosList")
        if mid and pl is not None and pl.text:
            S[mid] = _poslist(pl.text)
    root = ET.fromstring(ofmx)
    stand = root.get("effective") or root.get("created") or ""
    gleich = {}
    for adg in root.iter("Adg"):
        a, b = adg.find("AdgUid/AseUid"), adg.find("AseUidSameExtent")
        if a is not None and b is not None:
            gleich[a.get("mid")] = b.get("mid")
    lr, firs = [], []
    fehlt = 0
    for ase in root.findall("Ase"):
        uid = ase.find("AseUid")
        mid, art = uid.get("mid"), _t(uid, "codeType") or "CLASS"   # ohne Art: Luftraum E ab 1000/1700 ft GND (Klassengrenze)
        pts = S.get(mid) or S.get(gleich.get(mid, ""))
        if art == "FIR":
            if pts:
                firs.append(pts)
            continue
        if art in OHNE:
            continue
        u, o = _grenze(ase, "Lower"), _grenze(ase, "Upper")
        if u is None or o is None:
            continue                     # Sammel-Eintrag ohne Höhen (z. B. „AREA“)
        if not pts or len(pts) < 3:
            fehlt += 1
            continue
        p, b = kodiere(vereinfache(pts, TOL_LR))
        if len(p) < 6:
            fehlt += 1
            continue
        z, zt, zr = zeitplan(ase.find("Att"))
        e = {"t": art, "n": _t(ase, "txtName") or _t(uid, "codeId"), "u": u, "o": o, "p": p, "b": b}
        for k, v in (("k", _t(ase, "codeClass")), ("a", _zeilen(_t(ase, "txtNameAlt"))), ("z", z), ("zt", zt), ("zr", zr), ("r", _zeilen(_t(ase, "txtRmk")))):
            if v:
                e[k] = v
        if _t(ase, "codeSelAvbl") == "Y":
            e["s"] = 1
        lr.append(e)
    ad = []
    for ahp in root.findall("Ahp"):
        art = _t(ahp, "codeType")
        if art not in AD_ARTEN:
            continue
        lat, lon = _grad(_t(ahp, "geoLat")), _grad(_t(ahp, "geoLong"))
        if lat is None or lon is None:
            continue
        el = _t(ahp, "valElev")
        try:
            h = float(el) if el is not None else None
            if h is not None and (_t(ahp, "uomDistVer") or "FT") == "M":
                h = h / 0.3048
        except ValueError:
            h = None
        kennung = _t(ahp, "codeIcao") or _t(ahp, "codeGps") or _t(ahp.find("AhpUid"), "codeId")
        ad.append([kennung, _t(ahp, "txtName") or kennung, art, round(lat, 5), round(lon, 5), None if h is None else int(round(h))])
    dp = []
    for dpn in root.findall("Dpn"):
        uid = dpn.find("DpnUid")
        lat, lon = _grad(_t(uid, "geoLat")), _grad(_t(uid, "geoLong"))
        if lat is None or lon is None:
            continue
        dp.append([_t(uid, "codeId"), _t(dpn, "txtName") or _t(uid, "codeId"), _t(dpn, "codeType") or "", round(lat, 5), round(lon, 5),
                   _t(dpn.find("AhpUidAssoc"), "codeId") or ""])
    lr.sort(key=lambda e: (e["t"], e["n"], e["b"]))
    ad.sort(key=lambda x: (x[0] or "", x[1]))
    dp.sort(key=lambda x: (x[5], x[0], x[3], x[4]))
    return {"lr": lr, "ad": ad, "dp": dp, "de": maske(firs), "firs": len(firs), "stand": stand, "ohne_umriss": fehlt}


def aus_zip(daten: bytes, region: str = "ed") -> tuple[bytes, bytes]:
    with zipfile.ZipFile(io.BytesIO(daten)) as z:
        n = {x.lower(): x for x in z.namelist()}
        o = n.get(f"ofmx_{region}/isolated/ofmx_{region}.ofmx")
        s = n.get(f"ofmx_{region}/isolated/ofmx_{region}_ofmshapeextension.xml")
        if not o or not s:
            raise RuntimeError(f"OFMX-Archiv unvollständig: {sorted(z.namelist())[:10]}")
        return z.read(o), z.read(s)


def zyklus_inhalt(kennung: str, region: str = "ed", quelle: str = QUELLE) -> dict | None:
    xml = netz.hole(f"{quelle}/publicationServices/{region.upper()}_{kennung}.xml", ok404=True)
    if not xml:
        return None
    u = lies_uebersicht(xml, kennung)
    if not u:
        return None
    ofmx, shape = aus_zip(netz.hole(u["ofmx"], timeout=180), region)
    w = wandle(ofmx, shape)
    print(f"  Zyklus {kennung} ({u['ab'][:10]} – {u['bis'][:10]}), OFMX vom {u['stand']}: {len(w['lr'])} Lufträume, "
          f"{len(w['ad'])} Flugplätze, {len(w['dp'])} Meldepunkte, Umriss aus {w['firs']} FIR ({len(w['de'])} Teil(e), "
          f"{sum(len(x) // 2 for x in w['de'])} Punkte)"
          + (f", {w['ohne_umriss']} Lufträume ohne Umriss ausgelassen" if w["ohne_umriss"] else ""), flush=True)
    return {"zyklus": kennung, "ab": u["ab"], "bis": u["bis"], "stand": u["stand"] or w["stand"], "quelle": "open flightmaps",
            "lr": w["lr"], "ad": w["ad"], "dp": w["dp"], "de": w["de"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--region", default="ed")
    ap.add_argument("--quelle", default=QUELLE)
    ap.add_argument("--jetzt", help="Zeitpunkt (ISO, UTC) statt der aktuellen Zeit — für Tests")
    a = ap.parse_args(argv)
    jetzt = dt.datetime.fromisoformat(a.jetzt.replace("Z", "+00:00")) if a.jetzt else dt.datetime.now(UTC)
    k0, ab0, _ = zyklus(jetzt)
    k1, _, _ = zyklus(ab0 + AIRAC_T)
    print(f"AIRAC laufend {k0}, nächster {k1}", flush=True)
    inhalte = []
    for k in (k0, k1):
        try:
            i = zyklus_inhalt(k, a.region, a.quelle)
        except Exception as e:  # noqa: BLE001 — der nächste Zyklus darf fehlen oder unfertig sein
            if k == k0:
                raise
            print(f"  Zyklus {k}: nicht verwendbar ({e})", flush=True)
            continue
        if i is None:
            print(f"  Zyklus {k}: noch nicht veröffentlicht", flush=True)
            if k == k0:
                raise SystemExit(f"laufender Zyklus {k0} nicht verfügbar")
            continue
        inhalte.append(i)
    kopf = {"quelle": "open flightmaps (" + LIZENZ + ")", "region": a.region.upper(),
            "erzeugt": max(i["stand"] for i in inhalte),
            "lauf": " ".join(f"{i['zyklus']}@{i['stand']}" for i in inhalte)}   # Fassung: Zyklen und Stände
    K = F.schreibe_luftraum(a.aus, kopf, inhalte)
    print(f"geschrieben: {a.aus} · " + " · ".join(f"{z['zyklus']}: {z['lr']} Lufträume, {z['bytes'] // 1024} kB" for z in K["zyklen"]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
