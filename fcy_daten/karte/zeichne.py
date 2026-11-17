"""ICAO-Optik für ganz Deutschland zeichnen: je Zoomstufe einmal die ganze Szene aufbauen (Zeichen, Linien, Flächen und alle
Beschriftungen mit demselben Platztest wie die Übungskarte der Theorie, karte_12.py Entwurf 2.0), dann Block für Block zeichnen
und in Kacheln schneiden. Eine Beschriftung an einer Blockgrenze steht so in beiden Blöcken an genau derselben Stelle.

Maßstab wie in der Zwischenstufe Harz–Elbe (kacheln_v5.py): 1 pt der Übungskarte = PXPT CSS-Bildpunkte je Zoomstufe; Längen
der Übungskarte in „Kartenmetern“ (1 : 500 000) bleiben Papiermaße. Außerhalb Deutschlands bleiben die Kacheln durchsichtig.

Aufruf: python -m fcy_daten.karte.zeichne --arbeit <Ordner> --zyklus 2611 --aus <Kachelordner> [--zoom 8 12] [--gebiet lon0 lat0 lon1 lat1]
        [--prozesse 4]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pickle
import re
import sys
import time

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection, PatchCollection  # noqa: E402
from matplotlib.patches import Circle, PathPatch, Polygon as MPoly, Rectangle  # noqa: E402
from matplotlib.path import Path  # noqa: E402
from matplotlib.transforms import IdentityTransform  # noqa: E402
import shapely  # noqa: E402
from shapely.affinity import scale as sk_scale  # noqa: E402
from shapely.geometry import Point, Polygon, box  # noqa: E402
from shapely.prepared import prep  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from .gelaende import E, res  # noqa: E402

plt.rcParams["font.family"] = ["Nimbus Sans", "DejaVu Sans"]
plt.rcParams["hatch.linewidth"] = 0.6
SCHMAL = ["Nimbus Sans Narrow", "DejaVu Sans"]
PT = 500000.0 * 0.0254 / 72                     # 1 pt der Übungskarte in Kartenmetern
PXPT = {8: 0.95, 9: 1.2, 10: 1.7, 11: 2.15, 12: 2.6}
SCALES = {8: [1], 9: [1], 10: [1, 2], 11: [1, 2], 12: [1, 2]}
BLOCK_PX = 2048
# Farben wie die Übungskarte (karte_12.py, an der deutschen ICAO-Karte gemessen)
FL_BLAU, C_BLAU, C_BAND, CTR_FUELL, E_BLAU = "#2a35c8", "#2f45c0", "#7f98e6", "#e1496e", "#3a49b8"
E_LILA, R_ROT, PJA_ROT, HIND, MEF_F = "#333333", "#c8283c", "#e4304a", "#2a35c8", "#ec6490"
ORT_GELB, ORT_RAND, STR_ROT, WALD, WASSER, WASSER_L, TMZ_GRAU = "#ffd21e", "#4a3c14", "#ee1c1c", "#bdeb8b", "#bfe9f8", "#22a9dc", "#4a4a4a"
STUFEN = [-1000, 500, 1000, 1500, 2000, 3000, 5000]
FARBEN = ["#ffffff", "#f7f1d8", "#efe2b6", "#e5cf93", "#d9b977", "#c99f5c"]
WALD_ALPHA = 0.55
ZEIT_HX = ("HX", "TIMSH")
STIL_BAHN = {"color": "#111", "linewidth": 0.95, "capstyle": "butt"}
STIL_STRICH = {"color": "#111", "linewidth": 0.85, "capstyle": "butt"}
STIL_WALD = {"facecolor": WALD, "edgecolor": "none", "alpha": WALD_ALPHA}
STIL_ORT = {"facecolor": ORT_GELB, "edgecolor": ORT_RAND, "linewidth": 0.3}
STIL_WASSER = {"facecolor": WASSER, "edgecolor": WASSER_L, "linewidth": 0.35}
STIL_FLUSS1 = {"color": WASSER_L, "linewidth": 0.8}
STIL_FLUSS2 = {"color": WASSER_L, "linewidth": 0.45}
STIL_S1305 = {"color": STR_ROT, "linewidth": 0.55}
STIL_S1303A, STIL_S1303B = {"color": STR_ROT, "linewidth": 1.55}, {"color": "white", "linewidth": 0.55}
STIL_S1301A, STIL_S1301B = {"color": STR_ROT, "linewidth": 3.0}, {"color": "white", "linewidth": 1.3}
NICHT_ORT = re.compile(r"gewerbe|industrie|hafen|gebiet|park|siedlung|landkreis", re.I)
OHNE_DME = {"BWG", "LND", "LLD"}
BROCKEN_M = (1181734.3, 6763881.4)            # 10,6157° E, 51,7991° N in Web-Mercator (wie karte_12.py)


# =====================================================================================================================
# Textmaße (pt) — einmal je Text, Schrift und Größe; die Lage folgt aus der Ausrichtung
# =====================================================================================================================
_MDPI = 720                                   # hoch messen: bei 72 dpi rundet das Hinting je nach Umgebung anders (Job 20,0 statt 21,7 pt)
_MF = plt.figure(figsize=(2, 2), dpi=_MDPI)
_MR = _MF.canvas.get_renderer()
_MC: dict = {}


def mass(txt, fs, **kw):
    """→ (Breite, Höhe) in pt, gemessen wie get_window_extent (ohne Halo und Kasten)."""
    k = (txt, fs, kw.get("fontfamily") and tuple(kw["fontfamily"]) if isinstance(kw.get("fontfamily"), list) else kw.get("fontfamily"),
         kw.get("weight"), kw.get("style"), kw.get("linespacing"))
    v = _MC.get(k)
    if v is None:
        t = _MF.text(0, 0, txt, fontsize=fs, transform=IdentityTransform(), ha="left", va="bottom",
                     **{a: b for a, b in kw.items() if a in ("fontfamily", "weight", "style", "linespacing")})
        bb = t.get_window_extent(renderer=_MR)
        v = (bb.width * 72 / _MDPI, bb.height * 72 / _MDPI); t.remove(); _MC[k] = v
    return v


def textbox(x, y, txt, fs, ha, va, rand=0.6, **kw):
    w, h = mass(txt, fs, **kw)
    w, h = w * PT, h * PT
    xa = x - w / 2 if ha == "center" else x - w if ha == "right" else x
    ya = y - h / 2 if va == "center" else y - h if va == "top" else y
    return (xa - rand * PT, ya - rand * PT, xa + w + rand * PT, ya + h + rand * PT)


# =====================================================================================================================
# Belegung (Platztest) mit Gitterindex
# =====================================================================================================================
class Belegt:
    def __init__(self, zelle):
        self.c = zelle; self.g: dict = {}; self.n = 0

    def _zellen(self, b):
        c = self.c
        for i in range(int(math.floor(b[0] / c)), int(math.floor(b[2] / c)) + 1):
            for j in range(int(math.floor(b[1] / c)), int(math.floor(b[3] / c)) + 1):
                yield (i, j)

    def add(self, b):
        self.n += 1
        for k in self._zellen(b):
            self.g.setdefault(k, []).append(b)

    def kandidaten(self, b):
        s = set()
        for k in self._zellen(b):
            for o in self.g.get(k, ()):
                s.add(o)
        return s

    def frei(self, b):
        for o in self.kandidaten(b):
            if o[0] < b[2] and b[0] < o[2] and o[1] < b[3] and b[1] < o[3]:
                return False
        return True

    def ueberdeckung(self, b):
        a = 0.0
        for o in self.kandidaten(b):
            w = min(o[2], b[2]) - max(o[0], b[0]); h = min(o[3], b[3]) - max(o[1], b[1])
            if w > 0 and h > 0:
                a += w * h
        return a


# =====================================================================================================================
# Szene: Liste von Zeichenbefehlen mit Umriss (Kartenmeter) und Ebene
# =====================================================================================================================
class Szene:
    def __init__(self):
        self.ops = []     # (zorder, nr, art, daten, bbox)

    def add(self, z, art, daten, bb):
        self.ops.append((float(z), len(self.ops), art, daten, tuple(float(v) for v in bb)))


def _pe(halo):
    return [pe.withStroke(linewidth=a, foreground=b) for a, b in halo] if halo else []


def _rand(lw):
    return (lw or 1.0) * PT


class Karte:
    """Baut die Szene einer Zoomstufe (Port von karte_12.py mit der Dichte je Zoomstufe aus kacheln_v5.py)."""

    def __init__(self, z, D, gebiet=None):
        self.z = z; self.D = D
        self.SK = res(z) * PXPT[z] / PT
        self.f = 1.0 / self.SK
        self.S = Szene()
        de = D["de"]
        if gebiet is not None:
            de = de.intersection(gebiet)
        self.DE = sk_scale(de, self.f, self.f, origin=(0, 0))
        self.INNEN = self.DE.buffer(-1500)
        self.INNEN_P = prep(self.INNEN)
        self.INNEN2 = self.INNEN.buffer(-2500)
        self.B = Belegt(60 * PT)
        self.gebiet_m = gebiet
        self.px = PT / PXPT[z]                         # Kartenmeter je CSS-Bildpunkt
        self.tol = 0.35 * self.px                      # Vereinfachung: 0,35 Bildpunkte
        self.amin = (1.0 * self.px) ** 2               # kleinere Flächen fallen weg (unter 1 Bildpunkt)

    def vec(self, arr, flaeche=False):
        """Geometrien (Web-Mercator) → Kartenmeter, vereinfacht; Rückgabe (Indizes, Geometrien)"""
        idx = np.arange(len(arr))
        if self.gebiet_m is not None and len(arr):
            m = shapely.intersects(arr, self.gebiet_m); idx = idx[m]; arr = arr[m]
        if not len(arr):
            return idx, arr
        g = shapely.transform(arr, lambda xy: xy * self.f)
        g = shapely.simplify(g, self.tol, preserve_topology=True)
        ok = ~shapely.is_empty(g)
        if flaeche:
            ok &= shapely.area(g) >= self.amin
        return idx[ok], g[ok]

    # ---------- Hilfen ----------
    def u(self, g):
        return sk_scale(g, self.f, self.f, origin=(0, 0))

    def pu(self, x, y):
        return x * self.f, y * self.f

    def lat(self, y_u):
        return math.degrees(2 * math.atan(math.exp(y_u * self.SK / 6378137.0)) - math.pi / 2)

    def gmf(self, y_u):
        """Kartenmeter je Meter im Gelände an der Breite von y_u"""
        return self.f / math.cos(math.radians(self.lat(y_u)))

    def km2(self, g):
        return g.area * self.SK ** 2 * math.cos(math.radians(self.lat(g.centroid.y))) ** 2 / 1e6

    def innen(self, b):
        return self.INNEN_P.contains(box(*b))

    def text(self, x, y, s, fs, z, ha="left", va="baseline", halo=None, bbox=None, rotation=0, **kw):
        d = dict(x=x, y=y, s=s, fontsize=fs, ha=ha, va=va if va != "baseline" else "baseline", zorder=z, rotation=rotation,
                 halo=halo, bbox=bbox, kw=kw)
        bb = textbox(x, y, s, fs, ha, "center" if va == "baseline" else va, rand=0, **kw)
        m = max(PT * (max([a for a, _ in (halo or [(0, 0)])]) + 2), (fs * PT * 0.6 if bbox else 0))
        if rotation:
            r = max(bb[2] - bb[0], bb[3] - bb[1])
            bb = (x - r, y - r, x + r, y + r)
        self.S.add(z, "text", d, (bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m))

    def setze(self, x, y, txt, fs, versuche=((1, 1), (1, -1), (-1, 1), (-1, -1), (0, 1.4), (0, -1.4), (1.6, 0), (-1.6, 0)),
              abstand=1.0, pflicht=True, z=8, halo=None, bbox=None, **kw):
        best = None
        for dx, dy in versuche:
            ha = "left" if dx > 0 else "right" if dx < 0 else "center"
            va = "bottom" if dy > 0 else "top" if dy < 0 else "center"
            px_, py_ = x + dx * abstand * fs * PT, y + dy * abstand * fs * PT
            b = textbox(px_, py_, txt, fs, ha, va, **kw)
            if self.innen(b) and self.B.frei(b):
                self.B.add(b); self.text(px_, py_, txt, fs, z, ha, va, halo, bbox, **kw)
                return {"x": px_, "y": py_, "ha": ha, "va": va, "box": b}
            if pflicht:
                ib = box(*b)
                wert = (0 if self.innen(b) else 1, ib.difference(self.INNEN).area if not self.innen(b) else 0.0, self.B.ueberdeckung(b))
                if best is None or wert < best[0]:
                    best = (wert, px_, py_, ha, va, b)
        if not pflicht:
            return None
        _, px_, py_, ha, va, b = best
        self.B.add(b); self.text(px_, py_, txt, fs, z, ha, va, halo, bbox, **kw)
        return {"x": px_, "y": py_, "ha": ha, "va": va, "box": b}

    def flaeche(self, g, z, stil):
        for q in getattr(g, "geoms", [g]):
            if q.geom_type == "Polygon" and not q.is_empty and len(q.exterior.coords) > 3:
                r = _rand(stil.get("linewidth")) if stil.get("linewidth") else 0.0
                x0, y0, x1, y1 = q.bounds
                self.S.add(z, "flaeche", (q, stil), (x0 - r, y0 - r, x1 + r, y1 + r))

    def linie(self, coords, z, stil):
        a = np.asarray(coords, dtype=float)
        if len(a) < 2:
            return
        r = _rand(stil.get("linewidth", 1.0)) * 1.5
        self.S.add(z, "linie", (a, stil), (a[:, 0].min() - r, a[:, 1].min() - r, a[:, 0].max() + r, a[:, 1].max() + r))

    def patch(self, art, daten, z, stil, bb):
        self.S.add(z, "patch", (art, daten, stil), bb)

    def plot(self, xs, ys, z, stil):
        xs, ys = np.atleast_1d(xs).astype(float), np.atleast_1d(ys).astype(float)
        r = (stil.get("ms", 0) / 2 + stil.get("lw", 1) + 1) * PT
        self.S.add(z, "plot", (xs, ys, stil), (xs.min() - r, ys.min() - r, xs.max() + r, ys.max() + r))

    # =================================================================================================================
    def baue(self):
        z, D = self.z, self.D
        t0 = time.time()
        self.topografie()
        self.vorbelegen()
        self.luftraeume()
        if z >= 10:
            self.hindernisse()
        self.funkfeuer()
        self.flugplaetze()
        if z >= 10:
            self.meldepunkte()
        self.orte()
        if z >= 10:
            self.hoehenpunkte()
        self.isogonen()
        self.mef()
        self.gradnetz()
        print(f"  z{z}: Szene {len(self.S.ops)} Befehle, {self.B.n} Beschriftungen/Belegungen, {time.time() - t0:.0f} s", flush=True)
        return self.S

    def _im(self, g):
        if self.gebiet_m is None:
            return True
        return g.intersects(self.gebiet_m)

    # ---------- Topografie ----------
    def topografie(self):
        z, A = self.z, self.D["arr"]
        for g in self.vec(A["wald"], True)[1]:
            self.flaeche(g, 0.3, STIL_WALD)
        io, go = self.vec(A["orte"], True)
        self.orte_u = [(g, A["orte_n"][k]) for k, g in zip(io, go)]
        for g in go:
            self.flaeche(g, 3, STIL_ORT)
        for g in self.vec(A["wasser"], True)[1]:
            self.flaeche(g, 4, STIL_WASSER)
        i_, g_ = self.vec(A["fluesse"])
        for k, g in zip(i_, g_):
            self.linie(shapely.get_coordinates(g), 4, STIL_FLUSS1 if A["fluesse_w"][k] == "1310" else STIL_FLUSS2)
        self.fluesse_u = [(g, A["fluesse_w"][k], A["fluesse_n"][k]) for k, g in zip(i_, g_)]
        i_, g_ = self.vec(A["strassen"])
        self.strassen_u = []
        for k, g in zip(i_, g_):
            wdm = A["strassen_w"][k]; c = shapely.get_coordinates(g)
            if wdm == "1305" and z >= 10:
                self.linie(c, 4.8, STIL_S1305)
            elif wdm == "1303":
                self.linie(c, 5, STIL_S1303A); self.linie(c, 5.05, STIL_S1303B)
            elif wdm == "1301":
                self.linie(c, 5.1, STIL_S1301A); self.linie(c, 5.15, STIL_S1301B)
                self.strassen_u.append((g, A["strassen_b"][k]))
        # Dörfer (Punkte) ab Zoom 10
        T = self.D["topo"]
        self.doerfer = [(Point(p.x * self.f, p.y * self.f), n) for p, n in T["doerfer"] if self._im(p)] if z >= 10 else []
        for g, n in self.doerfer:
            self.plot([g.x], [g.y], 3.2, {"marker": "o", "ms": math.sqrt(7.5), "mfc": ORT_GELB, "mec": "#2a2a2a", "mew": 0.45, "ls": "none"})
        # Eisenbahn
        bahn = {k: list(self.vec(A["bahn_" + k])[1]) for k in ("ein", "mehr", "still")}
        for q in bahn["ein"] + bahn["mehr"]:
            self.linie(np.asarray(q.coords)[:, :2], 5, STIL_BAHN)
        if z >= 10:
            for q in bahn["still"]:
                self.linie(np.asarray(q.coords)[:, :2], 5, {"color": "#111", "linewidth": 0.9, "linestyle": (0, (3.2, 1.8))})
            B_ABST, B_HALB, B_DOP = 26 * PT, 1.9 * PT, 1.7 * PT
            for liste, doppelt in ((bahn["ein"], False), (bahn["mehr"], True)):
                for q in liste:
                    L_ = q.length
                    for d in (np.arange(B_ABST / 2, L_, B_ABST) if L_ >= B_ABST / 2 else [L_ / 2]):
                        a_, b_ = q.interpolate(max(d - 60, 0)), q.interpolate(min(d + 60, L_)); c_ = q.interpolate(d)
                        tx, ty = b_.x - a_.x, b_.y - a_.y; nn = math.hypot(tx, ty) or 1.0; tx, ty = tx / nn, ty / nn
                        for o_ in ((-B_DOP / 2, B_DOP / 2) if doppelt else (0,)):
                            mx, my = c_.x + o_ * tx, c_.y + o_ * ty
                            self.linie([(mx - B_HALB * ty, my + B_HALB * tx), (mx + B_HALB * ty, my - B_HALB * tx)], 5.01, STIL_STRICH)
            alle = bahn["ein"] + bahn["mehr"]
            if alle:
                baum = STRtree(alle)
                for p in T["bahnhoefe"]:
                    if not self._im(p):
                        continue
                    g = Point(p.x * self.f, p.y * self.f)
                    if not self.INNEN_P.contains(g):
                        continue
                    i = baum.nearest(g); q = alle[i]
                    if q.distance(g) > 400:
                        continue
                    d = q.project(g); c_ = q.interpolate(d); a_, b_ = q.interpolate(max(d - 80, 0)), q.interpolate(min(d + 80, q.length))
                    tx, ty = b_.x - a_.x, b_.y - a_.y; nn = math.hypot(tx, ty) or 1.0; tx, ty = tx / nn, ty / nn
                    hl, hb = 1.9 * PT, 1.05 * PT
                    pts = [(c_.x + sx * hl * tx - sy * hb * ty, c_.y + sx * hl * ty + sy * hb * tx) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                    xs = [a for a, _ in pts]; ys = [b for _, b in pts]
                    self.patch("poly", pts, 5.02, {"fc": "#111", "ec": "none"}, (min(xs), min(ys), max(xs), max(ys)))
        # Autobahnnummern: je Autobahn und 30′-Feld ein Schild am längsten Stück
        best = {}
        for g, bez in self.strassen_u:
            if not bez or g.length <= 6000:
                continue
            m = g.interpolate(0.5, normalized=True)
            lon_, lat_ = (m.x * self.SK / 6378137.0) * 180 / math.pi, self.lat(m.y)
            k = (bez, math.floor(lon_ * 2), math.floor(lat_ * 2))
            if k not in best or g.length > best[k][0]:
                best[k] = (g.length, m)
        for (bez, _, _), (_, m) in sorted(best.items()):
            if self.INNEN_P.contains(m):
                self.text(m.x, m.y, bez, 5.6, 8, "center", "center", halo=[(1.8, "white")], color=STR_ROT, weight="bold", fontfamily=SCHMAL)
                self.B.add(textbox(m.x, m.y, bez, 5.2, "center", "center", rand=0))
        # Gewässernamen: je Fluss (Gewässer I. Ordnung) und 30′-Feld am längsten Stück
        fl = {}
        for g, wdm, n in self.fluesse_u:
            if wdm != "1310" or not n:
                continue
            m = g.interpolate(0.5, normalized=True)
            lon_, lat_ = (m.x * self.SK / 6378137.0) * 180 / math.pi, self.lat(m.y)
            k = (n, math.floor(lon_ * 2), math.floor(lat_ * 2))
            if k not in fl or g.length > fl[k][0]:
                fl[k] = (g.length, m)
        for (n, _, _), (_, m) in sorted(fl.items(), key=lambda e: -e[1][0]):
            self.setze(m.x, m.y, n, 6.0, versuche=((0.6, 0.6), (-0.6, 0.6)), pflicht=False, z=8, color=WASSER_L, style="italic")

    # ---------- Zeichen vorab belegen ----------
    def vorbelegen(self):
        P = self.D["plaetze_sicht"]
        for q in P:
            x, y = self.pu(q["x"], q["y"]); self.B.add((x - 1700, y - 1700, x + 1700, y + 1700))
        if self.z >= 10:
            for m in self.D["L"]["meldepunkte"]:
                x, y = self.pu(m["x"], m["y"]); self.B.add((x - 700, y - 700, x + 700, y + 800))
        for e in self.D["L"]["funkfeuer"]:
            if e["art"] in ("VOR", "NDB"):
                x, y = self.pu(e["x"], e["y"]); self.B.add((x - 1800, y - 1800, x + 1800, y + 1800))
        for g, p in self.D["L"]["luftraeume"]:
            if p.get("typ") == "A" and p.get("lokal") in ("PJA", "ACR") and self._im(g):
                c = self.u(g).centroid; self.B.add((c.x - 2700, c.y - 2700, c.x + 2700, c.y + 2700))

    # ---------- Lufträume ----------
    @staticmethod
    def fl(g):
        if not g:
            return ""
        w, e, b = float(g.get("wert")), (g.get("einheit") or "").upper(), (g.get("bezug") or "").upper()
        if b == "SFC" and w == 0:
            return "GND"
        if b == "STD" or e == "FL":
            return f"FL {int(w)}"
        return f"{int(w)} AGL" if b == "SFC" else f"{int(w)}"

    def band(self, g, breite, z, stil):
        b = g.difference(g.buffer(-breite)) if g.area > (breite * 3) ** 2 else g
        self.flaeche(b, z, stil)

    def umriss(self, g, farbe, lw, ls="solid", z=7):
        for q in getattr(g, "geoms", [g]):
            if q.geom_type == "Polygon":
                self.linie(np.asarray(q.exterior.coords)[:, :2], z, {"color": farbe, "linewidth": lw, "linestyle": ls})

    def kasten(self, g, klasse, ob, un, farbe, kopf=None, rahmen=True, fs=5.9):
        z = self.z
        if z <= 9 and klasse not in ("C", "D") and not str(kopf or "").startswith(("ED-R", "ED-P")):
            return
        ziel = g.intersection(self.INNEN2)
        if ziel.is_empty:
            return
        G = 1500 * PT / PXPT[z]                       # weitere Kästen in großen Lufträumen, etwa alle 1500 CSS-Bildpunkte
        punkte = [(ziel.representative_point(), True)]
        if ziel.area > 4 * G * G:
            x0, y0, x1, y1 = ziel.bounds
            for gx in np.arange(math.floor(x0 / G) * G, x1, G):
                for gy in np.arange(math.floor(y0 / G) * G, y1, G):
                    t = ziel.intersection(box(gx, gy, gx + G, gy + G))
                    if not t.is_empty and t.area > 0.3 * G * G and not t.contains(punkte[0][0]):
                        punkte.append((t.representative_point(), False))
        zh = fs * 1.18 * PT; fk = fs * 1.35 if not klasse or len(klasse) == 1 else fs * 1.08
        wk = (len(klasse) * fk * 0.62 * PT + 0.5 * fs * PT) if klasse else 0
        wl = max(len(ob), len(un), len(kopf or "")) * fs * 0.50 * PT + 0.7 * fs * PT
        zeilen = 2 + (1 if kopf else 0); w, h = wk + wl, zeilen * zh + 0.35 * fs * PT
        for p, pflicht in punkte:
            bb = None
            for dx, dy in ((0, 0), (0, 5000), (0, -5000), (6000, 0), (-6000, 0), (6000, 6000), (-6000, -6000), (0, 10000), (0, -10000)):
                b = (p.x + dx - w / 2, p.y + dy - h / 2, p.x + dx + w / 2, p.y + dy + h / 2)
                if self.innen(b) and self.B.frei(b):
                    bb = b; break
            if bb is None:
                if not pflicht:
                    continue
                bb = b
            self.B.add(bb); x, y = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            xa, ya = bb[0], bb[1]
            halo = None if rahmen else [(2.0, "white")]
            if rahmen:
                self.patch("rect", (xa, ya, w, h), 9, {"fc": "white", "ec": farbe, "lw": 0.8}, bb)
            if klasse:
                self.text(xa + wk / 2, y, klasse, fk, 9.1, "center", "center", color=farbe, weight="bold", fontfamily=SCHMAL)
                if rahmen:
                    self.plot([xa + wk, xa + wk], [ya, ya + h], 9.1, {"color": farbe, "lw": 0.6})
            xl = xa + wk + wl / 2; yt = ya + h - 0.175 * fs * PT
            zt = ([kopf] if kopf else []) + [ob, un]
            for i, tx in enumerate(zt):
                self.text(xl, yt - (i + 0.5) * zh, tx, fs, 9.1, "center", "center", halo=halo, color=farbe, weight="bold", fontfamily=SCHMAL)
            yb = yt - (len(zt) - 1) * zh
            self.plot([xl - wl / 2 + 0.25 * fs * PT, xl + wl / 2 - 0.25 * fs * PT], [yb, yb], 9.1, {"color": farbe, "lw": 0.6})

    def fallschirm(self, x, y, r, ry=None):
        ry = r if ry is None else ry
        for i_, (w1, w2) in enumerate(((0, 36), (36, 72), (72, 108), (108, 144), (144, 180))):
            ww = np.radians(np.linspace(w1, w2, 12))
            pts = [(x, y + 0.15 * ry)] + [(x + r * math.cos(w), y + 0.15 * ry + ry * math.sin(w)) for w in ww]
            self.patch("poly", pts, 9.2, {"fc": PJA_ROT if i_ % 2 == 0 else "white", "ec": PJA_ROT, "lw": 0.4}, (x - r, y, x + r, y + 1.2 * ry))
        for xx in (-r, -0.35 * r, 0.35 * r, r):
            self.plot([x + xx, x], [y + 0.15 * ry, y - 1.05 * ry], 9.2, {"color": PJA_ROT, "lw": 0.45})
        self.plot([x], [y - 1.1 * ry], 9.2, {"marker": "o", "ms": 1.6, "color": PJA_ROT, "ls": "none"})

    def mit_hx(self, t, p, sep=""):
        return f"{t}{sep}(HX)" if p.get("zeit") in ZEIT_HX else t

    def luftraeume(self):
        L = [(shapely.simplify(self.u(g), self.tol, preserve_topology=True), p) for g, p in self.D["L"]["luftraeume"] if self._im(g)]
        for g, p in L:
            t, lt, kl = p.get("typ"), p.get("lokal"), p.get("klasse")
            unten_fl = (p.get("unten") or {}).get("bezug") == "STD" and float(p["unten"]["wert"]) >= 100
            if t in ("CTR", "CTR_P"):
                self.flaeche(g, 2.9, {"facecolor": CTR_FUELL, "edgecolor": "none", "alpha": 0.33})
            elif t == "CLASS" and kl in ("C", "D") and not unten_fl:
                self.band(g, 1500, 2.95, {"facecolor": C_BAND, "edgecolor": "none", "alpha": 0.7})
            elif t == "RAS" and lt == "RMZ":
                self.flaeche(g, 2.92, {"facecolor": C_BAND, "edgecolor": "none", "alpha": 0.35})
        P = self.D["plaetze_sicht"]
        for g, p in L:
            t, lt, kl = p.get("typ"), p.get("lokal"), p.get("klasse")
            un, ob = self.fl(p.get("unten")), self.fl(p.get("oben"))
            unten_fl = (p.get("unten") or {}).get("bezug") == "STD" and float(p["unten"]["wert"]) >= 100
            if t in ("CTR", "CTR_P"):
                self.umriss(g, C_BLAU, 1.7, (0, (4.5, 2)))
                self.kasten(g, self.mit_hx("D", p), ob, un, C_BLAU)
            elif t == "CLASS" and kl in ("C", "D") and not unten_fl:
                self.umriss(g, C_BLAU, 0.9)
                self.kasten(g, self.mit_hx(kl, p), ob, un, C_BLAU)
            elif t == "CLASS" and kl == "E" and un in ("1000 AGL", "1700 AGL"):
                self.umriss(g, E_BLAU, 0.9)
                self.kasten(g, "E", ob, un, C_BLAU)
            elif t == "RAS" and lt == "TMZ":
                self.umriss(g, TMZ_GRAU, 2.6, (0, (5.5, 1.8, 1.3, 1.8)))
                self.kasten(g, None, ob, un, "#1a1a1a", kopf=self.mit_hx("TMZ", p, " "), rahmen=False)
            elif t == "RAS" and lt == "RMZ":
                self.umriss(g, C_BLAU, 1.5, (0, (4.5, 2)))
                self.kasten(g, None, ob, un, C_BLAU, kopf=self.mit_hx("RMZ", p, " "))
            elif t == "RAS" and lt == "ATZ":
                self.umriss(g, C_BLAU, 1.3, (0, (0.6, 1.5)))
                self.kasten(g, None, ob, un, C_BLAU, kopf="ATZ")
            elif t in ("OTHER:R_AMC", "R", "P") and (p.get("unten") or {}).get("bezug") == "SFC":
                self.band(g, 1300, 6, {"facecolor": "none", "edgecolor": R_ROT, "hatch": "////", "linewidth": 0})
                self.umriss(g, R_ROT, 1.0)
                m = re.match(r"ED([RPD])(.*)", p.get("kennung", "") or "")
                kopf = f"ED-{m.group(1)} {m.group(2).strip()}" if m else (p.get("kennung") or "ED-R")
                self.kasten(g, None, ob, un, R_ROT, kopf=kopf)
            elif t == "A" and lt == "PJA":
                cp = g.centroid
                self.patch("circle", (cp.x, cp.y, 2500), 9, {"fill": False, "ec": PJA_ROT, "lw": 1.6, "ls": (0, (0.5, 1.6)), "capstyle": "round"},
                           (cp.x - 2600, cp.y - 2600, cp.x + 2600, cp.y + 2600))
                nah = any(math.hypot(self.pu(q["x"], q["y"])[0] - cp.x, self.pu(q["x"], q["y"])[1] - cp.y) < 1600 for q in P)
                if nah:
                    self.fallschirm(cp.x - 2450, cp.y + 2450, 820)
                else:
                    self.fallschirm(cp.x, cp.y, 1000)
            elif t == "A" and lt == "ACR":
                cp = g.centroid
                self.text(cp.x, cp.y, "✈", 11, 9, "center", "center", rotation=35, color=PJA_ROT, fontfamily="DejaVu Sans")

    # ---------- Hindernisse ----------
    def hindernisse(self):
        _M, _L, _C = Path.MOVETO, Path.LINETO, Path.CLOSEPOLY

        def strahlen(oben):
            d = oben - 0.62
            return [((x0_, y0_ + d), (x1_, y1_ + d)) for (x0_, y0_), (x1_, y1_) in
                    (((0, 0.62), (0, 0.98)), ((-0.2, 0.55), (-0.45, 0.85)), ((0.2, 0.55), (0.45, 0.85)), ((-0.25, 0.38), (-0.6, 0.48)), ((0.25, 0.38), (0.6, 0.48)))]

        def zeichen(teile, oben, bef):
            v, c = [], []
            for zug in teile:
                geschl = len(zug) > 2 and zug[0] == zug[-1]
                pts = zug[:-1] if geschl else zug
                v += pts; c += [_M] + [_L] * (len(pts) - 1)
                if geschl:
                    v.append(pts[0]); c.append(_C)
            if bef:
                for a_, b_ in strahlen(oben):
                    v += [a_, b_]; c += [_M, _L]
            s_ = 1.0 / max(1.0, max(abs(y_) for _, y_ in v))
            return Path([(x_ * s_, y_ * s_) for x_, y_ in v], c)

        LAMBDA = [[(-0.32, -0.9), (0, 0.4), (0.32, -0.9)]]
        GRUPPE = [[(-0.62, -0.9), (-0.3, 0.2), (0.02, -0.9)], [(-0.02, -0.9), (0.3, 0.4), (0.62, -0.9)]]
        ART = {
            "STACK": ([[(-0.2, -0.9), (-0.11, 0.55), (0.11, 0.55), (0.2, -0.9), (-0.2, -0.9)]], 0.55),
            "TOWER": ([[(0, -0.9), (0, 0.75)], [(-0.2, 0.25), (0, 0.42), (0.2, 0.25), (0, 0.08), (-0.2, 0.25)]], 0.75),
            "ANTENNA": ([[(-0.3, -0.9), (0, 0.6), (0.3, -0.9)], [(-0.24, -0.6), (0.24, -0.6)], [(-0.17, -0.25), (0.17, -0.25)],
                         [(-0.24, -0.6), (0.17, -0.25)], [(0.24, -0.6), (-0.17, -0.25)]], 0.6),
            "TRANSMISSION_LINE": ([[(-0.28, -0.9), (0, 0.55), (0.28, -0.9)], [(-0.48, 0.25), (0.48, 0.25)], [(-0.36, -0.05), (0.36, -0.05)]], 0.55),
            "SPIRE": ([[(-0.17, -0.9), (-0.17, -0.15), (0, 0.6), (0.17, -0.15), (0.17, -0.9), (-0.17, -0.9)], [(0, 0.6), (0, 0.85)], [(-0.09, 0.74), (0.09, 0.74)]], 0.85),
            "BUILDING": ([[(-0.28, -0.9), (-0.28, 0.2), (0.28, 0.2), (0.28, -0.9), (-0.28, -0.9)]], 0.2),
            "OTHER:DUMP": ([[(-0.62, -0.9), (-0.3, -0.25), (0.3, -0.25), (0.62, -0.9), (-0.62, -0.9)]], -0.25),
        }

        def gruppe_bef():
            p_ = zeichen(GRUPPE, 0.4, False); v = list(p_.vertices); c = list(p_.codes)
            for a_, b_ in strahlen(0.4):
                v += [(a_[0] + 0.3, a_[1]), (b_[0] + 0.3, b_[1])]; c += [_M, _L]
            sc = 1.0 / max(1.0, max(abs(y_) for _, y_ in v))
            return Path([(x_ * sc, y_ * sc) for x_, y_ in v], c)

        def hz(typ, bef, gruppe=False):
            if gruppe:
                return zeichen(GRUPPE, 0.4, bef) if not bef else gruppe_bef()
            teile, oben = ART.get(typ, (LAMBDA, 0.4))
            return zeichen(teile, oben, bef)

        WR = Path([(0, -0.9), (0, 0.25), (0, 0.25), (0, 1.0), (0, 0.25), (-0.65, -0.12), (0, 0.25), (0.65, -0.12)],
                  [Path.MOVETO, Path.LINETO, Path.MOVETO, Path.LINETO, Path.MOVETO, Path.LINETO, Path.MOVETO, Path.LINETO])
        H = []
        for h in self.D["L"]["hindernisse"]:
            x, y = self.pu(h["x"], h["y"])
            if self.gebiet_m is not None and not self.gebiet_m.contains(Point(h["x"], h["y"])):
                continue
            H.append((x, y, h))

        def gruppiere(liste, d):
            gitter, gruppen = {}, []
            for x, y, h in liste:
                i, j = int(x // d), int(y // d); treffer = None
                for a in (i - 1, i, i + 1):
                    for b in (j - 1, j, j + 1):
                        for gi in gitter.get((a, b), ()):
                            gx, gy = gruppen[gi]["p"]
                            if math.hypot(gx - x, gy - y) < d:
                                treffer = gi; break
                        if treffer is not None:
                            break
                    if treffer is not None:
                        break
                if treffer is None:
                    gruppen.append({"p": (x, y), "n": 1, "liste": [(x, y, h)]}); gitter.setdefault((i, j), []).append(len(gruppen) - 1)
                else:
                    gruppen[treffer]["n"] += 1; gruppen[treffer]["liste"].append((x, y, h))
            return gruppen

        for gr in gruppiere([e for e in H if e[2]["typ"] == "WINDMILL"], 3000):
            cx = float(np.mean([e[0] for e in gr["liste"]])); cy = float(np.mean([e[1] for e in gr["liste"]]))
            mx = max(e[2]["hoehe_msl_ft"] or 0 for e in gr["liste"])
            self.plot([cx], [cy], 8, {"marker": WR, "ms": 7 if gr["n"] < 5 else 9, "color": HIND, "mew": 0.8, "ls": "none"})
            if gr["n"] >= 5:
                self.setze(cx, cy, f"{mx}", 6.8, versuche=((0.9, 0.3), (-0.9, 0.3), (0.9, -0.5)), pflicht=False, z=8,
                           halo=[(1.4, "white")], color=HIND, style="italic")
        rest = sorted([e for e in H if e[2]["typ"] != "WINDMILL"], key=lambda e: -(e[2]["hoehe_msl_ft"] or 0))
        for gr in gruppiere(rest, 2000):
            x, y, h0 = gr["liste"][0]
            bef = any(e[2]["befeuert"] == "YES" for e in gr["liste"])
            mk = hz(h0["typ"], bef, gruppe=gr["n"] > 1)
            gefuellt = gr["n"] == 1 and h0["typ"] == "STACK"
            self.plot([x], [y], 8, {"marker": mk, "ms": 8.5 if gr["n"] > 1 else 8, "mfc": HIND if gefuellt else "none", "mec": HIND, "mew": 0.9, "ls": "none"})
            self.setze(x, y, f"{h0['hoehe_msl_ft']} ({h0['hoehe_agl_ft']})", 5.8, versuche=((0.95, 0.0), (-0.95, 0.0), (0.0, -0.9), (0.0, 0.9)),
                       pflicht=False, z=8, halo=[(1.4, "white")], color=HIND, style="italic")

    # ---------- Funkfeuer ----------
    def funkfeuer(self):
        from pygeomag import GeoMag
        gm = GeoMag(); jahr = self.D["jahr"]
        nav = {}
        for e in self.D["L"]["funkfeuer"]:
            if e["art"] not in ("VOR", "NDB", "DME"):
                continue
            if self.gebiet_m is not None and not self.gebiet_m.contains(Point(e["x"], e["y"])):
                continue
            if e["art"] == "DME" and (str(e["kennung"]).startswith("I") or e["kennung"] in OHNE_DME):
                continue
            n = nav.setdefault(e["kennung"], {"xy": (e["x"], e["y"]), "ll": (e["lon"], e["lat"]), "arten": set(), "f": None, "name": e["name"]})
            n["arten"].add(e["art"]); n["name"] = n["name"] or e["name"]
            if e["art"] in ("VOR", "NDB") and e["frequenz"]:
                n["f"] = e["frequenz"]
        for kz, e in sorted(nav.items()):
            x, y = self.pu(*e["xy"]); vor = "VOR" in e["arten"]; dme = "DME" in e["arten"]
            if vor:
                self.plot([x], [y], 10, {"marker": "h", "ms": 7.5, "mfc": "white", "mec": FL_BLAU, "mew": 1.1, "ls": "none"})
                self.plot([x], [y], 10, {"marker": ".", "ms": 2, "color": FL_BLAU, "ls": "none"})
                if dme:
                    self.patch("rect", (x - 1400, y - 1400, 2800, 2800), 10, {"fill": False, "ec": FL_BLAU, "lw": 0.8}, (x - 1500, y - 1500, x + 1500, y + 1500))
                var = gm.calculate(glat=e["ll"][1], glon=e["ll"][0], alt=0, time=jahr).d
                R0 = 8000
                self.patch("circle", (x, y, R0), 9, {"fill": False, "ec": FL_BLAU, "lw": 0.6}, (x - R0 - 300, y - R0 - 300, x + R0 + 300, y + R0 + 300))
                striche = []
                for a in range(0, 360, 5):
                    az = math.radians(a + var); l = 1300 if a % 30 == 0 else 800 if a % 10 == 0 else 450
                    striche.append([(x + (R0 - l) * math.sin(az), y + (R0 - l) * math.cos(az)), (x + R0 * math.sin(az), y + R0 * math.cos(az))])
                for s_ in striche:
                    self.linie(s_, 9, {"color": FL_BLAU, "linewidth": 0.45})
                self.S.add(9, "pfeil", ((x + R0 * 1.12 * math.sin(math.radians(var)), y + R0 * 1.12 * math.cos(math.radians(var))), (x, y)),
                           (x - R0 * 1.2, y - R0 * 1.2, x + R0 * 1.2, y + R0 * 1.2))
            elif dme and "NDB" not in e["arten"]:
                self.patch("rect", (x - 1100, y - 1100, 2200, 2200), 10, {"fc": "white", "ec": FL_BLAU, "lw": 1.1}, (x - 1200, y - 1200, x + 1200, y + 1200))
                self.plot([x], [y], 10.1, {"marker": ".", "ms": 2, "color": FL_BLAU, "ls": "none"})
            elif "NDB" in e["arten"]:
                xs, ys = [], []
                for rr, nn in ((450, 8), (850, 14), (1250, 20), (1650, 26), (2050, 32)):
                    ww = np.linspace(0, 2 * np.pi, nn, endpoint=False); xs += list(x + rr * np.cos(ww)); ys += list(y + rr * np.sin(ww))
                self.plot(xs, ys, 10, {"marker": "o", "ms": math.sqrt(0.9), "color": "#5560d0", "mew": 0, "ls": "none"})
                self.plot([x], [y], 10, {"marker": "o", "ms": 1.8, "color": "#5560d0", "ls": "none"})
            if vor:
                fq = e["f"]
                txt = f"{(e['name'] or '').upper()}\n{float(fq):.2f} {kz}" if fq else f"{(e['name'] or '').upper()}\n{kz}"
            elif "NDB" in e["arten"]:
                txt = f"{int(float(e['f'])) if e['f'] else ''} {kz}"
            else:
                txt = f"{(e['name'] or '').upper()} DME\n{kz}"
            self.setze(x, y, txt, 6.0, versuche=((1.6, -1.2), (1.6, 1.2), (-1.6, -1.2), (-1.6, 1.2)), z=11,
                       halo=None if vor else [(1.8, "white")], bbox=dict(boxstyle="square,pad=0.25", fc="white", ec=FL_BLAU, lw=0.7) if vor else None,
                       fontfamily=SCHMAL, weight="bold", color=FL_BLAU, linespacing=1.0)

    # ---------- Flugplätze ----------
    def flugplaetze(self):
        z = self.z
        from pygeomag import GeoMag  # noqa: F401
        pisten = [self.u(q) for q in self.D["topo"]["pisten"] if self._im(q)]
        baum = STRtree(pisten) if pisten else None
        halo = [(2, "white")]
        SEGLER = Path([(-0.85, 0.0), (-0.45, 0.28), (-0.12, 0.05), (0, -0.12), (0.12, 0.05), (0.45, 0.28), (0.85, 0.0)], [Path.MOVETO] + [Path.LINETO] * 6)
        for q in self.D["plaetze_sicht"]:
            x, y = self.pu(q["x"], q["y"]); gm_ = self.gmf(y)
            rich = None
            nah = [pisten[i] for i in baum.query(Point(x, y).buffer(1500 * gm_))] if baum is not None else []
            nah = [pl for pl in nah if pl.distance(Point(x, y)) < 1500 * gm_]
            if nah:
                pl = max(nah, key=lambda l: l.length); (ax_, ay_), (bx_, by_) = pl.coords[0][:2], pl.coords[-1][:2]
                rich = math.degrees(math.atan2(by_ - ay_, bx_ - ax_))
            pl_ = q["pisten"] or []
            lang = max(pl_, key=lambda p: p.get("laenge_m") or 0) if pl_ else None
            if rich is None and lang and lang.get("kurs_rw") is not None:
                rich = 90 - float(lang["kurs_rw"])
            fest = bool(lang and lang.get("fest"))
            hoehe = q["hoehe_ft"]; laenge = f"{lang['laenge_m']}m" if lang and lang.get("laenge_m") else ""; mhz = q.get("mhz") or ""
            ifr = q["art"] == "Regionalflughafen"
            mil = q["mil"]; segel = q["art"] == "Segelfluggelände"
            rr = 950 if segel else 1050

            def balken(lw_):
                if rich is None:
                    return
                dx, dy = math.cos(math.radians(rich)) * (rr + 650), math.sin(math.radians(rich)) * (rr + 650)
                bb = (x - abs(dx) - 200, y - abs(dy) - 200, x + abs(dx) + 200, y + abs(dy) + 200)
                if fest or lang is None:
                    self.plot([x - dx, x + dx], [y - dy, y + dy], 11, {"color": FL_BLAU, "lw": lw_, "solid_capstyle": "butt"})
                else:
                    self.plot([x - dx, x + dx], [y - dy, y + dy], 11, {"color": FL_BLAU, "lw": lw_ + 0.4, "solid_capstyle": "butt"})
                    self.plot([x - dx * 0.94, x + dx * 0.94], [y - dy * 0.94, y + dy * 0.94], 11.1, {"color": "white", "lw": lw_ - 1.2, "solid_capstyle": "butt"})

            if q["art"] == "Hubschrauberflugplatz":
                if z <= 9:
                    continue
                self.patch("circle", (x, y, 900), 10, {"fc": "white", "ec": FL_BLAU, "lw": 1.6}, (x - 1000, y - 1000, x + 1000, y + 1000))
                self.text(x, y, "H", 6.2, 11.2, "center", "center", color=FL_BLAU, weight="bold")
                nm = re.sub(r" Bundespolizei| ADAC-Luftrettungs-Station| Firma .*", "", q["name"]).upper()
                self.setze(x, y, nm, 5.6, versuche=((1.2, -0.7), (1.2, 0.7), (-1.2, -0.7), (-1.2, 0.7), (0, 1.5), (0, -1.5), (1.9, 0), (-1.9, 0)),
                           z=11, halo=halo, color=FL_BLAU, linespacing=1.0)
                continue
            if segel:
                if z <= 9:
                    continue
                self.patch("circle", (x, y, rr), 10, {"fc": "white", "ec": FL_BLAU, "lw": 1.8}, (x - rr - 100, y - rr - 100, x + rr + 100, y + rr + 100))
                balken(1.8)
                self.plot([x], [y], 11.2, {"marker": SEGLER, "ms": 7, "mfc": "none", "mec": FL_BLAU, "mew": 1.1, "ls": "none"})
                self.setze(x, y, q["name"].upper(), 5.8, versuche=((1.2, -0.7), (1.2, 0.7), (-1.2, -0.7), (-1.2, 0.7), (0, 1.5), (0, -1.5), (1.9, 0), (-1.9, 0),
                                                                    (2.4, 1.2), (-2.4, 1.2), (2.4, -1.2), (-2.4, -1.2)), z=11, halo=halo, color=FL_BLAU, linespacing=1.0)
                continue
            if q["art"] == "Internationaler Flughafen":
                pb = [pl for pl in (pisten[i] for i in baum.query(Point(x, y).buffer(3500 * gm_))) if pl.distance(Point(x, y)) < 3500 * gm_
                      and pl.length > 1500 * gm_] if baum is not None else []
                for pl in pb:
                    ln_ = np.asarray(pl.coords)[:, :2]
                    self.plot(ln_[:, 0], ln_[:, 1], 11, {"color": FL_BLAU, "lw": 4.2, "solid_capstyle": "butt"})
                    self.plot(ln_[:, 0], ln_[:, 1], 11.1, {"color": "white", "lw": 0.5, "solid_capstyle": "butt"})
                    self.B.add(pl.buffer(500).bounds)
                if not pb:
                    balken(4.0)
                z1 = f"{q['kennung']} {hoehe} AMSL" if hoehe else q["kennung"]
                self.platz_label(x, y, z1, q["name"].upper() if z >= 10 else "", mhz if z >= 10 else "", laenge if z >= 10 else "", halo, fs=6.6)
                continue
            self.patch("circle", (x, y, rr), 10, {"fc": "white", "ec": FL_BLAU, "lw": 2.0}, (x - rr - 100, y - rr - 100, x + rr + 100, y + rr + 100))
            if mil:
                self.patch("circle", (x, y, rr * 0.45), 10.1, {"fc": "none", "ec": FL_BLAU, "lw": 1.4}, (x - rr, y - rr, x + rr, y + rr))
            if ifr:
                for w_ in (0, 90, 180, 270):
                    c_, s_ = math.cos(math.radians(w_)), math.sin(math.radians(w_))
                    self.plot([x + rr * c_, x + (rr + 650) * c_], [y + rr * s_, y + (rr + 650) * s_], 10, {"color": FL_BLAU, "lw": 2.4, "solid_capstyle": "butt"})
            balken(2.6)
            z1 = f"{q['kennung']} {hoehe} AMSL" if hoehe and q["kennung"] else (q["kennung"] or "")
            if z <= 9:
                self.platz_label(x, y, q["kennung"] or "", "", "", "", halo)
            else:
                self.platz_label(x, y, z1, q["name"].upper(), mhz, laenge, halo)

    def platz_label(self, x, y, z1, z2, mhz, laenge, halo, fs=6.0):
        z3 = " ".join(t for t in (mhz, laenge) if t)
        voll = "\n".join(t for t in (z1, z2, z3) if t)
        if not voll:
            return
        r = self._setze_still(x, y, voll, fs, versuche=((1.3, 0.9), (1.3, -0.9), (-1.3, 0.9), (-1.3, -0.9), (0, 1.7), (0, -1.7), (1.3, 2.4), (-1.3, 2.4),
                                                         (1.3, -2.4), (-1.3, -2.4), (2.4, 0.4), (-2.4, 0.4), (0, 3.2), (0, -3.2)), linespacing=1.0)
        if not mhz:
            self.text(r["x"], r["y"], voll, fs, 11, r["ha"], r["va"], halo=halo, color=FL_BLAU, linespacing=1.0)
            return
        x0, y0, x1, y1 = r["box"]; y1 -= 0.6 * PT
        ha = r["ha"]; xa = r["x"]
        oben = "\n".join(t for t in (z1, z2) if t)
        self.text(xa, y1, oben, fs, 11, ha, "top", halo=halo, color=FL_BLAU, linespacing=1.0)
        yo = (-2 * fs * 1.0 - 0.6) * PT
        wf = mass(mhz, fs, style="italic")[0]; wl = mass(laenge, fs)[0] if laenge else 0; gap = 2.5 if laenge else 0
        ges = wf + gap + wl; start = 0 if ha == "left" else -ges if ha == "right" else -ges / 2
        self.text(xa + start * PT, y1 + yo, mhz, fs, 11, "left", "top", halo=halo, color=FL_BLAU, style="italic")
        if laenge:
            self.text(xa + (start + wf + gap) * PT, y1 + yo, laenge, fs, 11, "left", "top", halo=halo, color=FL_BLAU)

    def _setze_still(self, x, y, txt, fs, versuche, **kw):
        """wie setze (Pflicht), zeichnet aber nicht — Lage für platz_label"""
        best = None
        for dx, dy in versuche:
            ha = "left" if dx > 0 else "right" if dx < 0 else "center"
            va = "bottom" if dy > 0 else "top" if dy < 0 else "center"
            px_, py_ = x + dx * fs * PT, y + dy * fs * PT
            b = textbox(px_, py_, txt, fs, ha, va, **kw)
            if self.innen(b) and self.B.frei(b):
                self.B.add(b); return {"x": px_, "y": py_, "ha": ha, "va": va, "box": b}
            ib = box(*b)
            wert = (0 if self.innen(b) else 1, ib.difference(self.INNEN).area if not self.innen(b) else 0.0, self.B.ueberdeckung(b))
            if best is None or wert < best[0]:
                best = (wert, {"x": px_, "y": py_, "ha": ha, "va": va, "box": b})
        self.B.add(best[1]["box"]); return best[1]

    # ---------- Meldepunkte ----------
    def meldepunkte(self):
        M = []
        for m in self.D["L"]["meldepunkte"]:
            if self.gebiet_m is not None and not self.gebiet_m.contains(Point(m["x"], m["y"])):
                continue
            M.append((self.pu(m["x"], m["y"]), m))
        for (x, y), p in M:
            self.patch("circle", (x, y, 1150), 11.4, {"fill": False, "ec": FL_BLAU, "lw": 1.0, "ls": (0, (2.2, 1.4))}, (x - 1250, y - 1250, x + 1250, y + 1250))
            self.plot([x], [y + 60], 11.5, {"marker": "^", "ms": 6.0, "mfc": FL_BLAU, "mec": FL_BLAU, "mew": 0.4, "ls": "none"})
        pts = np.array([xy for xy, _ in M]) if M else np.zeros((0, 2))
        for (x, y), p in M:
            v = [(1.2, 0.6), (-1.2, 0.6), (1.2, -0.7), (-1.2, -0.7), (0, 1.5), (0, -1.6)]
            if len(pts) > 1:
                d = np.hypot(pts[:, 0] - x, pts[:, 1] - y); d[d == 0] = np.inf
                i = int(np.argmin(d))
                if d[i] < 5000:
                    xx, yy = pts[i]; v.sort(key=lambda q: q[0] * (xx - x) + q[1] * (yy - y))
            nm = re.sub(r"(\D)(\d+)$", r"\1 \2", (p.get("langname") or p["name"]).strip())   # wie ICAO-Karte: „WHISKEY 1“
            self.setze(x, y, nm, 5.8, versuche=tuple(v), z=11.5, halo=[(1.8, "white")], color=FL_BLAU, weight="bold", fontfamily=SCHMAL)

    # ---------- Ortsnamen ----------
    def orte(self):
        z = self.z
        gross, klein = [], []
        for g, n in self.orte_u:
            if not n or NICHT_ORT.search(n):
                continue
            k = self.km2(g)
            if k >= (6 if z <= 9 else 2.5):
                gross.append((k, g, n))
            elif z >= 10 and (0.4 if z >= 11 else 0.9) <= k < 2.5:
                klein.append((k, g, n))
        for k, g, n in sorted(gross, key=lambda t: -t[0]):
            n = n.replace(" (Saale)", "").replace(" (Anhalt)", "").replace("/Anhalt", "")
            fs, txt, gew = (8.6, n.upper(), "bold") if k >= 15 else (6.6, n.upper(), "bold") if k >= 6 else (5.8, n, "normal")
            pt = g.representative_point()
            self.setze(pt.x, pt.y, txt, fs, versuche=((0, 0), (0, 1.2), (0, -1.2), (1.2, 0), (-1.2, 0)), pflicht=k >= 15, z=8,
                       halo=[(1.5, "white")], color="#111", weight=gew)
        for k, g, n in klein:
            pt = g.representative_point()
            self.setze(pt.x, pt.y, n, 5.2, versuche=((0.9, 0.5), (-0.9, 0.5), (0.9, -0.5), (-0.9, -0.5)), pflicht=False, z=8,
                       halo=[(1.3, "white")], color="#111")
        for g, n in (self.doerfer if z >= 11 else self.doerfer[::2]):
            if n and not NICHT_ORT.search(n):
                self.setze(g.x, g.y, n, 4.8, versuche=((0.7, 0.4), (-0.7, 0.4), (0.7, -0.5), (-0.7, -0.5)), pflicht=False, z=8,
                           halo=[(1.2, "white")], color="#111")

    # ---------- Höhenpunkte ----------
    def hoehenpunkte(self):
        # Brocken: Name und amtliche Gipfelhöhe immer, Zahl im Kasten (Übungskarte, Testrunde 15.11.2026; DGM200 glättet die Spitze)
        bx, by = self.pu(*BROCKEN_M)
        if self.gebiet_m is None or self.gebiet_m.contains(Point(*BROCKEN_M)):
            self.plot([bx], [by], 8.5, {"marker": ".", "ms": 2.6, "color": "#111", "ls": "none"})
            self.setze(bx, by, "3743", 6.8, versuche=((0.5, -0.45), (-0.5, -0.45), (0.5, 0.45), (-0.5, 0.45), (0, -0.8)), z=8.6,
                       bbox=dict(boxstyle="square,pad=0.22", fc="white", ec="#111", lw=0.6), color="#111", style="italic")
            self.setze(bx, by, "Brocken", 6.4, versuche=((0, 0.9), (0, -0.9), (1.1, 0.6), (-1.1, 0.6), (1.1, -0.6), (-1.1, -0.6)), z=8.5,
                       halo=[(1.3, "white")], color="#111", style="italic", weight="bold")
        for h_, xm, ym in self.D["hp"]:
            if math.hypot(xm - BROCKEN_M[0], ym - BROCKEN_M[1]) < 3000 * 1.6:
                continue
            if self.gebiet_m is not None and not self.gebiet_m.contains(Point(xm, ym)):
                continue
            x, y = self.pu(xm, ym)
            if self.INNEN_P.contains(Point(x, y)):
                r = self.setze(x, y, f"{int(round(h_))}", 6.4, versuche=((0.35, 0.0), (-0.35, 0.0)), pflicht=False, z=8,
                               halo=[(1.3, "white")], color="#111", style="italic")
                if r is not None:
                    self.plot([x], [y], 8, {"marker": ".", "ms": 2.2, "color": "#111", "ls": "none"})

    # ---------- Isogonen ----------
    def isogonen(self):
        for lev, linien, labels in self.D["iso"]:
            for c in linien:
                self.linie(c * self.f, 6, {"color": E_LILA, "linewidth": 0.9, "linestyle": (0, (10, 3))})
            for (xm, ym, w) in labels:
                x, y = self.pu(xm, ym)
                t = f"{lev:.1f}".replace(".", ",").replace(",0", "") + "° E"
                self.text(x, y, t, 6.5, 6.1, "center", "center", halo=[(2.5, "white")], rotation=w, color=E_LILA)

    # ---------- MEF ----------
    def mef(self):
        for e in self.D["mef"]:
            x, y = self.pu(e["xm"], e["ym"])
            m = e["mef_ft"] // 100
            self.text(x, y, f"{m // 10}", 19, 7.5, "right", "center", halo=[(1.2, "white")], color=MEF_F, alpha=0.85, weight="bold")
            self.text(x + 150, y + 700, f"{m % 10}", 13, 7.5, "left", "center", halo=[(1.2, "white")], color=MEF_F, alpha=0.85, weight="bold")

    # ---------- Gradnetz ----------
    def gradnetz(self):
        lon0, lat0, lon1, lat1 = self.D["grenzen"]
        from pyproj import Transformer
        tr = Transformer.from_crs(4326, 3857, always_xy=True)
        T = lambda lo, la: tuple(v * self.f for v in tr.transform(lo, la))
        for lon in np.arange(math.ceil(lon0 * 2) / 2, lon1 + 1e-6, 0.5):
            xs, ys = zip(*[T(lon, b) for b in np.linspace(lat0, lat1, 40)])
            self.linie(np.column_stack([xs, ys]), 12, {"color": "#111", "linewidth": 0.4})
            for mi in range(int(round(lat0 * 60)) + 1, int(round(lat1 * 60))):
                x_, y_ = T(lon, mi / 60); l = 1500 if mi % 10 == 0 else 800 if mi % 5 == 0 else 500
                self.linie([(x_ - l / 2, y_), (x_ + l / 2, y_)], 12, {"color": "#111", "linewidth": 0.35})
        for lat in np.arange(math.ceil(lat0 * 2) / 2, lat1 + 1e-6, 0.5):
            xs, ys = zip(*[T(a, lat) for a in np.linspace(lon0, lon1, 40)])
            self.linie(np.column_stack([xs, ys]), 12, {"color": "#111", "linewidth": 0.4})
            for mi in range(int(round(lon0 * 60)) + 1, int(round(lon1 * 60))):
                x_, y_ = T(mi / 60, lat); l = 1500 if mi % 10 == 0 else 800 if mi % 5 == 0 else 500
                self.linie([(x_, y_ - l / 2), (x_, y_ + l / 2)], 12, {"color": "#111", "linewidth": 0.35})


# =====================================================================================================================
# Gemeinsame Vorberechnungen (unabhängig von der Zoomstufe)
# =====================================================================================================================
def vorbereiten(arbeit, zyklus, gebiet=None):
    from pyproj import Transformer
    D = {"topo": pickle.load(open(os.path.join(arbeit, "topo.pkl"), "rb"))}
    T = D["topo"]; D["de"] = T["de"]
    arr = lambda l: np.array(l, dtype=object) if l else np.array([], dtype=object)
    D["arr"] = {"wald": arr(T["wald"]), "orte": arr([g for g, n in T["orte"]]), "orte_n": [n for g, n in T["orte"]],
                "wasser": arr(T["wasser"]), "fluesse": arr([g for g, w, n in T["fluesse"]]), "fluesse_w": [w for g, w, n in T["fluesse"]],
                "fluesse_n": [n for g, w, n in T["fluesse"]], "strassen": arr([g for g, w, b in T["strassen"]]),
                "strassen_w": [w for g, w, b in T["strassen"]], "strassen_b": [b for g, w, b in T["strassen"]]}
    for k in ("ein", "mehr", "still"):
        D["arr"]["bahn_" + k] = arr(T["bahn_" + k])
    L = pickle.load(open(os.path.join(arbeit, f"luftfahrt_{zyklus}.pkl"), "rb"))
    D["L"] = L
    ab = dt.date.fromisoformat(L["ab"])
    D["jahr"] = ab.year + (ab.timetuple().tm_yday - 0.5) / 365.25
    pz = os.path.join(arbeit, f"plaetze_{zyklus}.json")
    P = json.load(open(pz if os.path.exists(pz) else os.path.join(arbeit, "plaetze.json"), encoding="utf-8"))
    rang = ["Internationaler Flughafen", "Regionalflughafen", "Verkehrslandeplatz", "Sonderlandeplatz", "Segelfluggelände", "Hubschrauberflugplatz"]
    deP = prep(D["de"])
    D["plaetze_sicht"] = sorted([q for q in P if deP.contains(Point(q["x"], q["y"])) and (gebiet is None or gebiet.contains(Point(q["x"], q["y"])))],
                                key=lambda q: rang.index(q["art"]))
    m2l = Transformer.from_crs(3857, 4326, always_xy=True)
    x0, y0, x1, y1 = D["de"].bounds
    lo0, la0 = m2l.transform(x0, y0); lo1, la1 = m2l.transform(x1, y1)
    D["grenzen"] = (math.floor(lo0 * 2) / 2, math.floor(la0 * 2) / 2, math.ceil(lo1 * 2) / 2, math.ceil(la1 * 2) / 2)
    # DGM200: Höhenpunkte (höchster Punkt je 6-km-Feld, wenn er auch im Umkreis der höchste ist) und Feldmaxima für die MEF
    d = np.load(os.path.join(arbeit, "dgm200.npz")); a = d["hoehe_m"]; x0u, y0u, pix = d["meta"]
    ft = np.nan_to_num(a, nan=-9999.0) * 3.28084
    NB = 30; hp = []
    u2m = Transformer.from_crs(25832, 3857, always_xy=True)
    for i0 in range(0, ft.shape[0] - NB, NB):
        for j0 in range(0, ft.shape[1] - NB, NB):
            blk = ft[i0:i0 + NB, j0:j0 + NB]; k_ = np.unravel_index(np.argmax(blk), blk.shape); i_, j_ = i0 + k_[0], j0 + k_[1]
            um = ft[max(0, i_ - NB):i_ + NB + 1, max(0, j_ - NB):j_ + NB + 1]
            if ft[i_, j_] >= um.max() and ft[i_, j_] > 150:
                xm, ym = u2m.transform(x0u + (j_ + 0.5) * pix, y0u - (i_ + 0.5) * pix)
                hp.append((float(ft[i_, j_]), xm, ym))
    D["hp"] = sorted(hp, reverse=True)
    # MEF je 30′-Feld, nur Felder ganz in Deutschland (Gelände DGM200 + 300 ft oder Hindernis, + 100 ft, aufgerundet)
    rr, cc = np.mgrid[0:ft.shape[0], 0:ft.shape[1]]
    u2l = Transformer.from_crs(25832, 4326, always_xy=True)
    lon, lat = u2l.transform(x0u + (cc + 0.5) * pix, y0u - (rr + 0.5) * pix)
    fi = np.floor(np.asarray(lon) * 2).astype(int); fj = np.floor(np.asarray(lat) * 2).astype(int)
    hmax = {}
    ok = ft > -1000
    for a_, b_, h_ in zip(fi[ok].ravel(), fj[ok].ravel(), ft[ok].ravel()):
        k = (a_, b_)
        if h_ > hmax.get(k, -1e9):
            hmax[k] = h_
    omax = {}
    for h in L["hindernisse"]:
        lo, la = m2l.transform(h["x"], h["y"]); k = (math.floor(lo * 2), math.floor(la * 2))
        omax[k] = max(omax.get(k, 0), h["hoehe_msl_ft"] or 0)
    l2m = Transformer.from_crs(4326, 3857, always_xy=True)
    mef = []
    for (a_, b_), h_ in sorted(hmax.items()):
        zelle = Polygon([l2m.transform(a_ / 2 + i / 20, b_ / 2) for i in range(11)] + [l2m.transform(a_ / 2 + 0.5, b_ / 2 + i / 20) for i in range(11)]
                        + [l2m.transform(a_ / 2 + 0.5 - i / 20, b_ / 2 + 0.5) for i in range(11)] + [l2m.transform(a_ / 2, b_ / 2 + 0.5 - i / 20) for i in range(11)])
        if not deP.contains(zelle):
            continue
        if gebiet is not None and not gebiet.intersects(zelle):
            continue
        m = math.ceil((max(h_ + 300, omax.get((a_, b_), 0)) + 100) / 100)
        xm, ym = l2m.transform(a_ / 2 + 0.25, b_ / 2 + 0.25)
        mef.append({"lon0": a_ / 2, "lat0": b_ / 2, "mef_ft": m * 100, "gelaende_ft": round(float(h_)), "hindernis_ft": omax.get((a_, b_), 0), "xm": xm, "ym": ym})
    D["mef"] = mef
    # Isogonen (WMM2025 zum Beginn des Zyklus), Beschriftung an festen Breiten
    from pygeomag import GeoMag
    import contourpy
    gm = GeoMag()
    lo = np.arange(D["grenzen"][0] - 0.5, D["grenzen"][2] + 0.51, 0.25); la = np.arange(D["grenzen"][1] - 0.5, D["grenzen"][3] + 0.51, 0.25)
    V = np.array([[gm.calculate(glat=b, glon=a_, alt=0, time=D["jahr"]).d for a_ in lo] for b in la])
    LO, LA = np.meshgrid(lo, la)
    gen = contourpy.contour_generator(LO, LA, V)
    iso = []
    for lev in np.arange(math.floor(V.min() * 2) / 2 + 0.5, V.max(), 0.5):
        linien, labels = [], []
        for c in gen.lines(lev):
            xm, ym = l2m.transform(c[:, 0], c[:, 1]); cm = np.column_stack([xm, ym]); linien.append(cm)
            for bl in np.arange(math.floor(c[:, 1].min()) + 0.1, c[:, 1].max(), 1.0):
                i = np.where((c[:-1, 1] - bl) * (c[1:, 1] - bl) <= 0)[0]
                for k in i[:1]:
                    t = (bl - c[k, 1]) / ((c[k + 1, 1] - c[k, 1]) or 1e-9)
                    x_ = cm[k, 0] + t * (cm[k + 1, 0] - cm[k, 0]); y_ = cm[k, 1] + t * (cm[k + 1, 1] - cm[k, 1])
                    w = math.degrees(math.atan2(cm[k + 1, 1] - cm[k, 1], cm[k + 1, 0] - cm[k, 0]))
                    w = w - 180 if w > 90 else w + 180 if w < -90 else w
                    if deP.contains(Point(x_, y_)):
                        labels.append((x_, y_, w))
        iso.append((float(lev), linien, labels))
    D["iso"] = iso
    return D


# =====================================================================================================================
# Blöcke zeichnen
# =====================================================================================================================
_G: dict = {}


def _replay(ax, ops):
    """Befehle in eine Achse zeichnen; gleiche Flächen-/Linienstile nacheinander zusammenfassen."""
    i = 0
    while i < len(ops):
        z, nr, art, d, bb = ops[i]
        if art in ("flaeche", "linie"):
            stil = d[1]; j = i; teile = []
            while j < len(ops) and ops[j][2] == art and ops[j][0] == z and ops[j][3][1] is stil:
                teile.append(ops[j][3][0]); j += 1
            if art == "flaeche":
                pcs = []
                for q in teile:
                    verts = [np.asarray(q.exterior.coords)[:, :2]] + [np.asarray(r.coords)[:, :2] for r in q.interiors]
                    codes = []
                    for v in verts:
                        c = [Path.LINETO] * len(v); c[0] = Path.MOVETO; codes += c
                    pcs.append(PathPatch(Path(np.concatenate(verts), codes)))
                pc = PatchCollection(pcs, zorder=z, **stil); ax.add_collection(pc)
            else:
                kw = dict(stil)
                kw2 = {"colors": kw.pop("color"), "linewidths": kw.pop("linewidth", 1.0)}
                if "linestyle" in kw:
                    kw2["linestyles"] = [kw.pop("linestyle")]
                if "capstyle" in kw:
                    kw2["capstyle"] = kw.pop("capstyle")
                ax.add_collection(LineCollection(teile, zorder=z, **kw2, **kw))
            i = j
            continue
        if art == "text":
            kw = dict(d["kw"])
            t = ax.text(d["x"], d["y"], d["s"], fontsize=d["fontsize"], ha=d["ha"], va=d["va"], zorder=z, rotation=d["rotation"],
                        rotation_mode="anchor" if d["rotation"] else "default", **kw)
            if d["halo"]:
                t.set_path_effects(_pe(d["halo"]))
            if d["bbox"]:
                t.set_bbox(d["bbox"])
        elif art == "patch":
            a, dd, stil = d
            if a == "circle":
                ax.add_patch(Circle((dd[0], dd[1]), dd[2], zorder=z, **stil))
            elif a == "rect":
                ax.add_patch(Rectangle((dd[0], dd[1]), dd[2], dd[3], zorder=z, **stil))
            elif a == "poly":
                ax.add_patch(MPoly(dd, closed=True, zorder=z, **stil))
        elif art == "plot":
            xs, ys, stil = d
            ax.plot(xs, ys, zorder=z, **stil)
        elif art == "pfeil":
            ax.annotate("", xy=d[0], xytext=d[1], arrowprops=dict(arrowstyle="-|>", color=FL_BLAU, lw=0.6, mutation_scale=6), zorder=z)
        i += 1


def _gelaende_bild(z, s, gx0, gy0, W, H):
    """Höhenschichten und Schatten (RGBA) für den Block: Bildpunkte gx0 … (CSS-Bildpunkte der Stufe z), Maßstab s."""
    A = _G["gel"][z]; meta = _G["gel_meta"]
    f = 2 ** (12 - z)
    ox, oy = meta["x0"] / f, meta["y0"] / f
    cx = gx0 + (np.arange(W) + 0.5) / s - ox - 0.5
    cy = gy0 + (np.arange(H) + 0.5) / s - oy - 0.5
    ft, dk = A
    i0 = int(max(0, math.floor(cy.min()) - 1)); i1 = int(min(ft.shape[0], math.ceil(cy.max()) + 2))
    j0 = int(max(0, math.floor(cx.min()) - 1)); j1 = int(min(ft.shape[1], math.ceil(cx.max()) + 2))
    tint = np.zeros((H, W, 4), np.float32); sch = np.zeros((H, W, 4), np.float32); sch[..., :3] = (0.40, 0.42, 0.50)
    if i1 - i0 < 2 or j1 - j0 < 2:
        return tint, sch
    F = np.asarray(ft[i0:i1, j0:j1], dtype=np.float32); K = np.asarray(dk[i0:i1, j0:j1], dtype=np.float32) / 255.0
    yy = np.clip(cy - i0, 0, F.shape[0] - 1.001); xx = np.clip(cx - j0, 0, F.shape[1] - 1.001)
    yi = yy.astype(int); xi = xx.astype(int); fy = (yy - yi)[:, None]; fx = (xx - xi)[None, :]

    def bil(M):
        return (M[yi][:, xi] * (1 - fx) * (1 - fy) + M[yi][:, xi + 1] * fx * (1 - fy) + M[yi + 1][:, xi] * (1 - fx) * fy + M[yi + 1][:, xi + 1] * fx * fy)

    h = bil(F); sv = bil(K)
    FC = np.array([matplotlib.colors.to_rgb(c) for c in FARBEN], dtype=np.float32)
    k = np.clip(np.searchsorted(STUFEN, h, side="right") - 1, 0, len(FARBEN) - 1)
    tint[..., :3] = FC[k]; tint[..., 3] = 1.0
    sch[..., 3] = 0.62 * sv
    return tint, sch


def zeichne_block(args):
    z, s, bx, by = args
    S, baum, ops = _G["S"][z], _G["baum"][z], _G["ops"][z]
    TS = 256 * s; N = BLOCK_PX // TS                      # Kacheln je Blockseite
    tx0, ty0 = bx * N, by * N
    W = H = BLOCK_PX
    R = res(z) / s; SK = res(z) * PXPT[z] / PT
    xm0, ym1 = tx0 * 256 * res(z) - E, E - ty0 * 256 * res(z)
    xm1, ym0 = xm0 + W * R, ym1 - H * R
    u0, u1, v0, v1 = xm0 / SK, xm1 / SK, ym0 / SK, ym1 / SK
    rand = 40 * PT
    idx = baum.query(box(u0 - rand, v0 - rand, u1 + rand, v1 + rand))
    teil = sorted((ops[i] for i in idx), key=lambda o: (o[0], o[1]))
    dpi = 72 * PXPT[z] * s
    fig = plt.figure(figsize=(W / dpi, H / dpi), dpi=dpi); fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.patch.set_alpha(0); ax.set_xlim(u0, u1); ax.set_ylim(v0, v1); ax.axis("off")
    tint, sch = _gelaende_bild(z, s, tx0 * 256, ty0 * 256, W, H)
    ax.imshow(tint, extent=(u0, u1, v0, v1), origin="upper", interpolation="nearest", zorder=0, aspect="auto", resample=False)
    ax.imshow(sch, extent=(u0, u1, v0, v1), origin="upper", interpolation="nearest", zorder=0.5, aspect="auto", resample=False)
    _replay(ax, teil)
    ax.set_xlim(u0, u1); ax.set_ylim(v0, v1)
    fig.canvas.draw()
    im = np.asarray(fig.canvas.buffer_rgba()).copy(); plt.close(fig)
    assert im.shape[0] == H and im.shape[1] == W, im.shape
    # nur Deutschland: außerhalb durchsichtig
    import rasterio.features
    from rasterio.transform import Affine
    m = ~rasterio.features.geometry_mask([_G["deckung"]], (H, W), Affine(R, 0, xm0, 0, -R, ym1), all_touched=False)
    im[..., 3] = (im[..., 3].astype(np.uint16) * m).astype(np.uint8)
    from PIL import Image
    n = 0; b = 0
    for j in range(N):
        for i in range(N):
            t = im[j * TS:(j + 1) * TS, i * TS:(i + 1) * TS]
            if t[..., 3].max() == 0:
                continue
            dd = os.path.join(_G["aus"], str(z), str(tx0 + i)); os.makedirs(dd, exist_ok=True)
            fn = os.path.join(dd, f"{ty0 + j}.webp" if s == 1 else f"{ty0 + j}@2x.webp")
            Image.fromarray(np.ascontiguousarray(t), "RGBA").save(fn, "WEBP", quality=88 if s == 1 else 75, method=6)
            n += 1; b += os.path.getsize(fn)
    return n, b


def _frei_gb():
    try:
        for z in open("/proc/meminfo"):
            if z.startswith("MemAvailable:"):
                return int(z.split()[1]) / 1048576
    except OSError:
        pass
    return 0.0


def _rss_gb():
    try:
        for z in open("/proc/self/status"):
            if z.startswith("VmRSS:"):
                return int(z.split()[1]) / 1048576
    except OSError:
        pass
    return 0.0


def bloecke(z, s, deckung_m):
    TS = 256 * s; N = BLOCK_PX // TS
    x0, y0, x1, y1 = deckung_m.bounds
    t = lambda xm: int((xm + E) // (256 * res(z)))
    tyf = lambda ym: int((E - ym) // (256 * res(z)))
    bx0, bx1 = t(x0) // N, t(x1) // N; by0, by1 = tyf(y1) // N, tyf(y0) // N
    out = []
    P = prep(deckung_m)
    for bx in range(bx0, bx1 + 1):
        for by in range(by0, by1 + 1):
            xm0 = bx * N * 256 * res(z) - E; ym1 = E - by * N * 256 * res(z)
            if P.intersects(box(xm0, ym1 - N * 256 * res(z), xm0 + N * 256 * res(z), ym1)):
                out.append((z, s, bx, by))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arbeit", required=True); ap.add_argument("--zyklus", required=True); ap.add_argument("--aus", required=True)
    ap.add_argument("--zoom", nargs=2, type=int, default=[8, 12]); ap.add_argument("--gebiet", nargs=4, type=float)
    ap.add_argument("--prozesse", type=int, default=os.cpu_count() or 1)
    a = ap.parse_args(argv)
    from pyproj import Transformer
    gebiet = None
    if a.gebiet:
        l2m = Transformer.from_crs(4326, 3857, always_xy=True)
        x0, y0 = l2m.transform(a.gebiet[0], a.gebiet[1]); x1, y1 = l2m.transform(a.gebiet[2], a.gebiet[3])
        gebiet = box(x0, y0, x1, y1)
    t0 = time.time()
    from matplotlib import font_manager as _fm
    print("Schriften:", " · ".join(f"{st}: {os.path.basename(_fm.findfont(_fm.FontProperties(family=plt.rcParams['font.family'], style=st)))}"
                                    for st in ("normal", "italic")), "· Breite „120.055“ 6 pt kursiv/normal:",
          [round(float(v), 2) for v in (mass("120.055", 6.0, style="italic")[0], mass("120.055", 6.0)[0])], flush=True)
    D = vorbereiten(a.arbeit, a.zyklus, gebiet)
    print(f"Vorbereitet: {len(D['plaetze_sicht'])} Plätze, {len(D['hp'])} Höhenpunkte, {len(D['mef'])} MEF-Felder, {len(D['iso'])} Isogonen, "
          f"{time.time() - t0:.0f} s", flush=True)
    gm = json.load(open(os.path.join(a.arbeit, "gelaende.json")))
    _G["gel_meta"] = gm["z12"]
    _G["gel"] = {z: (np.load(os.path.join(a.arbeit, f"gelaende_z{z}_ft.npy"), mmap_mode="r"),
                     np.load(os.path.join(a.arbeit, f"gelaende_z{z}_dk.npy"), mmap_mode="r")) for z in range(8, 13)}
    deck = D["de"] if gebiet is None else D["de"].intersection(gebiet)
    _G["deckung"] = deck; _G["aus"] = a.aus
    _G["S"], _G["baum"], _G["ops"] = {}, {}, {}
    stat = {}
    import multiprocessing as mp
    for z in range(a.zoom[0], a.zoom[1] + 1):
        S = Karte(z, D, gebiet).baue()
        ops = S.ops
        _G["ops"][z] = ops; _G["S"][z] = S
        _G["baum"][z] = STRtree([box(*o[4]) for o in ops])
        for s in SCALES[z]:
            jobs = bloecke(z, s, deck)
            t1 = time.time(); n = b = 0
            import gc
            gc.collect(); frei = _frei_gb()
            proz = max(1, min(a.prozesse, int((frei - 1.5) / (1.2 * s * s ** 0.5)))) if frei else a.prozesse
            print(f"  z{z} x{s}: frei {frei:.1f} GB, Eltern {_rss_gb():.1f} GB, {proz} Prozesse", flush=True)
            if proz > 1:
                from concurrent.futures import ProcessPoolExecutor
                gc.freeze()                               # Elternobjekte nicht in die Kindprozesse kopieren lassen
                try:
                    with ProcessPoolExecutor(proz, mp_context=mp.get_context("fork")) as pool:
                        for nn, bb in pool.map(zeichne_block, jobs):
                            n += nn; b += bb
                finally:
                    gc.unfreeze()
            else:
                for j in jobs:
                    nn, bb = zeichne_block(j); n += nn; b += bb
            stat[f"{z}x{s}"] = [n, b]
            print(f"  z{z} x{s}: {len(jobs)} Blöcke, {n} Kacheln, {b / 1e6:.1f} MB, {time.time() - t1:.0f} s", flush=True)
        del _G["ops"][z], _G["S"][z], _G["baum"][z]
    json.dump({"zyklus": a.zyklus, "stat": stat, "mef": D["mef"]}, open(os.path.join(a.aus, "statistik.json"), "w"), ensure_ascii=False)
    print(f"fertig in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
