"""Wind-Job gegen künstliche ICON-D2-Dateien (tests/synth.py): Umrechnung auf Höhen, Mittel, Zeit, Plätze, Dateiformat."""
from __future__ import annotations

import functools
import http.server
import os
import sys
import tempfile
import threading

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F  # noqa: E402
from fcy_daten import wind  # noqa: E402
from tests import synth  # noqa: E402

FT = 0.3048
KT = 1.943844


def server(wurzel):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=wurzel)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_wind_ende_zu_ende():
    with tempfile.TemporaryDirectory() as tmp:
        wurzel = os.path.join(tmp, "dwd")
        synth.schreibe(wurzel)
        csvp = os.path.join(tmp, "airports.csv")
        open(csvp, "w").write(synth.PLAETZE_CSV)
        s = server(wurzel)
        aus = os.path.join(tmp, "wind.bin")
        cache = os.path.join(tmp, "cache", "hhl.npz")
        rc = wind.main(["--aus", aus, "--quelle", f"http://127.0.0.1:{s.server_address[1]}",
                        "--jetzt", "2026-10-24T14:10:00", "--plaetze", csvp, "--threads", "8", "--hhl-cache", cache])
        assert rc == 0 and os.path.exists(cache)
        # zweiter Lauf mit den Flächenhöhen aus dem Zwischenspeicher (wie jeder Lauf nach dem ersten auf GitHub)
        aus2 = os.path.join(tmp, "wind2.bin")
        rc = wind.main(["--aus", aus2, "--quelle", f"http://127.0.0.1:{s.server_address[1]}",
                        "--jetzt", "2026-10-24T14:10:00", "--plaetze", csvp, "--threads", "8", "--hhl-cache", cache])
        s.shutdown()
        assert rc == 0
        daten = open(aus, "rb").read()
        d2 = open(aus2, "rb").read()
        k1, k2 = F.kopf_lesen(daten, b"FCYW"), F.kopf_lesen(d2, b"FCYW")
        assert d2[F.KOPF_BYTES:] == daten[F.KOPF_BYTES:] and {x: k1[x] for x in k1 if x != "erzeugt"} == {x: k2[x] for x in k2 if x != "erzeugt"}, \
            "Lauf mit Zwischenspeicher weicht ab"
        K = F.kopf_lesen(daten, b"FCYW")
        assert K["lauf"] == "2026-10-24T12:00:00Z"
        g = K["gitter"]
        assert (g["lat0"], g["lon0"], g["nlat"], g["nlon"]) == (47.0, 9.0, 11, 16), g
        hs = synth.gelaende()
        fehler = []
        geprueft = 0
        for i in range(g["nlat"]):
            for j in range(g["nlon"]):
                p = F.lese_wind_punkt(daten, i, j)
                lat, lon = g["lat0"] + i * 0.1, g["lon0"] + j * 0.1
                ni, nj = int(round((lat - synth.LAT0) / synth.D)), int(round((lon - synth.LON0) / synth.D))
                box = hs[max(0, ni - 2):ni + 3, max(0, nj - 2):nj + 3]
                for si, st in enumerate(K["schritte_h"]):
                    for ai, hft in enumerate(K["hoehen_ft"]):
                        z = hft * FT
                        anteil = float((box <= z).mean())
                        u, v, t = (int(x) for x in p[si, ai])
                        if anteil < 0.5:
                            if (u, v, t) != (F.FEHLT_I8,) * 3:
                                fehler.append(("sollte fehlen", i, j, st, hft, u, v, t))
                            continue
                        soll = (np.clip(np.rint(synth.u_f(z, st) * KT), -127, 127),
                                np.clip(np.rint(synth.v_f(z, st) * KT), -127, 127),
                                np.rint(synth.t_f(z) - 273.15))
                        if anteil == 1.0:
                            geprueft += 1
                            if (u, v, t) != tuple(int(x) for x in soll):
                                fehler.append(("Wert", i, j, st, hft, (u, v, t), soll))
        assert geprueft > 1000, geprueft
        assert not fehler, fehler[:10]
        # Plätze: EDTX (Berg, Modellhöhe am Gipfel), EDTY; EDTZ außerhalb; Hubschrauberplatz nicht
        assert K["plaetze"]["anzahl"] == 2
        a = F.lese_platz(daten, "EDTX")
        assert a is not None and F.lese_platz(daten, "EDTZ") is None
        ni, nj = int(round((47.5 - synth.LAT0) / synth.D)), int(round((9.5 - synth.LON0) / synth.D))
        korr = 0.0065 * (hs[ni, nj] - 1300 * FT)
        st = 7
        soll = [290 + 0.1 * st - 273.15 + korr, 280 - 273.15 + korr, (101500 + 10 * st) / 100, 2 * KT, 1 * KT, 8 * KT]
        assert np.allclose(a[st], soll, atol=0.051), (a[st], soll)
        assert np.isnan(a[0, 5])          # vmax_10m fehlt bei +0 h
        print(f"ok: {geprueft} Werte geprüft, Datei {len(daten)} Byte")


if __name__ == "__main__":
    test_wind_ende_zu_ende()
