"""Pisten-Job (OurAirports) gegen eine künstliche runways.csv über einen lokalen Webserver: laden, umrechnen wie die App
bis 25j (parseRwyCsv), Datei schreiben, lesen, prüfen. Kein Netz zu OurAirports."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F, pisten as PI, pruefen as P  # noqa: E402
from tests.test_wind import server  # noqa: E402

KOPF = ('"id","airport_ref","airport_ident","length_ft","width_ft","surface","lighted","closed","le_ident","le_latitude_deg",'
        '"le_longitude_deg","le_elevation_ft","le_heading_degT","le_displaced_threshold_ft","he_ident","he_latitude_deg",'
        '"he_longitude_deg","he_elevation_ft","he_heading_degT","he_displaced_threshold_ft"\n')
ZEILEN = [
    '236176,2284,"EDVE",7546,148,"ASP",1,0,"08",52.318401,10.5421,273,85,985,"26",52.320297,10.575681,288,265,',
    '236177,2284,"EDVE",2953,98,"GRS",0,1,"08R",52.3174,10.5485,,85,,"26L",52.3182,10.5617,,265,',      # geschlossen
    '1,10,"EDXA",2000,30,"grass",0,0,"07L",,,,,,"25R",,,,,2500',                                        # Schwelle > Länge
    '2,11,"EDXB",,30,"ASP",0,0,"09",,,,,,"27",,,,,',                                                     # Länge unbekannt
    '3,12,"EDXC",1640.42,30,"ASP",0,0,"H1",,,,,,"N",,,,,',                                               # keine Richtungszahl
    '4,13,"EDXD",3281,30,"ASP",0,0,"00",,,,,,"37",,,,,',                                                 # außerhalb 01–36
    '5,14,"EDXE",1000,30,"CON",0,0,"18/36",,,,,10.5,"36",,,,,',                                          # parseInt("18/36") = 18
    '6,15,"DE-0001",2000,30,"ASP",0,0,"09",,,,,,"27",,,,,',                                              # keine vierstellige Kennung
    '7,16,"EDX",2000,30,"ASP",0,0,"09",,,,,,"27",,,,,',
    '8,17,"0A12",1001.64,30,"turf",0,0,"1",,,,,0.82,"19",,,,,',                                         # 305,3 m → 305; 0,82 ft
    '9,18,"EDXF",1000,30,"ASP",0,1,"09",,,,,,"27",,,,,',                                                 # nur geschlossen → leer
]
CSV = KOPF + "\n".join(ZEILEN) + "\n"


def test_umrechnung():
    P_ = PI.aufbereiten(CSV)
    assert P_["EDVE"] == [["08", 80, 2300, 2000, "ASP"], ["26", 260, 2300, 2300, "ASP"]], P_["EDVE"]
    assert P_["EDXA"] == [["07L", 70, 610, 610, "GRASS"], ["25R", 250, 610, 0, "GRASS"]], P_["EDXA"]
    assert P_["EDXB"] == [["09", 90, None, None, "ASP"], ["27", 270, None, None, "ASP"]], P_["EDXB"]
    assert P_["EDXC"] == [] and P_["EDXD"] == [] and P_["EDXF"] == []
    assert P_["EDXE"] == [["18/36", 180, 305, 302, "CON"], ["36", 360, 305, 305, "CON"]], P_["EDXE"]
    assert P_["0A12"] == [["1", 10, 305, 305, "TURF"], ["19", 190, 305, 305, "TURF"]], P_["0A12"]
    assert "DE-0001" not in P_ and "EDX" not in P_
    assert PI._js_runden(2.5) == 3 and PI._js_runden(304.5) == 305 and PI._js_zahl("") == 0 and PI._js_zahl("12abc") == 12
    print("ok: Umrechnung wie in der App")


def test_job_datei_pruefung():
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "oa")
        os.makedirs(w)
        # genug Plätze für die Mindestzahlen der Prüfung: künstliche Bahnen, dazu die Proben der Prüfung
        z = list(ZEILEN)
        proben = {"EDDH": [("05", 10663, 0), ("23", 10663, 0)], "EDDF": [("18", 13123, 0), ("36", 13123, 0)],
                  "EDVM": [("07", 4003, 0), ("25", 4003, 0)], "LOWI": [("08", 6562, 0), ("26", 6562, 0)]}
        for ic, rws in proben.items():
            z.append(f'0,0,"{ic}",{rws[0][1]},45,"{"CON" if ic == "EDDF" else "ASP"}",1,0,"{rws[0][0]}",,,,,,"{rws[1][0]}",,,,,')
        b36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i in range(26000):
            # „ED“ + Ziffer + Zeichen (ED0A …, kollidiert mit keiner echten Kennung oben), sonst „Q“ + drei Zeichen
            ic = f"ED{b36[i // 36]}{b36[i % 36]}" if i < 350 else "Q" + b36[i // 1296 % 36] + b36[i // 36 % 36] + b36[i % 36]
            z.append(f'{1000 + i},{i},"{ic}",{2000 + i % 500},30,"ASP",0,0,"{i % 18 + 1:02d}",,,,,,"{i % 18 + 19:02d}",,,,,')
        open(os.path.join(w, "runways.csv"), "w").write(KOPF + "\n".join(z) + "\n")
        s = server(w)
        try:
            q = f"http://127.0.0.1:{s.server_address[1]}/runways.csv"
            aus = os.path.join(tmp, "pisten.bin")
            alt = PI.netz.time.sleep
            PI.netz.time.sleep = lambda s_: None       # Wiederholungen der ersten (toten) Quelle abkürzen
            try:
                assert PI.main(["--aus", aus, "--quelle", "http://127.0.0.1:9/fehlt.csv", "--quelle", q, "--stand", "2026-10-26"]) == 0
            finally:
                PI.netz.time.sleep = alt
            d = open(aus, "rb").read()
            K = F.kopf_lesen(d, b"FCYR")
            assert K["stand"] == "2026-10-26" and "OurAirports" in K["quelle"] and K["format"] == "FCYR"
            assert F.lese_pisten(d, "EDVE") == [["08", 80, 2300, 2000, "ASP"], ["26", 260, 2300, 2300, "ASP"]]
            assert F.lese_pisten(d, "edve") == F.lese_pisten(d, "EDVE") and F.lese_pisten(d, "ZZZZ") in (None, [])
            assert P.pruefe_pisten(aus)
            # gleiche Eingabe → gleiche Datei (der Dienst lädt nur bei neuen Daten)
            aus2 = os.path.join(tmp, "pisten2.bin")
            assert PI.main(["--aus", aus2, "--quelle", q, "--stand", "2026-10-26"]) == 0
            assert open(aus2, "rb").read() == d
            # zerstörte Gruppe → Prüfung schlägt fehl (der Server behält die vorige Datei)
            g = K["gruppen"]["E"]
            kaputt = bytearray(d)
            kaputt[g["ab_byte"] + 20] ^= 0xFF
            open(aus2, "wb").write(bytes(kaputt))
            assert not P.pruefe_pisten(aus2)
            # falsche Spalten → Abbruch
            open(os.path.join(w, "runways.csv"), "w").write('"id","ident"\n1,"EDVE"\n')
            try:
                PI.main(["--aus", aus2, "--quelle", q, "--stand", "2026-10-26"])
                raise AssertionError("kein Fehler")
            except SystemExit as e:
                assert "unerwartete Spalten" in str(e)
        finally:
            s.shutdown()
        print("ok: Pisten-Job (OurAirports)")


if __name__ == "__main__":
    test_umrechnung()
    test_job_datei_pruefung()
