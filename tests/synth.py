"""Künstliche ICON-D2-Dateien (GRIB2, bz2) im Verzeichnisaufbau von opendata.dwd.de — für Tests ohne Netz.

Felder sind bekannte Funktionen der Höhe, damit die Umrechnung auf feste Höhen exakt nachgeprüft werden kann:
  Gelände  hs(lat, lon) = 300 + 600 · max(0, 1 − d/0,25°)   (ein Berg um 47,5° N / 9,5° E, Gipfel 900 m)
  u(z, s)  = 5 + 0,004 · z + 0,1 · s     [m/s]   z = Höhe MSL in m, s = Vorhersagestunde
  v(z, s)  = −3 + 0,002 · z               [m/s]
  t(z)     = 288,15 − 0,0065 · z          [K]
  Boden:   t_2m = 290 + 0,1 · s, td_2m = 280, pmsl = 101500 + 10 · s Pa, u_10m = 2, v_10m = 1, vmax_10m = 8 m/s
"""
from __future__ import annotations

import bz2
import os

import eccodes
import numpy as np

LAT0, LAT1, LON0, LON1, D = 47.0, 48.0, 9.0, 10.5, 0.02
NLAT = int(round((LAT1 - LAT0) / D)) + 1
NLON = int(round((LON1 - LON0) / D)) + 1


def gitter():
    la = LAT0 + np.arange(NLAT) * D
    lo = LON0 + np.arange(NLON) * D
    return np.meshgrid(la, lo, indexing="ij")


def gelaende():
    LA, LO = gitter()
    d = np.hypot(LA - 47.5, (LO - 9.5) * np.cos(np.radians(47.5)))
    return 300.0 + 600.0 * np.maximum(0.0, 1.0 - d / 0.25)


def hhl():
    """66 Halbflächen, 1 = oben, 66 = Boden (geländefolgend)."""
    dick = 20.0 * 1.07 ** np.arange(65)               # Schichtdicken von unten
    hagl = np.concatenate([[0.0], np.cumsum(dick)])   # 66 Werte, Boden zuerst
    hs = gelaende()
    return {k: hs + hagl[66 - k] for k in range(1, 67)}


def u_f(z, s): return 5.0 + 0.004 * z + 0.1 * s
def v_f(z, s): return -3.0 + 0.002 * z
def t_f(z): return 288.15 - 0.0065 * z


def grib(werte: np.ndarray) -> bytes:
    h = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        eccodes.codes_set(h, "Ni", NLON)
        eccodes.codes_set(h, "Nj", NLAT)
        eccodes.codes_set(h, "latitudeOfFirstGridPointInDegrees", LAT0)
        eccodes.codes_set(h, "longitudeOfFirstGridPointInDegrees", LON0)
        eccodes.codes_set(h, "latitudeOfLastGridPointInDegrees", LAT1)
        eccodes.codes_set(h, "longitudeOfLastGridPointInDegrees", LON1)
        eccodes.codes_set(h, "iDirectionIncrementInDegrees", D)
        eccodes.codes_set(h, "jDirectionIncrementInDegrees", D)
        eccodes.codes_set(h, "jScansPositively", 1)
        eccodes.codes_set(h, "bitsPerValue", 24)
        eccodes.codes_set_values(h, werte.astype(np.float64).ravel())
        return eccodes.codes_get_message(h)
    finally:
        eccodes.codes_release(h)


def schreibe(wurzel: str, lauf: str = "2026102412", schritte_3d=range(0, 49), schritte_2d=range(0, 49), ebenen=None):
    hh = lauf[8:]
    H = hhl()
    ebenen = ebenen or list(range(20, 66))
    def ablage(var, name, werte):
        d = os.path.join(wurzel, hh, var)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as f:
            f.write(bz2.compress(grib(werte)))
    pre = "icon-d2_germany_regular-lat-lon"
    for k in range(1, 67):
        ablage("hhl", f"{pre}_time-invariant_{lauf}_000_{k}_hhl.grib2.bz2", H[k])
    for s in schritte_3d:
        for k in ebenen:
            z = 0.5 * (H[k] + H[k + 1])
            ablage("u", f"{pre}_model-level_{lauf}_{s:03d}_{k}_u.grib2.bz2", u_f(z, s))
            ablage("v", f"{pre}_model-level_{lauf}_{s:03d}_{k}_v.grib2.bz2", v_f(z, s))
            ablage("t", f"{pre}_model-level_{lauf}_{s:03d}_{k}_t.grib2.bz2", t_f(z))
    one = np.ones((NLAT, NLON))
    for s in schritte_2d:
        ablage("t_2m", f"{pre}_single-level_{lauf}_{s:03d}_2d_t_2m.grib2.bz2", (290 + 0.1 * s) * one)
        ablage("td_2m", f"{pre}_single-level_{lauf}_{s:03d}_2d_td_2m.grib2.bz2", 280 * one)
        ablage("pmsl", f"{pre}_single-level_{lauf}_{s:03d}_2d_pmsl.grib2.bz2", (101500 + 10 * s) * one)
        ablage("u_10m", f"{pre}_single-level_{lauf}_{s:03d}_2d_u_10m.grib2.bz2", 2 * one)
        ablage("v_10m", f"{pre}_single-level_{lauf}_{s:03d}_2d_v_10m.grib2.bz2", 1 * one)
        if s > 0:
            ablage("vmax_10m", f"{pre}_single-level_{lauf}_{s:03d}_2d_vmax_10m.grib2.bz2", 8 * one)


PLAETZE_CSV = """id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,iso_country,iso_region,municipality,scheduled_service,icao_code,iata_code,gps_code,local_code,home_link,wikipedia_link,keywords
1,EDTX,small_airport,Testplatz Berg,47.5,9.5,1300,EU,DE,DE-BW,,no,EDTX,,EDTX,,,,
2,EDTY,medium_airport,Testplatz Tal,47.8,10.2,1000,EU,DE,DE-BY,,no,EDTY,,EDTY,,,,
3,EDTZ,small_airport,Außerhalb,52.3,10.5,300,EU,DE,DE-NI,,no,EDTZ,,EDTZ,,,,
4,DE-0001,heliport,Heli,47.6,9.6,1500,EU,DE,DE-BW,,no,,,,,,,
"""
