"""Höhenschichten und Schummerung der ICAO-Optik für ganz Deutschland aus Copernicus GLO-30.

Wie die Zwischenstufe Harz–Elbe (Build 25v, kacheln_v5.py): Höhen je Bildpunkt aus Copernicus, Schummerung von Nordwest
(Azimut 315°, Höhe 40°, Überhöhung 2,5) auf 60 m geglättet und auf die Tonwerte der Übungskarte (Schummerung des DGM200)
abgebildet, Gamma 0,8. Raster: Bildpunkte der Zoomstufe 12 in Web-Mercator (rund 24 m), dazu Stufen 11 bis 8 (Mittel aus 2 × 2).

Ausgabe im Arbeitsordner: gelaende.json (Raster) und je Stufe gelaende_z<z>_ft.u16 (Höhe ft) und gelaende_z<z>_dk.u8 (Schatten).
Aufruf: python -m fcy_daten.karte.gelaende --cop <Ordner mit Copernicus-Kacheln> --arbeit <Arbeitsordner>
Copernicus: „produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided
under COPERNICUS by the European Union and ESA; all rights reserved“.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import pickle

import numpy as np

E = 20037508.342789244
LON0, LON1, LAT0, LAT1 = 5.5, 15.5, 47.0, 55.2       # Deutschland mit Rand
STUFEN_FT = [-1000, 500, 1000, 1500, 2000, 3000, 5000]
BLOCK = 2048
RAND = 48


def px(lon, z):
    return (lon + 180) / 360 * 256 * 2 ** z


def py(lat, z):
    return (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * 256 * 2 ** z


def res(z):
    return 2 * E / (256 * 2 ** z)


def gitter(z=12):
    x0, x1 = int(math.floor(px(LON0, z))), int(math.ceil(px(LON1, z)))
    y0, y1 = int(math.floor(py(LAT1, z))), int(math.ceil(py(LAT0, z)))
    return {"z": z, "x0": x0, "y0": y0, "w": x1 - x0, "h": y1 - y0}


def _kacheln(ordner):
    import rasterio
    out = []
    for f in sorted(glob.glob(os.path.join(ordner, "*.tif"))):
        with rasterio.open(f) as r:
            out.append((f, r.bounds))
    return out


def _hoehe_block(kacheln, z, gx, gy, w, h):
    """Höhe (m) für die Bildpunkte gx … gx+w, gy … gy+h der Stufe z, bilinear aus allen berührten Copernicus-Kacheln."""
    import rasterio
    from rasterio.transform import Affine
    from rasterio.warp import reproject, Resampling
    r_ = res(z)
    xm0, ym0 = gx * r_ - E, E - gy * r_
    dst = np.full((h, w), np.nan, np.float32)
    lon0 = (gx / (256 * 2 ** z)) * 360 - 180; lon1 = ((gx + w) / (256 * 2 ** z)) * 360 - 180
    lat_ = lambda yy: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yy / (256 * 2 ** z)))))
    lat1, lat0 = lat_(gy), lat_(gy + h)
    for f, b in kacheln:
        if b.right < lon0 - 0.01 or b.left > lon1 + 0.01 or b.top < lat0 - 0.01 or b.bottom > lat1 + 0.01:
            continue
        with rasterio.open(f) as r:
            reproject(source=rasterio.band(r, 1), destination=dst, dst_transform=Affine(r_, 0, xm0, 0, -r_, ym0), dst_crs="EPSG:3857",
                      dst_nodata=np.nan, init_dest_nodata=False, resampling=Resampling.bilinear)
    return dst


def _roh_schatten(hm, lat):
    """Schattenwert 0…1 (vor der Tonwertabbildung) wie kacheln_v5.py: Glättung 60 m, Überhöhung 2,5, Licht 315°/40°."""
    from scipy.ndimage import gaussian_filter
    pix_m = res(12) * math.cos(math.radians(lat))
    g = gaussian_filter(np.nan_to_num(hm, nan=0.0), 60 / pix_m)
    ey, ex = np.gradient(2.5 * g, -pix_m, pix_m)
    az, al = np.radians(90 - 315), np.radians(40)
    I = (-ex * np.cos(az) * np.cos(al) - ey * np.sin(az) * np.cos(al) + np.sin(al)) / np.sqrt(ex ** 2 + ey ** 2 + 1)
    return np.clip((np.sin(al) - I) / np.sin(al), 0, 1).astype(np.float32)


def referenz_dgm200(dgm_npz):
    """Tonwertverteilung der Schummerung der Übungskarte (DGM200, Überhöhung 5, 315°/40°), für ganz Deutschland."""
    from matplotlib.colors import LightSource
    d = np.load(dgm_npz)
    a = d["hoehe_m"]; ok = np.isfinite(a)
    ls_ = LightSource(azdeg=315, altdeg=40)
    sh = ls_.hillshade(np.nan_to_num(a, nan=0.0), vert_exag=5, dx=200, dy=200)
    fl = ls_.hillshade(np.zeros((3, 3)), vert_exag=5, dx=200, dy=200)[1, 1]
    return np.sort(np.clip((fl - sh) / fl, 0, 1)[ok].ravel()).astype(np.float32)


def rechne(cop, arbeit, ref):
    import rasterio.features
    from rasterio.transform import Affine
    T = pickle.load(open(os.path.join(arbeit, "topo.pkl"), "rb"))
    de = T["de"].buffer(3000)
    G = gitter(12); W, H = G["w"], G["h"]
    kach = _kacheln(cop)
    ft = np.lib.format.open_memmap(os.path.join(arbeit, "gelaende_z12_ft.npy"), "w+", np.uint16, (H, W))
    roh = np.lib.format.open_memmap(os.path.join(arbeit, "_roh_z12.npy"), "w+", np.uint16, (H, W))
    hist = np.zeros(65536, np.int64)
    r_ = res(12)
    for by in range(0, H, BLOCK):
        for bx in range(0, W, BLOCK):
            w, h = min(BLOCK, W - bx), min(BLOCK, H - by)
            gx, gy = G["x0"] + bx - RAND, G["y0"] + by - RAND
            tr = Affine(r_, 0, gx * r_ - E, 0, -r_, E - gy * r_)
            m = ~rasterio.features.geometry_mask([de], (h + 2 * RAND, w + 2 * RAND), tr, all_touched=True)
            if not m.any():
                continue
            hm = _hoehe_block(kach, 12, gx, gy, w + 2 * RAND, h + 2 * RAND)
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (gy + h / 2) / (256 * 2 ** 12)))))
            rs = _roh_schatten(hm, lat)[RAND:RAND + h, RAND:RAND + w]
            hk = hm[RAND:RAND + h, RAND:RAND + w]; mk = m[RAND:RAND + h, RAND:RAND + w] & np.isfinite(hk)
            ft[by:by + h, bx:bx + w] = np.where(mk, np.clip(np.nan_to_num(hk, nan=0) * 3.28084, 0, 65000), 0).astype(np.uint16)
            q = (rs * 65535).astype(np.uint16)
            roh[by:by + h, bx:bx + w] = np.where(mk, q, 0)
            hist += np.bincount(q[mk].ravel(), minlength=65536)
            print(f"  Block {by // BLOCK},{bx // BLOCK}: {mk.mean() * 100:.0f} % in Deutschland", flush=True)
    ft.flush(); roh.flush()
    # Tonwertabbildung: Rang in Deutschland → Tonwert der Übungskarte; Gamma 0,8; als 0…255
    cdf = np.cumsum(hist).astype(np.float64); cdf = (cdf - hist / 2) / max(1, cdf[-1])
    lut = (np.interp(cdf, np.linspace(0, 1, ref.size), ref) ** 0.8 * 255).round().clip(0, 255).astype(np.uint8)
    dk = np.lib.format.open_memmap(os.path.join(arbeit, "gelaende_z12_dk.npy"), "w+", np.uint8, (H, W))
    for by in range(0, H, BLOCK):
        dk[by:by + BLOCK] = lut[roh[by:by + BLOCK]]
    dk.flush(); del roh
    os.remove(os.path.join(arbeit, "_roh_z12.npy"))
    # Stufen 11 … 8: Mittel aus 2 × 2
    for z in range(11, 7, -1):
        a = np.load(os.path.join(arbeit, f"gelaende_z{z + 1}_ft.npy"), mmap_mode="r")
        b = np.load(os.path.join(arbeit, f"gelaende_z{z + 1}_dk.npy"), mmap_mode="r")
        h2, w2 = a.shape[0] // 2, a.shape[1] // 2
        fa = np.lib.format.open_memmap(os.path.join(arbeit, f"gelaende_z{z}_ft.npy"), "w+", np.uint16, (h2, w2))
        fb = np.lib.format.open_memmap(os.path.join(arbeit, f"gelaende_z{z}_dk.npy"), "w+", np.uint8, (h2, w2))
        for r0 in range(0, h2, 1024):
            r1 = min(h2, r0 + 1024)
            aa = a[2 * r0:2 * r1, :2 * w2].astype(np.float32); bb = b[2 * r0:2 * r1, :2 * w2].astype(np.float32)
            fa[r0:r1] = (aa.reshape(r1 - r0, 2, w2, 2).mean(axis=(1, 3))).round().astype(np.uint16)
            fb[r0:r1] = (bb.reshape(r1 - r0, 2, w2, 2).mean(axis=(1, 3))).round().astype(np.uint8)
        fa.flush(); fb.flush()
    meta = {"z12": G, "stufen_ft": STUFEN_FT, "quelle": "Copernicus GLO-30", "kacheln": len(kach)}
    json.dump(meta, open(os.path.join(arbeit, "gelaende.json"), "w"))
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cop", required=True); ap.add_argument("--arbeit", required=True)
    a = ap.parse_args(argv)
    ref = referenz_dgm200(os.path.join(a.arbeit, "dgm200.npz"))
    print("Referenz DGM200:", ref.size, "Werte", flush=True)
    print(rechne(a.cop, a.arbeit, ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
