"""Höhenwind und Bodenwerte aus DWD ICON-D2 für den FlyCademy Flight Log.

Ablauf (GitHub Actions, alle 3 Stunden):
  1. neuesten vollständigen Lauf auf opendata.dwd.de suchen
  2. Höhen der Modellflächen (HHL, zeitunabhängig) laden und die Flächen für 0–14 000 ft auswählen
  3. je Vorhersageschritt (0–48 h, alle 3 h) u, v, t dieser Flächen laden, auf feste Höhen in ft MSL
     umrechnen (linear in der Höhe) und auf ein 0,1°-Gitter mitteln
  4. Bodenwerte (t_2m, td_2m, pmsl, u_10m, v_10m, vmax_10m) stündlich 0–48 h an jedem Flugplatz im Gebiet
     (nächster Modellpunkt; Temperatur mit 0,65 °C/100 m auf die Platzhöhe umgerechnet)
  5. wind.bin schreiben (Format: format.py)

Aufruf: python -m fcy_daten.wind --aus out/wind.bin [--lauf 2026102412] [--quelle URL] [--plaetze datei.csv]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys

import eccodes
import numpy as np

from . import format as F
from . import netz

QUELLE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
PLAETZE_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
HOEHEN_FT = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 10000, 12000, 14000]
SCHRITTE_H = list(range(0, 49))          # stündlich 0–48 h (Georgi 25.10.2026; vorher alle 3 h)
BODEN_SCHRITTE_H = list(range(0, 49))
BODEN_VARS = ["t_2m", "td_2m", "pmsl", "u_10m", "v_10m", "vmax_10m"]
GITTER_D = 0.1                 # Ausgabegitter in Grad
KT = 1.943844                  # m/s → kt
FT = 0.3048

_NAME = re.compile(r"icon-d2_germany_regular-lat-lon_(model-level|pressure-level|single-level|time-invariant)_(\d{10})_(\d{3})_(.+)\.grib2\.bz2$")


def zerlege(name: str):
    """Dateiname → (art, lauf, schritt, ebene|None, variable)."""
    m = _NAME.match(name)
    if not m:
        return None
    art, lauf, schritt, rest = m.group(1), m.group(2), int(m.group(3)), m.group(4).split("_")
    ebene = None
    if rest and rest[0].isdigit():
        ebene = int(rest.pop(0))
    while rest and rest[0] in ("2d", "3d"):
        rest.pop(0)
    return art, lauf, schritt, ebene, "_".join(rest).lower()


def grib_feld(daten: bytes):
    """GRIB2-Nachricht → (Array [nlat, nlon] Süd→Nord, West→Ost; Gitter-Dict)."""
    h = eccodes.codes_new_from_message(daten)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        la1 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees")
        la2 = eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
        lo1 = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees")
        lo2 = eccodes.codes_get(h, "longitudeOfLastGridPointInDegrees")
        di = eccodes.codes_get(h, "iDirectionIncrementInDegrees")
        dj = eccodes.codes_get(h, "jDirectionIncrementInDegrees")
        jpos = eccodes.codes_get(h, "jScansPositively")
        miss = eccodes.codes_get(h, "missingValue")
        bitmap = eccodes.codes_get(h, "bitmapPresent")
        v = eccodes.codes_get_values(h).astype(np.float32)
    finally:
        eccodes.codes_release(h)
    if bitmap:
        v[v == miss] = np.nan
    a = v.reshape(nj, ni)
    if lo1 > 180:
        lo1 -= 360
    if lo2 > 180:
        lo2 -= 360
    if not jpos:
        a = a[::-1]
        la1, la2 = la2, la1
    return a, {"lat0": round(la1, 4), "lon0": round(lo1, 4), "dlat": round(dj, 4), "dlon": round(di, 4), "nlat": nj, "nlon": ni}


class Quelle:
    def __init__(self, basis: str):
        self.basis = basis.rstrip("/")
        self._listen = {}

    def liste(self, hh: int, var: str) -> dict:
        key = (hh, var)
        if key not in self._listen:
            try:
                namen = netz.verzeichnis(f"{self.basis}/{hh:02d}/{var}/")
            except RuntimeError:
                namen = []
            d = {}
            for n in namen:
                z = zerlege(n)
                if z:
                    d[(z[0], z[1], z[2], z[3], z[4])] = n
            self._listen[key] = d
        return self._listen[key]

    def url(self, hh: int, var: str, name: str) -> str:
        return f"{self.basis}/{hh:02d}/{var}/{name}"


def lauf_finden(q: Quelle, jetzt: dt.datetime, art: str) -> str | None:
    """Neuester Lauf, für den u/v/t aller Schritte und alle Bodenwerte vollständig vorliegen."""
    basis = jetzt.replace(minute=0, second=0, microsecond=0)
    basis -= dt.timedelta(hours=basis.hour % 3)
    for k in range(0, 9):
        t = basis - dt.timedelta(hours=3 * k)
        lauf = t.strftime("%Y%m%d%H")
        hh = t.hour
        ok = True
        for var in ("u", "v", "t"):
            have = {(s, e) for (a, l, s, e, v) in q.liste(hh, var) if a == art and l == lauf and v == var}
            if not all(any(s == st for (s, _e) in have) for st in SCHRITTE_H):
                ok = False
                break
        if ok:
            for var in BODEN_VARS:
                have = {s for (a, l, s, e, v) in q.liste(hh, var) if l == lauf and v == var}
                if not all(st in have for st in BODEN_SCHRITTE_H if not (var == "vmax_10m" and st == 0)):
                    ok = False
                    break
        if ok:
            return lauf
    return None


def hhl_laden(q: Quelle, lauf: str, cache: str | None = None):
    """Höhen der Halbflächen (zeitunabhängig). Mit cache: einmal laden, danach aus der Datei (GitHub-Actions-Cache)."""
    if cache and os.path.exists(cache):
        z = np.load(cache, allow_pickle=False)
        return [int(e) for e in z["ebenen"]], z["hhl"], json.loads(str(z["gitter"]))   # int, nicht numpy.int64 (JSON-Kopf)
    e, h, g = _hhl_holen(q, lauf)
    if cache:
        os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
        np.savez_compressed(cache, ebenen=np.array(e), hhl=h, gitter=json.dumps(g))
    return e, h, g


def _hhl_holen(q: Quelle, lauf: str):
    hh = int(lauf[8:])
    for h in [hh] + [x for x in range(0, 24, 3) if x != hh]:
        L = q.liste(h, "hhl")
        eintr = sorted(((e, n) for (a, l, s, e, v), n in L.items() if v == "hhl" and e is not None), key=lambda x: x[0])
        if eintr:
            # pro Ebene den neuesten Lauf nehmen
            beste = {}
            for (a, l, s, e, v), n in L.items():
                if v == "hhl" and e is not None and (e not in beste or l > beste[e][0]):
                    beste[e] = (l, n)
            ebenen = sorted(beste)
            felder = netz.parallel(lambda e: grib_feld(netz.hole_bz2(q.url(h, "hhl", beste[e][1]))), ebenen)
            gitter = felder[0][1]
            return ebenen, np.stack([f[0] for f in felder]), gitter
    raise RuntimeError("HHL (Höhen der Modellflächen) nicht gefunden")


def ebenen_waehlen(hhl_ebenen, hhl):
    """Modellflächen (Vollflächen k zwischen Halbflächen k und k+1) für 0–14 000 ft auswählen.
    Rückgabe: Liste k (oben → unten), z_voll [len, nlat, nlon], Gelände [nlat, nlon]."""
    idx = {e: i for i, e in enumerate(hhl_ebenen)}
    unten = max(hhl_ebenen)                       # unterste Halbfläche = Erdoberfläche
    gelaende = hhl[idx[unten]]
    kand = [k for k in hhl_ebenen if k + 1 in idx]
    z = {k: 0.5 * (hhl[idx[k]] + hhl[idx[k + 1]]) for k in kand}
    ztop = HOEHEN_FT[-1] * FT + 200.0
    oben = [k for k in kand if np.nanmin(z[k]) >= ztop]
    k_top = max(oben) if oben else min(kand)
    folge = sorted(k for k in kand if k >= k_top)  # oben → unten (k wächst nach unten)
    # Abstand der gewählten Flächen: unter 1500 m höchstens 200 m, darüber höchstens 400 m (mittlere Höhe)
    gew = [folge[0]]
    for k in folge[1:]:
        zl, zk = float(np.nanmean(z[gew[-1]])), float(np.nanmean(z[k]))
        nxt = folge[folge.index(k) + 1] if folge.index(k) + 1 < len(folge) else None
        grenze = 200.0 if zk < 1500 else 400.0
        if nxt is None or zl - float(np.nanmean(z[nxt])) > grenze:
            gew.append(k)
    if folge[-1] not in gew:
        gew.append(folge[-1])
    return gew, np.stack([z[k] for k in gew]), gelaende


def interpol_gewichte(zv, gelaende):
    """Für jede Zielhöhe: oberer Index j, Gewicht w (Wert = w·f[j] + (1−w)·f[j+1]), Maske unter Gelände."""
    n = zv.shape[0]
    out = []
    for hft in HOEHEN_FT:
        A = hft * FT
        cnt = (zv >= A).sum(axis=0)                     # Flächen über der Zielhöhe (zv fällt mit dem Index)
        j = np.clip(cnt - 1, 0, n - 2)
        za = np.take_along_axis(zv, j[None], 0)[0]
        zb = np.take_along_axis(zv, (j + 1)[None], 0)[0]
        w = np.where(za > zb, (A - zb) / np.where(za > zb, za - zb, 1), 1.0)
        w = np.clip(w, 0.0, 1.0)
        unter_unterster = cnt >= n                     # Ziel unter der untersten Fläche, aber evtl. über Grund
        w = np.where(unter_unterster, 0.0, w)
        j = np.where(unter_unterster, n - 2, j)
        unter_grund = A < gelaende
        oben_raus = cnt == 0                          # über der obersten Fläche (sollte nicht vorkommen)
        out.append((j, w.astype(np.float32), unter_grund | oben_raus))
    return out


def box_mittel(a, gitter, d=GITTER_D, min_anteil=0.5):
    """a [..., nlat, nlon] (natives Gitter) → [..., nlat_out, nlon_out] auf Vielfachen von d, Mittel über ±d/2."""
    la0, lo0, dla, dlo, nla, nlo = gitter["lat0"], gitter["lon0"], gitter["dlat"], gitter["dlon"], gitter["nlat"], gitter["nlon"]
    i0 = int(np.ceil(round(la0 / d, 6))); i1 = int(np.floor(round((la0 + (nla - 1) * dla) / d, 6)))
    j0 = int(np.ceil(round(lo0 / d, 6))); j1 = int(np.floor(round((lo0 + (nlo - 1) * dlo) / d, 6)))
    lats = np.arange(i0, i1 + 1) * d
    lons = np.arange(j0, j1 + 1) * d
    ii = np.rint((lats - la0) / dla).astype(int)
    jj = np.rint((lons - lo0) / dlo).astype(int)
    hi, hj = int(round(d / 2 / dla)), int(round(d / 2 / dlo))
    valid = np.isfinite(a)
    a0 = np.where(valid, a, 0.0).astype(np.float64)
    c0 = valid.astype(np.float64)

    def csum(x):
        s = np.zeros(x.shape[:-2] + (x.shape[-2] + 1, x.shape[-1] + 1))
        s[..., 1:, 1:] = x.cumsum(-2).cumsum(-1)
        return s
    S, C = csum(a0), csum(c0)
    r0 = np.clip(ii - hi, 0, nla); r1 = np.clip(ii + hi + 1, 0, nla)
    q0 = np.clip(jj - hj, 0, nlo); q1 = np.clip(jj + hj + 1, 0, nlo)
    R0, Q0 = np.meshgrid(r0, q0, indexing="ij"); R1, Q1 = np.meshgrid(r1, q1, indexing="ij")
    def box(T):
        return T[..., R1, Q1] - T[..., R0, Q1] - T[..., R1, Q0] + T[..., R0, Q0]
    s, c = box(S), box(C)
    voll = (R1 - R0) * (Q1 - Q0)
    m = np.where(c >= min_anteil * voll, s / np.maximum(c, 1), np.nan)
    return m.astype(np.float32), {"lat0": round(float(lats[0]), 4), "lon0": round(float(lons[0]), 4), "d": d,
                                  "nlat": len(lats), "nlon": len(lons)}


def plaetze_laden(text: str, gitter):
    la0, lo0 = gitter["lat0"], gitter["lon0"]
    la1 = la0 + (gitter["nlat"] - 1) * gitter["dlat"]; lo1 = lo0 + (gitter["nlon"] - 1) * gitter["dlon"]
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("type") not in ("small_airport", "medium_airport", "large_airport"):
            continue
        code = ""
        for k in ("icao_code", "gps_code", "ident"):
            c = (r.get(k) or "").strip().upper()
            if re.fullmatch(r"[A-Z]{4}", c):
                code = c
                break
        if not code:
            continue
        try:
            la, lo = float(r["latitude_deg"]), float(r["longitude_deg"])
        except (TypeError, ValueError):
            continue
        if not (la0 <= la <= la1 and lo0 <= lo <= lo1):
            continue
        try:
            elev = float(r.get("elevation_ft") or "nan") * FT
        except ValueError:
            elev = float("nan")
        # bei doppelten Codes den größeren Platz behalten
        rang = {"large_airport": 3, "medium_airport": 2, "small_airport": 1}[r["type"]]
        if code not in out or rang > out[code][3]:
            out[code] = (la, lo, elev, rang)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--quelle", default=QUELLE)
    ap.add_argument("--lauf", help="YYYYMMDDHH (sonst neuester vollständiger)")
    ap.add_argument("--jetzt", help="UTC-Zeit für die Laufsuche, ISO (für Tests)")
    ap.add_argument("--plaetze", help="airports.csv lokal (sonst OurAirports)")
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--hhl-cache", help="Datei für die zeitunabhängigen Flächenhöhen (npz)")
    a = ap.parse_args(argv)

    q = Quelle(a.quelle)
    jetzt = dt.datetime.fromisoformat(a.jetzt) if a.jetzt else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    art = "model-level"
    lauf = a.lauf or lauf_finden(q, jetzt, art)
    if not lauf:
        print("Kein vollständiger ICON-D2-Lauf gefunden — nichts geschrieben.", file=sys.stderr)
        return 2
    hh = int(lauf[8:])
    print(f"Lauf {lauf}", flush=True)

    hhl_e, hhl, g_nat = hhl_laden(q, lauf, a.hhl_cache)
    ebenen, zv, gelaende = ebenen_waehlen(hhl_e, hhl)
    print(f"Modellflächen: {ebenen} (Höhe Mittel {float(np.nanmean(zv[0])):.0f} … {float(np.nanmean(zv[-1])):.0f} m)", flush=True)
    gew = interpol_gewichte(zv, gelaende)

    def namen(var):
        return {(s, e): n for (ar, l, s, e, v), n in q.liste(hh, var).items() if ar == art and l == lauf and v == var}
    nm = {v: namen(v) for v in ("u", "v", "t")}

    U = V = T = None
    gout = None
    for si, st in enumerate(SCHRITTE_H):
        jobs = [(v, e) for v in ("u", "v", "t") for e in ebenen]
        def lade(job):
            v, e = job
            n = nm[v].get((st, e))
            if not n:
                raise RuntimeError(f"fehlt: {v} Fläche {e} Schritt {st}")
            return grib_feld(netz.hole_bz2(q.url(hh, v, n)))[0]
        felder = netz.parallel(lade, jobs, threads=a.threads)
        f = {"u": np.stack(felder[0:len(ebenen)]), "v": np.stack(felder[len(ebenen):2 * len(ebenen)]),
             "t": np.stack(felder[2 * len(ebenen):])}
        res = {}
        for var in ("u", "v", "t"):
            lst = []
            for (j, w, maske) in gew:
                fa = np.take_along_axis(f[var], j[None], 0)[0]
                fb = np.take_along_axis(f[var], (j + 1)[None], 0)[0]
                x = w * fa + (1 - w) * fb
                x[maske] = np.nan
                lst.append(x)
            res[var] = np.stack(lst)              # hoehe, nlat, nlon
        um, gout = box_mittel(res["u"], g_nat)
        vm, _ = box_mittel(res["v"], g_nat)
        tm, _ = box_mittel(res["t"], g_nat)
        if U is None:
            shp = (len(SCHRITTE_H),) + um.shape
            U, V, T = (np.full(shp, np.nan, np.float32) for _ in range(3))
        U[si], V[si], T[si] = um * KT, vm * KT, tm - 273.15
        print(f"  Schritt +{st:02d} h", flush=True)

    # Bodenwerte an den Plätzen
    txt = open(a.plaetze, encoding="utf-8").read() if a.plaetze else netz.hole(PLAETZE_URL).decode("utf-8")
    pl = plaetze_laden(txt, g_nat)
    codes = sorted(pl)
    ii = np.array([int(round((pl[c][0] - g_nat["lat0"]) / g_nat["dlat"])) for c in codes], dtype=int)
    jj = np.array([int(round((pl[c][1] - g_nat["lon0"]) / g_nat["dlon"])) for c in codes], dtype=int)
    hmod = gelaende[ii, jj] if len(codes) else np.array([])
    helev = np.array([pl[c][2] for c in codes], dtype=float)
    korr = np.where(np.isfinite(helev), 0.0065 * (hmod - helev), 0.0)
    B = np.full((len(codes), len(BODEN_SCHRITTE_H), 6), np.nan, np.float32)
    for vi, var in enumerate(BODEN_VARS):
        L = {s: n for (ar, l, s, e, v), n in q.liste(hh, var).items() if l == lauf and v == var}
        def lade_b(st):
            n = L.get(st)
            if not n:
                return None
            return grib_feld(netz.hole_bz2(q.url(hh, var, n)))[0]
        felder = netz.parallel(lade_b, BODEN_SCHRITTE_H, threads=a.threads)
        for si, fe in enumerate(felder):
            if fe is None or not len(codes):
                continue
            x = fe[ii, jj].astype(float)
            if var in ("t_2m", "td_2m"):
                x = x - 273.15 + korr
            elif var == "pmsl":
                x = x / 100.0
            else:
                x = x * KT
            B[:, si, vi] = x
    plaetze = [(c, B[n]) for n, c in enumerate(codes)]

    lauf_iso = f"{lauf[:4]}-{lauf[4:6]}-{lauf[6:8]}T{lauf[8:]}:00:00Z"
    kopf = {"modell": "ICON-D2", "lauf": lauf_iso,
            "erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "quelle": "Deutscher Wetterdienst (DWD), ICON-D2", "hoehen_ft": HOEHEN_FT, "hoehe": "MSL",
            "schritte_h": SCHRITTE_H, "boden_schritte_h": BODEN_SCHRITTE_H, "gitter": gout,
            "modellflaechen": ebenen, "natives_gitter": g_nat}
    k = F.schreibe_wind(a.aus, kopf, U, V, T, plaetze)
    print(f"geschrieben: {a.aus} · Gitter {gout['nlat']}×{gout['nlon']} · {len(plaetze)} Plätze", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
