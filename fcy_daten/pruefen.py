"""Prüfungen der erzeugten Dateien vor dem Hochladen (GitHub Actions). Bei einem Fehler wird nicht hochgeladen —
auf dem Server bleibt die vorige Datei, der Flight Log zeigt deren Laufzeit an.

  python -m fcy_daten.pruefen wind out/wind.bin [--vergleich]
  python -m fcy_daten.pruefen gelaende out/gelaende.bin
  python -m fcy_daten.pruefen orte out/orte.bin
  python -m fcy_daten.pruefen luftraum out/luftraum.bin [--jetzt 2026-10-26T12:00:00Z]
  python -m fcy_daten.pruefen pisten out/pisten.bin

--vergleich: Bodenwerte und 850-hPa-Wind an einigen Plätzen gegen Open-Meteo (Modell icon_d2) — fängt grobe Fehler
der Aufbereitung ab (vertauschte Achsen, falsche Einheiten, falsche Zeit). Ist Open-Meteo nicht erreichbar, nur Hinweis.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import struct
import sys

import numpy as np

from . import format as F
from . import netz

ZEILEN = []


def melde(ok: bool, txt: str, wichtig: bool = True) -> bool:
    ZEILEN.append(("✅" if ok else ("❌" if wichtig else "⚠️")) + " " + txt)
    print(("OK   " if ok else ("FEHLER " if wichtig else "HINWEIS ")) + txt, flush=True)
    return ok or not wichtig


def zusammenfassung(titel: str):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"### {titel}\n\n" + "\n".join(f"- {z}" for z in ZEILEN) + "\n\n")


def wind_wert(d: bytes, K: dict, lat: float, lon: float, schritt: int, ft_ziel: float):
    """Wind (u, v kt) an einem Punkt in einer Höhe (linear zwischen den festen Höhen) — nächster Gitterpunkt."""
    g = K["gitter"]
    i = int(round((lat - g["lat0"]) / g["d"])); j = int(round((lon - g["lon0"]) / g["d"]))
    p = F.lese_wind_punkt(d, i, j)
    if p is None:
        return None
    H = K["hoehen_ft"]
    s = K["schritte_h"].index(schritt)
    for a in range(len(H) - 1):
        if H[a] <= ft_ziel <= H[a + 1]:
            w = (ft_ziel - H[a]) / (H[a + 1] - H[a])
            x0, x1 = p[s, a].astype(float), p[s, a + 1].astype(float)
            if -128 in x0 or -128 in x1:
                return None
            x = (1 - w) * x0 + w * x1
            return x[0], x[1], x[2]
    return None


def pruefe_wind(pfad: str, vergleich: bool) -> bool:
    d = open(pfad, "rb").read()
    K = F.kopf_lesen(d, b"FCYW")
    ok = True
    lauf = dt.datetime.strptime(K["lauf"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    alter = (dt.datetime.now(dt.timezone.utc) - lauf).total_seconds() / 3600
    ok &= melde(K["modell"] == "ICON-D2" and alter < 12, f"Lauf {K['lauf']} ({alter:.1f} h alt), Modell {K['modell']}")
    g = K["gitter"]
    ok &= melde(g["nlat"] > 100 and g["nlon"] > 150, f"Gitter {g['nlat']} × {g['nlon']} ab {g['lat0']}° N / {g['lon0']}° E, {g['d']}°")
    # Stichprobe über das ganze Gitter
    alle = []
    for i in range(0, g["nlat"], 7):
        for j in range(0, g["nlon"], 7):
            alle.append(F.lese_wind_punkt(d, i, j))
    A = np.stack(alle).astype(float)         # n, schritt, hoehe, 3
    A[A == -128] = np.nan
    a5 = list(K["hoehen_ft"]).index(5000)
    innen = ~np.isnan(A[:, :, -1, 0])          # in 14 000 ft vorhanden = im Modellgebiet (die Ecken des Rechtecks liegen außerhalb)
    aussen = 1.0 - float(innen.mean())
    fehlt5 = float(np.isnan(A[:, :, a5, 0])[innen].mean())
    ok &= melde(aussen < 0.35, f"außerhalb des ICON-D2-Gebiets: {aussen:.1%} der Stichprobe (Ecken des Rechtecks, höchstens 35 %)")
    ok &= melde(fehlt5 < 0.10, f"5000 ft: {fehlt5:.1%} der Punkte im Gebiet fehlen (unter Gelände, höchstens 10 %)")
    sp = np.hypot(A[..., 0], A[..., 1])
    ok &= melde(np.nanmax(sp) < 160 and np.nanmean(sp) > 2, f"Windgeschwindigkeit Mittel {np.nanmean(sp):.1f} kt, höchstens {np.nanmax(sp):.0f} kt")
    t = A[..., 2]
    t1, t14 = np.nanmean(t[:, :, 0]), np.nanmean(t[:, :, -1])
    ok &= melde(-60 < np.nanmin(t) and np.nanmax(t) < 45 and t1 > t14 + 10, f"Temperatur 1000 ft Mittel {t1:.1f} °C, 14 000 ft {t14:.1f} °C (nimmt mit der Höhe ab)")
    P = K["plaetze"]
    ok &= melde(P["anzahl"] > 300 and F.lese_platz(d, "EDVE") is not None, f"{P['anzahl']} Plätze, EDVE dabei")
    e = F.lese_platz(d, "EDVE")
    if e is not None:
        ok &= melde(np.all(np.isfinite(e[1:, :5])) and 950 < np.nanmean(e[:, 2]) < 1060 and -40 < np.nanmean(e[:, 0]) < 45,
                    f"EDVE: QNH {np.nanmean(e[:, 2]):.1f} hPa, Temperatur {np.nanmean(e[:, 0]):.1f} °C im Mittel, keine Lücken")
    if not vergleich:
        return ok
    # Vergleich mit Open-Meteo (icon_d2) an Plätzen zur Stunde +3 h
    plaetze = {"EDVE": (52.3192, 10.5561), "EDDH": (53.6304, 9.9882), "EDDM": (48.3538, 11.7861), "EDDK": (50.8659, 7.1427),
               "EDDP": (51.4239, 12.2364), "LOWS": (47.7933, 13.0043), "EPWR": (51.1027, 16.8858), "LKPR": (50.1008, 14.26)}
    st = 3
    zeit = lauf + dt.timedelta(hours=st)
    tag = zeit.strftime("%Y-%m-%d")
    abw = []
    try:
        lat = ",".join(str(v[0]) for v in plaetze.values()); lon = ",".join(str(v[1]) for v in plaetze.values())
        url = ("https://api.open-meteo.com/v1/forecast?latitude=" + lat + "&longitude=" + lon +
               "&hourly=temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,wind_speed_850hPa,wind_direction_850hPa,geopotential_height_850hPa"
               f"&models=icon_d2&wind_speed_unit=kn&timezone=UTC&start_date={tag}&end_date={tag}")
        om = json.loads(netz.hole(url, versuche=2, timeout=60))
        om = om if isinstance(om, list) else [om]
    except Exception as ex:  # noqa: BLE001
        melde(False, f"Vergleich mit Open-Meteo nicht möglich: {ex}", wichtig=False)
        return ok
    schlecht = 0; n = 0
    for (ic, (la, lo)), o in zip(plaetze.items(), om):
        h = o.get("hourly", {})
        try:
            k = h["time"].index(zeit.strftime("%Y-%m-%dT%H:00"))
        except (KeyError, ValueError):
            continue
        b = F.lese_platz(d, ic)
        if b is not None:
            si = K["boden_schritte_h"].index(st)
            dt2 = b[si, 0] - h["temperature_2m"][k]; dp = b[si, 2] - h["pressure_msl"][k]
            ws = math.hypot(b[si, 3], b[si, 4]) - h["wind_speed_10m"][k]
            gut = abs(dt2) <= 3 and abs(dp) <= 1.5 and abs(ws) <= 5
            n += 1; schlecht += not gut
            abw.append(f"{ic} Boden: ΔT {dt2:+.1f} °C, ΔQNH {dp:+.1f} hPa, ΔWind {ws:+.1f} kt")
        z850 = h.get("geopotential_height_850hPa", [None] * 99)[k]
        if z850:
            w = wind_wert(d, K, la, lo, st, z850 / 0.3048)
            if w:
                kt = math.hypot(w[0], w[1]); dr = (math.degrees(math.atan2(-w[0], -w[1])) + 360) % 360
                okt, odr = h["wind_speed_850hPa"][k], h["wind_direction_850hPa"][k]
                ddir = abs((dr - odr + 180) % 360 - 180)
                gut = abs(kt - okt) <= 8 and (okt < 10 or ddir <= 30)
                n += 1; schlecht += not gut
                abw.append(f"{ic} 850 hPa ({z850:.0f} m): {dr:.0f}°/{kt:.0f} kt gegen {odr:.0f}°/{okt:.0f} kt")
    for a in abw:
        print("   " + a)
    melde(schlecht == 0, f"Vergleich mit Open-Meteo icon_d2 (+{st} h): {n - schlecht} von {n} innerhalb der Toleranz", wichtig=False)
    ZEILEN.extend("  " + a for a in abw)
    ok &= melde(n == 0 or schlecht <= n // 2, "kein systematischer Fehler (höchstens die Hälfte außerhalb der Toleranz)")
    return ok


def pruefe_gelaende(pfad: str) -> bool:
    d = open(pfad, "rb").read()
    K = F.kopf_lesen(d, b"FCYG")
    ok = melde(K["kacheln_fehlt"] == 0, f"{K['kacheln_land']} Land-, {K['kacheln_meer']} Meerkacheln, {K['kacheln_fehlt']} fehlen")
    ziele = [("Brocken", 51.7991, 10.6156, 1130, 1160), ("Zugspitze", 47.4211, 10.9853, 2930, 2975),
             ("Großglockner", 47.0742, 12.6947, 3770, 3810), ("Matterhorn", 45.9763, 7.6586, 4440, 4490),
             ("Mont Blanc", 45.8326, 6.8652, 4780, 4820), ("EDVE", 52.3192, 10.5561, 75, 110), ("Nordsee", 54.5, 6.5, -5, 5)]
    for name, la, lo, mn, mx in ziele:
        if not (K["lat0"] <= la < K["lat1"] and K["lon0"] <= lo < K["lon1"]):
            continue
        t = F.lese_gelaende_kachel(d, int(math.floor(la)), int(math.floor(lo)))
        if isinstance(t, str):
            v = 0
        elif t is None:
            v = None
        else:
            # Höchstwert im Umkreis von 1 Zelle (Gipfel kann am Zellrand liegen)
            r = int((math.floor(la) + 1 - la) * K["n"]); c = int((lo - math.floor(lo)) * K["n"])
            v = int(t[max(0, r - 1):r + 2, max(0, c - 1):c + 2].max())
        ok &= melde(v is not None and mn <= v <= mx, f"{name}: {v} m (erwartet {mn}–{mx})")
    g = K.get("gipfel")
    if g:
        print(f"   Gipfel aus GeoNames: {g['angehoben']} Zellen angehoben, {g['uebersprungen']} übersprungen (mehr als {g['grenze_m']} m über dem Gelände)")
    return ok


def pruefe_orte(pfad: str) -> bool:
    d = open(pfad, "rb").read()
    K = F.kopf_lesen(d, b"FCYO")
    ok = melde(K["anzahl"] > 100000, f"{K['anzahl']} Suchschlüssel")
    idx = struct.unpack_from(f"<{K['anzahl']}I", d, K["index_ab"])
    def suche(q):
        n = F.normiere(q).encode()
        lo, hi = 0, len(idx)
        while lo < hi:
            m = (lo + hi) // 2
            k = d[idx[m]:d.index(b"\t", idx[m])]
            if k < n:
                lo = m + 1
            else:
                hi = m
        out = []
        while lo < len(idx):
            z = d[idx[lo]:d.index(b"\n", idx[lo])].split(b"\t")
            if not z[0].startswith(n):
                break
            out.append(z[2].decode()); lo += 1
        return out
    for q, soll in [("Braunschweig", "Braunschweig"), ("Muenchen", "München"), ("Mailand", "Mailand"), ("Koeln", "Köln"), ("Waggum", "Waggum"),
                    ("Steinhuder Meer", "Steinhuder Meer"), ("Zagreb", "Zagreb"), ("Brocken", "Brocken")]:
        r = suche(q)
        ok &= melde(soll in r, f"„{q}“ findet „{soll}“ ({len(r)} Treffer)")
    return ok


def im_umriss(lon: float, lat: float, pts: list[tuple[float, float]]) -> bool:
    """Punkt im Polygon (Strahlverfahren)."""
    drin = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > lat) != (y1 > lat) and lon < x0 + (lat - y0) * (x1 - x0) / (y1 - y0):
            drin = not drin
    return drin


# Stichproben: Flugplatz (ICAO), Kontrollzone mit diesem Platz darin. Die Grenzen selbst ändern sich mit dem AIRAC-Zyklus
# und werden deshalb nicht fest geprüft, nur ob sie lesbar und plausibel sind.
LR_PROBEN = [("EDVE", "BRAUNSCHWEIG"), ("EDDH", "HAMBURG"), ("EDDM", "MÜNCHEN"), ("EDDF", "FRANKFURT")]
# Mindestanzahlen (2611: 1032 Lufträume, 837 Flugplätze, 376 Meldepunkte; CTR 62, TMA 154, R 186, RMZ 30, TMZ 55)
LR_MIN = {"lr": 700, "ad": 500, "dp": 250, "arten": {"CTR": 40, "TMA": 50, "R": 50, "RMZ": 10, "TMZ": 10}}


def pruefe_luftraum(pfad: str, jetzt: str | None = None) -> bool:
    import gzip as _gz
    import hashlib
    d = open(pfad, "rb").read()
    K = F.kopf_lesen(d, b"FCYL")
    Z = K.get("zyklen") or []
    ok = melde(len(Z) >= 1, f"{len(Z)} AIRAC-Zyklen: " + ", ".join(f"{z['zyklus']} ({z['ab'][:10]} – {z['bis'][:10]}, Stand {z['stand']})" for z in Z))
    t = (jetzt or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    ok &= melde(any(z["ab"] <= t < z["bis"] for z in Z), f"Zyklus für {t[:10]} enthalten")
    ok &= melde("open flightmaps" in K.get("quelle", ""), "Quellenangabe open flightmaps im Kopf")
    for z in Z:
        roh = d[z["ab_byte"]:z["ab_byte"] + z["bytes"]]
        if not melde(hashlib.sha256(roh).hexdigest() == z["sha256"], f"{z['zyklus']}: Prüfsumme des Inhalts ({z['bytes'] // 1024} kB gzip)"):
            ok = False
            continue
        I = json.loads(_gz.decompress(roh).decode("utf-8"))
        ok &= melde(I["zyklus"] == z["zyklus"] and I["ab"] == z["ab"] and I["bis"] == z["bis"], f"{z['zyklus']}: Kopf und Inhalt stimmen überein")
        lr, ad, dp, de = I["lr"], I["ad"], I["dp"], I["de"]
        ok &= melde(len(lr) >= LR_MIN["lr"], f"{z['zyklus']}: {len(lr)} Lufträume")
        ok &= melde(len(ad) >= LR_MIN["ad"], f"{z['zyklus']}: {len(ad)} Flugplätze")
        ok &= melde(len(dp) >= LR_MIN["dp"], f"{z['zyklus']}: {len(dp)} VFR-Meldepunkte")
        ok &= melde(len(de) >= 1, f"{z['zyklus']}: Umriss Deutschlands (vereinigte FIR) in {len(de)} Teil(en), {sum(len(x) // 2 for x in de)} Punkte")
        arten = {}
        for e in lr:
            arten[e["t"]] = arten.get(e["t"], 0) + 1
        ok &= melde(all(arten.get(a, 0) >= n for a, n in LR_MIN["arten"].items()),
                    f"{z['zyklus']}: Arten " + ", ".join(f"{a} {n}" for a, n in sorted(arten.items())))
        schlecht = []
        for e in lr:
            p = F.umriss_aus(e["p"])
            b = e["b"]
            if len(p) < 3 or not (200000 <= b[0] <= b[2] <= 1700000 and 4500000 <= b[1] <= b[3] <= 5700000):
                schlecht.append(e["n"]); continue
            for g in (e["u"], e["o"]):
                if not (isinstance(g, list) and len(g) == 3 and g[0] in ("ALT", "HEI", "STD") and g[2] in ("FT", "FL", "M")
                        and isinstance(g[1], (int, float)) and 0 <= g[1] <= 99999):
                    schlecht.append(e["n"]); break
        ok &= melde(not schlecht, f"{z['zyklus']}: Umrisse und Grenzen lesbar und in Mitteleuropa" + (f" — fehlerhaft: {schlecht[:8]}" if schlecht else ""))
        ok &= melde(all(len(x) == 6 and 45 <= x[3] <= 57 and 2 <= x[4] <= 17 for x in ad) and all(len(x) == 6 and 45 <= x[3] <= 57 and 2 <= x[4] <= 17 for x in dp),
                    f"{z['zyklus']}: Flugplätze und Meldepunkte mit Koordinaten in Mitteleuropa")
        D = [F.umriss_aus(p) for p in de]
        for icao, ctr in LR_PROBEN:
            a = next((x for x in ad if x[0] == icao), None)
            if a is None:
                ok &= melde(False, f"{z['zyklus']}: Flugplatz {icao} fehlt"); continue
            lat, lon = a[3], a[4]
            c = [e for e in lr if e["t"] == "CTR" and e["n"].upper().startswith(ctr) and im_umriss(lon, lat, F.umriss_aus(e["p"]))]
            ok &= melde(bool(c), f"{z['zyklus']}: {icao} ({lat:.3f} N, {lon:.3f} E) liegt in der CTR " + (", ".join(f"{e['n']} {e['u'][1]}–{e['o'][1]} {e['o'][2]} {e['o'][0]}" for e in c) or ctr + " — nicht gefunden"))
            ok &= melde(any(im_umriss(lon, lat, u) for u in D), f"{z['zyklus']}: {icao} liegt im Umriss Deutschlands")
            ok &= melde(any(x[5] == icao for x in dp) or icao in ("EDDF",), f"{z['zyklus']}: Meldepunkte zu {icao}: " + ", ".join(x[0] for x in dp if x[5] == icao)[:120], wichtig=False)
        aussen = [(n, la, lo) for n, la, lo in (("Zürich", 47.46, 8.55), ("Wien", 48.11, 16.57), ("Amsterdam", 52.31, 4.76), ("Prag", 50.10, 14.26))]
        ok &= melde(not any(im_umriss(lo, la, u) for _, la, lo in aussen for u in D), f"{z['zyklus']}: Zürich, Wien, Amsterdam, Prag liegen außerhalb des Umrisses")
    return ok


# Pisten: Proben mit bekannten Bahnen (Richtung, Länge in m ±60 m wie in der AIP gerundet, Belag)
PI_PROBEN = [("EDVE", "08", 80, 2300, "ASP"), ("EDVE", "26", 260, 2300, "ASP"), ("EDDH", "23", 230, 3250, "ASP"),
             ("EDDF", "18", 180, 4000, "CON"), ("EDVM", "07", 70, 1220, "ASP"), ("LOWI", "26", 260, 2000, "ASP")]
PI_MIN = {"plaetze": 25000, "richtungen": 50000, "ed": 300}


def pruefe_pisten(pfad: str) -> bool:
    import gzip as _gz
    import hashlib
    d = open(pfad, "rb").read()
    K = F.kopf_lesen(d, b"FCYR")
    ok = melde("OurAirports" in K.get("quelle", ""), f"Quelle {K.get('quelle')}, Stand {K.get('stand')}")
    ok &= melde(K["plaetze"] >= PI_MIN["plaetze"] and K["richtungen"] >= PI_MIN["richtungen"],
                f"{K['plaetze']} Plätze, {K['richtungen']} Richtungen in {len(K['gruppen'])} Gruppen")
    alle = {}
    for g, e in sorted(K["gruppen"].items()):
        roh = d[e["ab_byte"]:e["ab_byte"] + e["bytes"]]
        if hashlib.sha256(roh).hexdigest() != e["sha256"]:
            ok &= melde(False, f"Gruppe {g}: Prüfsumme"); continue
        I = json.loads(_gz.decompress(roh).decode("utf-8"))
        if len(I) != e["plaetze"] or not all(k[:1] == g for k in I):
            ok &= melde(False, f"Gruppe {g}: Inhalt passt nicht zum Kopf"); continue
        alle.update(I)
    ok &= melde(len(alle) == K["plaetze"], f"alle {len(K['gruppen'])} Gruppen lesbar, Prüfsummen stimmen")
    schlecht = [k for k, v in alle.items() for r in v
                if not (isinstance(r, list) and len(r) == 5 and isinstance(r[0], str) and isinstance(r[1], int) and 10 <= r[1] <= 360 and r[1] % 10 == 0
                        and (r[2] is None or 1 <= r[2] <= 10000) and (r[3] is None or 0 <= r[3] <= (r[2] or 0)) and isinstance(r[4], str))]
    ok &= melde(not schlecht, "jede Richtung mit Kennung, 10–360°, Länge bis 10 km (Wasserflächen), verfügbare Landestrecke ≤ Länge" + (f" — fehlerhaft: {schlecht[:8]}" if schlecht else ""))
    ed = [k for k in alle if k.startswith("ED") and alle[k]]
    ok &= melde(len(ed) >= PI_MIN["ed"], f"{len(ed)} Plätze in Deutschland (ED..) mit Pisten")
    for ic, rid, rdir, rlen, rsurf in PI_PROBEN:
        r = next((x for x in alle.get(ic, []) if x[0] == rid), None)
        ok &= melde(bool(r) and r[1] == rdir and r[2] is not None and abs(r[2] - rlen) <= 60 and r[4].startswith(rsurf),
                    f"{ic} {rid}: " + (f"{r[1]}°, {r[2]} m (verfügbar zur Landung {r[3]} m), {r[4]}" if r else "fehlt"))
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("art", choices=["wind", "gelaende", "orte", "luftraum", "pisten"])
    ap.add_argument("datei")
    ap.add_argument("--vergleich", action="store_true")
    ap.add_argument("--jetzt", help="Zeitpunkt (ISO, UTC) statt der aktuellen Zeit — für Tests")
    a = ap.parse_args(argv)
    ok = {"wind": lambda: pruefe_wind(a.datei, a.vergleich), "gelaende": lambda: pruefe_gelaende(a.datei),
          "orte": lambda: pruefe_orte(a.datei), "luftraum": lambda: pruefe_luftraum(a.datei, a.jetzt),
          "pisten": lambda: pruefe_pisten(a.datei)}[a.art]()
    zusammenfassung(f"Prüfung {a.art}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
