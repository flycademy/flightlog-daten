"""Gelände- und Orts-Job gegen künstliche Quelldateien."""
from __future__ import annotations

import io
import os
import struct
import sys
import tempfile
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F  # noqa: E402
from fcy_daten import gelaende, orte  # noqa: E402
from tests.test_wind import server  # noqa: E402


def tif(pfad, lat, lon, h, w, werte, nodata=None):
    tr = from_origin(lon, lat + 1, 1.0 / w, 1.0 / h)
    with rasterio.open(pfad, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32",
                       crs="EPSG:4326", transform=tr, nodata=nodata, compress="deflate") as ds:
        ds.write(werte.astype(np.float32), 1)


def test_gelaende():
    with tempfile.TemporaryDirectory() as tmp:
        q = os.path.join(tmp, "s3")
        # N52E010: 1200 × 800 Pixel (Seitenverhältnis wie zwischen 50 und 60° N), flach 50 m, Gipfel 777 m bei Pixel (605, 401)
        a = np.full((1200, 800), 50.0); a[605, 401] = 777.0; a[0:3, 0:3] = -32767.0   # Ecke ohne Daten
        nm = gelaende.cop_name(52, 10); os.makedirs(os.path.join(q, nm))
        tif(os.path.join(q, nm, nm + ".tif"), 52, 10, 1200, 800, a, nodata=-32767.0)
        # N51E010: 1200 × 1200, schräge Ebene 0 … 1199 m nach Osten
        b = np.tile(np.arange(1200, dtype=float), (1200, 1))
        nm = gelaende.cop_name(51, 10); os.makedirs(os.path.join(q, nm))
        tif(os.path.join(q, nm, nm + ".tif"), 51, 10, 1200, 1200, b)
        # N51E011: 3600 × 3600 wie GLO-30 bis 50° N, flach 20 m, Gipfel 999 m bei Pixel (1799, 1801)
        g = np.full((3600, 3600), 20.0); g[1799, 1801] = 999.0
        nm = gelaende.cop_name(51, 11); os.makedirs(os.path.join(q, nm))
        tif(os.path.join(q, nm, nm + ".tif"), 51, 11, 3600, 3600, g)
        s = server(q)
        aus = os.path.join(tmp, "g.bin")
        rc = gelaende.main(["--aus", aus, "--lat", "51", "53", "--lon", "10", "12", "--quelle", f"http://127.0.0.1:{s.server_address[1]}"])
        s.shutdown()
        assert rc == 0
        d = open(aus, "rb").read()
        k = F.kopf_lesen(d, b"FCYG")
        assert (k["kacheln_land"], k["kacheln_meer"], k["kacheln_fehlt"]) == (3, 1, 0)
        t = F.lese_gelaende_kachel(d, 52, 10)
        # Pixel (605, 401): Mitte bei 53 − 605,5/1200 → Zeile floor(605,5/10) = 60; Länge 401,5/800 → Spalte floor(60,225) = 60
        assert t[60, 60] == 777 and t[60, 61] == 50 and t[59, 60] == 50, t[58:62, 58:62]
        assert t.max() == 777 and t[0, 0] == 50
        assert F.lese_gelaende_kachel(d, 52, 11) == "meer"
        e = F.lese_gelaende_kachel(d, 51, 10)
        # Zelle j umfasst die Spalten 10j … 10j+9 → Maximum 10j + 9
        assert (e[0] == np.arange(120) * 10 + 9).all() and (e[:, 5] == 59).all()
        g = F.lese_gelaende_kachel(d, 51, 11)
        # 30 × 30 Pixel je Zelle: Zeile floor(1799,5/30) = 59, Spalte floor(1801,5/30) = 60
        assert g[59, 60] == 999 and g.max() == 999 and (g == 20).sum() == 120 * 120 - 1, g[58:61, 58:62]
        assert F.lese_gelaende_kachel(d, 50, 10) is None
        print("ok: Gelände")


def test_orte():
    with tempfile.TemporaryDirectory() as tmp:
        q = os.path.join(tmp, "gn"); os.makedirs(q)
        open(os.path.join(q, "admin1CodesASCII.txt"), "w").write("DE.06\tLower Saxony\tLower Saxony\t1\nDE.02\tBavaria\tBavaria\t2\n")
        rows = [
            ["2945024", "Braunschweig", "Braunschweig", "Brunswick,Brunsvicum", "52.26594", "10.52673", "P", "PPLA2", "DE", "", "06", "", "", "", "248292"],
            ["2867714", "Munich", "Munich", "Monaco di Baviera,München,Mnichov", "48.13743", "11.57549", "P", "PPLA", "DE", "", "02", "", "", "", "1260391"],
            ["2953416", "Bad Harzburg", "Bad Harzburg", "", "51.88268", "10.56157", "P", "PPL", "DE", "", "06", "", "", "", "21700"],
            ["6551111", "Waggum", "Waggum", "", "52.32", "10.55", "P", "PPLX", "DE", "", "06", "", "", "", "0"],
            ["2911111", "Brocken", "Brocken", "", "51.8", "10.6", "T", "MT", "DE", "", "06", "", "", "", "0"],
            ["2922222", "Steinhuder Meer", "Steinhuder Meer", "", "52.46", "9.34", "H", "LK", "DE", "", "06", "", "", "", "0"],
            ["2933333", "Altes Dorf", "Altes Dorf", "", "52.0", "10.0", "P", "PPLQ", "DE", "", "06", "", "", "", "0"],
        ]
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("DE.txt", "\n".join("\t".join(r + ["", "", "Europe/Berlin", "2026-01-01"]) for r in rows) + "\n")
        open(os.path.join(q, "DE.zip"), "wb").write(z.getvalue())
        alt = io.BytesIO()
        with zipfile.ZipFile(alt, "w") as zf:
            zf.writestr("alternateNamesV2.txt", "1\t2867714\tde\tMünchen\t1\t\t\t\t\t\n2\t2867714\tde\tMuenchen\t\t\t1\t\t\t\n"
                        "3\t2945024\ten\tBrunswick\t1\t\t\t\t\t\n4\t9999999\tde\tAnderswo\t1\t\t\t\t\t\n")
        open(os.path.join(q, "alternateNamesV2.zip"), "wb").write(alt.getvalue())
        s = server(q)
        aus = os.path.join(tmp, "o.bin")
        rc = orte.main(["--aus", aus, "--laender", "DE", "--quelle", f"http://127.0.0.1:{s.server_address[1]}"])
        s.shutdown()
        assert rc == 0
        d = open(aus, "rb").read()
        k = F.kopf_lesen(d, b"FCYO")
        idx = struct.unpack_from(f"<{k['anzahl']}I", d, k["index_ab"])
        keys = []
        for p in idx:
            e = d.index(b"\n", p)
            keys.append(d[p:e].split(b"\t"))
        ks = [x[0] for x in keys]
        assert ks == sorted(ks)
        kk = {x[0].decode(): x for x in keys}
        assert "munchen" in kk and "munich" in kk and "monaco di baviera" in kk and "baviera" in kk
        assert kk["munich"][2].decode() == "München" and kk["munchen"][2].decode() == "München"   # deutscher Name angezeigt
        assert "harzburg" in kk and kk["harzburg"][2].decode() == "Bad Harzburg" and kk["harzburg"][3].decode() == "Niedersachsen"
        assert "waggum" in kk and kk["waggum"][8] == b"X"
        assert "brocken" in kk and "steinhuder meer" in kk and "altes dorf" not in kk
        assert "brunswick" in kk           # über 20 000 Einwohner: andere Namen
        print("ok: Orte", len(ks), "Schlüssel")


if __name__ == "__main__":
    test_gelaende()
    test_orte()
