"""Hindernis-Job (DFS ED Obstacles Area 1) gegen künstliche AIXM-Dateien über einen lokalen Webserver: Übersicht lesen,
beide Zyklen laden und vereinigen, Abdeckung aus einem künstlichen luftraum.bin, Datei schreiben, lesen, prüfen.
Kein Netz zur DFS oder zu GitHub."""
from __future__ import annotations

import http.server
import os
import sys
import tempfile
import threading
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F, hindernisse as HI, luftraum as LR, pruefen as P  # noqa: E402


def teil(i, lat, lon, msl, agl, typ="WINDMILL", uom="FT"):
    return f"""<aixm:part><aixm:VerticalStructurePart gml:id="P{i}">
      <aixm:verticalExtent uom="{uom}">{agl}</aixm:verticalExtent><aixm:type>{typ}</aixm:type>
      <aixm:horizontalProjection_location><aixm:ElevatedPoint gml:id="E{i}" srsName="urn:ogc:def:crs:EPSG::4326">
        <gml:pos>{lat} {lon}</gml:pos><aixm:elevation uom="{uom}">{msl}</aixm:elevation></aixm:ElevatedPoint>
      </aixm:horizontalProjection_location></aixm:VerticalStructurePart></aixm:part>"""


def aixm(teile_je_struktur):
    s = []
    for j, (licht, teile) in enumerate(teile_je_struktur):
        s.append(f"""<message:hasMember><aixm:VerticalStructure gml:id="V{j}"><aixm:timeSlice>
          <aixm:VerticalStructureTimeSlice gml:id="T{j}"><aixm:interpretation>BASELINE</aixm:interpretation>
          <aixm:type>WINDMILL_FARMS</aixm:type><aixm:lighted>{licht}</aixm:lighted>{"".join(teile)}
          </aixm:VerticalStructureTimeSlice></aixm:timeSlice></aixm:VerticalStructure></message:hasMember>""")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message" '
            'xmlns:aixm="http://www.aixm.aero/schema/5.1.1" xmlns:gml="http://www.opengis.net/gml/3.2">'
            + "".join(s) + "</message:AIXMBasicMessage>").encode("utf-8")


# Zyklus 29.10.: zwei Windparks bei Braunschweig, ein Hindernis in Metern, eines außerhalb des Umrisses
Z0 = aixm([("YES", [teil(1, 52.40, 10.80, 1233.0, 788.0), teil(2, 52.41, 10.81, 1100.4, 650.0)]),
           ("NO", [teil(3, 52.10, 11.20, 300.0, 120.0, "TOWER", "M")]),
           ("NO", [teil(4, 50.30, 14.50, 900.0, 400.0, "ANTENNA")])])
# Zyklus 26.11.: Hindernis 1 höher vermessen, Hindernis 2 gestrichen, neues Hindernis 5
Z1 = aixm([("YES", [teil(1, 52.40, 10.80, 1240.0, 795.0)]),
           ("NO", [teil(3, 52.10, 11.20, 300.0, 120.0, "TOWER", "M")]),
           ("NO", [teil(5, 52.60, 11.70, 980.0, 650.0, "CHIMNEY")])])
N0 = "ED_Obstacles_Area_1_2026-10-01_2026-10-29_revision.xml"
N1 = "ED_Obstacles_Area_1_2026-10-29_2026-11-26_revision.xml"
SEITEN = {
    ("/scripts/getAmdtData.php", "amdt=0"): f'<h2 class="mt-5">AIRAC 29 OCT 2026</h2><a href="./scripts/getItem.php?amdt=0&content={N0}">AIXM 5.1</a>'.encode(),
    ("/scripts/getAmdtData.php", "amdt=1"): f'<h2 class="mt-5">AIRAC 26 NOV 2026</h2><a href="./scripts/getItem.php?amdt=1&content={N1}">AIXM 5.1</a>'.encode(),
    ("/scripts/getItem.php", f"amdt=0&content={N0}"): Z0,
    ("/scripts/getItem.php", f"amdt=1&content={N1}"): Z1,
}


class Dienst(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlsplit(self.path)
        d = SEITEN.get((u.path, u.query))
        self.send_response(200 if d is not None else 404)
        self.end_headers()
        self.wfile.write(d or b"")

    def log_message(self, *a):
        pass


def luftraum_bin(pfad):
    """künstliches luftraum.bin: Umriss „Deutschland“ = 51,3–53,7° N, 9,4–12,6° E (Kachel N52E010 und N52E011 ganz drin)"""
    p, _ = LR.kodiere([(9.4, 51.3), (12.6, 51.3), (12.6, 53.7), (9.4, 53.7), (9.4, 51.3)])
    F.schreibe_luftraum(pfad, {"lauf": "2611@test"}, [{"zyklus": "2611", "ab": "2026-10-29T00:00:00Z", "bis": "2026-11-26T00:00:00Z",
                                                       "lr": [], "ad": [], "dp": [], "de": [p]}])


def test_ende_zu_ende():
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Dienst)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            lr = os.path.join(tmp, "luftraum.bin"); luftraum_bin(lr)
            aus = os.path.join(tmp, "hindernisse.bin")
            q = f"http://127.0.0.1:{s.server_address[1]}"
            assert HI.main(["--aus", aus, "--quelle", q, "--umriss", lr]) == 0
            d = open(aus, "rb").read()
            K = F.kopf_lesen(d, b"FCYH")
            assert [z["airac"] for z in K["zyklen"]] == ["2026-10-29", "2026-11-26"] and K["format"] == "FCYH"
            assert K["anzahl"] == 5, K["anzahl"]          # 1 (höher), 2 (nur im laufenden Zyklus), 3, 4, 5
            k = F.lese_hindernis_kachel(d, 52, 10)
            assert k["a"] == "voll" and k["z"] == ["2026-10-29", "2026-11-26"]
            assert k["h"] == [[5240000, 1080000, 1240, 795, "WINDMILL", 1], [5241000, 1081000, 1101, 650, "WINDMILL", 1]], k["h"]
            k = F.lese_hindernis_kachel(d, 52, 11)
            assert k["a"] == "voll" and [5210000, 1120000, 985, 394, "TOWER", 0] in k["h"], k["h"]   # 300 m → 985 ft (aufgerundet)
            assert [5260000, 1170000, 980, 650, "CHIMNEY", 0] in k["h"]
            k = F.lese_hindernis_kachel(d, 50, 14)                                                    # außerhalb: nur das Hindernis
            assert k["a"] == "keine" and len(k["h"]) == 1 and not F.hindernis_zelle_gedeckt(k, 50.3, 14.5)
            assert F.lese_hindernis_kachel(d, 48, 14) is None
            k = F.lese_hindernis_kachel(d, 51, 9)                                                     # Rand: teils
            assert k["a"] == "teil" and F.hindernis_zelle_gedeckt(k, 51.5, 9.6) and not F.hindernis_zelle_gedeckt(k, 51.5, 9.3)
            assert not F.hindernis_zelle_gedeckt(k, 51.5, 9.4005)                                     # Zelle am Umriss: 300 m nach innen
            assert not F.hindernis_zelle_gedeckt(k, 51.2, 9.6)
            # Prüfung mit den Mindestwerten der künstlichen Daten
            alt = (P.HI_MIN, P.HI_PROBEN)
            P.HI_MIN = {"anzahl": 5, "kacheln": 5, "N52E010": 2}
            P.HI_PROBEN = [("Mitte", 52.4, 10.8, True), ("außen", 50.3, 14.5, False), ("Rand", 51.5, 9.3, False)]
            try:
                hoch = max(r[2] for la in range(47, 56) for lo in range(5, 16) for r in (F.lese_hindernis_kachel(d, la, lo) or {"h": []})["h"])
                assert hoch == 1240
                P.HI_MIN["anzahl"] = 5
                ok = P.pruefe_hindernisse(aus, "2026-11-15T12:00:00Z")
                assert not ok        # höchstes Hindernis 1240 ft < 3000 ft: die Prüfung der echten Daten schlägt hier an
                assert any("höchstes Hindernis 1240 ft" in z and z.startswith("❌") for z in P.ZEILEN)
                assert all(z.startswith("✅") for z in P.ZEILEN if "höchstes" not in z), [z for z in P.ZEILEN if not z.startswith("✅")]
                P.ZEILEN.clear()
                assert not P.pruefe_hindernisse(aus, "2026-12-30T12:00:00Z")      # Zyklus 29.10. gilt nicht mehr
                assert any("laufender Zyklus" in z and z.startswith("❌") for z in P.ZEILEN)
                P.ZEILEN.clear()
                # zerstörte Kachel → Prüfung schlägt fehl
                o, m = __import__("struct").unpack_from("<II", d, K["index_ab"] + ((52 - K["lat0"]) * (K["lon1"] - K["lon0"]) + (10 - K["lon0"])) * 8)
                kaputt = bytearray(d); kaputt[o + 12] ^= 0xFF
                aus2 = os.path.join(tmp, "kaputt.bin"); open(aus2, "wb").write(bytes(kaputt))
                assert not P.pruefe_hindernisse(aus2, "2026-11-15T12:00:00Z")
                P.ZEILEN.clear()
            finally:
                P.HI_MIN, P.HI_PROBEN = alt
            # gleiche Eingabe → gleiche Datei
            aus3 = os.path.join(tmp, "h3.bin")
            assert HI.main(["--aus", aus3, "--quelle", q, "--umriss", lr]) == 0 and open(aus3, "rb").read() == d
            # nächster Zyklus noch nicht veröffentlicht → nur der laufende
            alt1 = SEITEN.pop(("/scripts/getAmdtData.php", "amdt=1"))
            SEITEN[("/scripts/getAmdtData.php", "amdt=1")] = b'<h2 class="mt-5">AIRAC 26 NOV 2026</h2>'
            assert HI.main(["--aus", aus3, "--quelle", q, "--umriss", lr]) == 0
            K3 = F.kopf_lesen(open(aus3, "rb").read(), b"FCYH")
            assert [z["airac"] for z in K3["zyklen"]] == ["2026-10-29"] and K3["anzahl"] == 4
            SEITEN[("/scripts/getAmdtData.php", "amdt=1")] = alt1
            # laufender Zyklus ohne Datensatz → Abbruch (der Server behält die vorige Datei)
            alt0 = SEITEN[("/scripts/getAmdtData.php", "amdt=0")]
            SEITEN[("/scripts/getAmdtData.php", "amdt=0")] = b"<h2>Wartung</h2>"
            try:
                HI.main(["--aus", aus3, "--quelle", q, "--umriss", lr])
                raise AssertionError("kein Fehler")
            except SystemExit as e:
                assert "laufender Zyklus" in str(e)
            SEITEN[("/scripts/getAmdtData.php", "amdt=0")] = alt0
    finally:
        s.shutdown()
    print("ok: Hindernis-Job (DFS ED Obstacles Area 1)")


if __name__ == "__main__":
    test_ende_zu_ende()
