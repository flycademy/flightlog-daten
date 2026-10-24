"""Geländekacheln für die MSA des Flight Log aus Copernicus DEM GLO-30.

Je 1°-Kachel 120 × 120 Zellen (30″, rund 0,5 NM); Zellwert = HÖCHSTER Geländepunkt der Zelle in m (aufgerundet).
Copernicus-Kacheln, die es nicht gibt, sind Meer. Ausgabe: gelaende.bin (Format: format.py).

Aufruf: python -m fcy_daten.gelaende --aus out/gelaende.bin [--lat 35 60] [--lon -10 30] [--quelle URL]
Quelle: Copernicus DEM GLO-30 (AWS Open Data). GLO-30 statt GLO-90, weil GLO-90 gemittelt ist und spitze Gipfel
um über 100 m zu niedrig wiedergibt (Großglockner 3668 statt 3798 m). © DLR e.V. 2010–2014 und © Airbus Defence and Space GmbH 2014–2018,
bereitgestellt unter COPERNICUS durch die Europäische Union und die ESA; alle Rechte vorbehalten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from . import format as F
from . import netz

QUELLE = "https://copernicus-dem-30m.s3.amazonaws.com"
N = 120


def cop_name(lat: int, lon: int) -> str:
    return (f"Copernicus_DSM_COG_10_{'N' if lat >= 0 else 'S'}{abs(lat):02d}_00_"
            f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}_00_DEM")


def kachel_max(tif: bytes, lat: int, lon: int, n: int = N) -> np.ndarray:
    """GeoTIFF einer 1°-Kachel → int16 [n, n] (Zeile 0 = Nordrand), Höchstwert je Zelle, aufgerundet."""
    with MemoryFile(tif) as mf, mf.open() as ds:
        a = ds.read(1).astype(np.float64)
        nod = ds.nodata
        tr = ds.transform
    if nod is not None:
        a[a == nod] = np.nan
    a[a < -1000] = np.nan
    h, w = a.shape
    # Mittelpunkte der Pixel
    lats = tr.f + (np.arange(h) + 0.5) * tr.e
    lons = tr.c + (np.arange(w) + 0.5) * tr.a
    r = np.clip(np.floor((lat + 1 - lats) * n).astype(int), 0, n - 1)
    c = np.clip(np.floor((lons - lon) * n).astype(int), 0, n - 1)
    a = np.where(np.isfinite(a), a, -np.inf)
    # je Zeile/Spalte die Pixel zusammenfassen (Indizes sind aufsteigend)
    rs = np.flatnonzero(np.r_[True, r[1:] != r[:-1]])
    cs = np.flatnonzero(np.r_[True, c[1:] != c[:-1]])
    m1 = np.maximum.reduceat(a, rs, axis=0)
    m2 = np.maximum.reduceat(m1, cs, axis=1)
    out = np.full((n, n), -np.inf)
    out[np.ix_(r[rs], c[cs])] = m2
    # Zellen ohne eigenes Pixel (feinere Ausgabe als Eingabe, z. B. über 60° N): Nachbarwert übernehmen
    if not np.isfinite(out).all():
        for i in range(n):
            for j in range(n):
                if not np.isfinite(out[i, j]):
                    ii, jj = np.clip([i - 1, i + 2], 0, n), np.clip([j - 1, j + 2], 0, n)
                    blk = out[ii[0]:ii[1], jj[0]:jj[1]]
                    out[i, j] = np.max(blk[np.isfinite(blk)]) if np.isfinite(blk).any() else 0.0
    out = np.where(np.isfinite(out), out, 0.0)
    return np.clip(np.ceil(out), -500, 9000).astype(np.int16)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--aus", required=True)
    ap.add_argument("--lat", type=int, nargs=2, default=[35, 60])
    ap.add_argument("--lon", type=int, nargs=2, default=[-10, 30])
    ap.add_argument("--quelle", default=QUELLE)
    ap.add_argument("--threads", type=int, default=12)
    a = ap.parse_args(argv)

    jobs = [(la, lo) for la in range(a.lat[0], a.lat[1]) for lo in range(a.lon[0], a.lon[1])]

    def eine(job):
        la, lo = job
        nm = cop_name(la, lo)
        try:
            tif = netz.hole(f"{a.quelle.rstrip('/')}/{nm}/{nm}.tif", ok404=True, timeout=300)
        except RuntimeError as e:
            print(f"  {F.kachel_name(la, lo)}: Fehler {e}", flush=True)
            return job, None
        if tif is None:
            return job, "meer"
        return job, kachel_max(tif, la, lo)

    kacheln = {}
    for n, (job, k) in enumerate(netz.parallel(eine, jobs, threads=a.threads)):
        kacheln[job] = k
    kopf = {"lat0": a.lat[0], "lat1": a.lat[1], "lon0": a.lon[0], "lon1": a.lon[1], "n": N,
            "quelle": "Copernicus DEM GLO-30 (© DLR e.V. 2010–2014 und © Airbus Defence and Space GmbH 2014–2018, "
                      "bereitgestellt unter COPERNICUS durch die Europäische Union und die ESA)",
            "erzeugt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    k = F.schreibe_gelaende(a.aus, kopf, kacheln)
    print(f"geschrieben: {a.aus} · Land {k['kacheln_land']}, Meer {k['kacheln_meer']}, fehlt {k['kacheln_fehlt']}", flush=True)
    return 0 if k["kacheln_fehlt"] == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
