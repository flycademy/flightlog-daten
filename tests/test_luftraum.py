"""Luftraum-Job (open flightmaps) gegen künstliche OFMX-Daten über einen lokalen Webserver: Zyklusübersicht lesen, Archiv
laden, Lufträume/Flugplätze/Meldepunkte umwandeln, Datei schreiben, prüfen. Kein Netz zu open flightmaps."""
from __future__ import annotations

import io
import math
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F, luftraum as L, pruefen as P  # noqa: E402
from tests.test_wind import server  # noqa: E402

EDVE = (10.55888889, 52.31936111)


def kreis(lon, lat, r_nm, n=72):
    """Kreis im Uhrzeigersinn, geschlossen (wie die Shape-Extension)."""
    k = math.cos(math.radians(lat))
    pts = [(lon + r_nm / 60 * math.sin(2 * math.pi * i / n) / k, lat + r_nm / 60 * math.cos(2 * math.pi * i / n)) for i in range(n)]
    return pts + pts[:1]


def rechteck(lon0, lat0, lon1, lat1, schritt=0.1):
    """Rechteck mit vielen Zwischenpunkten auf den Kanten (wie vereinfachte Grenzverläufe)."""
    pts = []
    x = lon0
    while x < lon1:
        pts.append((x, lat1)); x += schritt
    y = lat1
    while y > lat0:
        pts.append((lon1, y)); y -= schritt
    x = lon1
    while x > lon0:
        pts.append((x, lat0)); x -= schritt
    y = lat0
    while y < lat1:
        pts.append((lon0, y)); y += schritt
    return pts + pts[:1]


def ase(mid, art, name, u=None, o=None, klasse=None, att="", extra=""):
    g = ""
    if u:
        g += f"<codeDistVerUpper>{o[0]}</codeDistVerUpper><valDistVerUpper>{o[1]}</valDistVerUpper><uomDistVerUpper>{o[2]}</uomDistVerUpper>"
        g += f"<codeDistVerLower>{u[0]}</codeDistVerLower><valDistVerLower>{u[1]}</valDistVerLower><uomDistVerLower>{u[2]}</uomDistVerLower>"
    typ = f"<codeType>{art}</codeType>" if art else "<codeType />"
    return (f'<Ase>\r\n<AseUid mid="{mid}" region="ED">{typ}<codeId>{mid[:7]}</codeId></AseUid><txtName>{name}</txtName>'
            + (f"<codeClass>{klasse}</codeClass>" if klasse else "") + g + extra + att + "</Ase>\r\n")


def shape(mid, art, name, pts):
    pl = " ".join(f"{x:.8f},{y:.8f},0" for x, y in pts)
    return f'<Ase mid="{mid}"><AseUid mid="{mid}"><codeType>{art}</codeType><codeId>{name}</codeId></AseUid><gmlPosList>{pl}</gmlPosList></Ase>\r\n'


def ofmx(variante: int):
    A, S = [], []
    def lr(mid, art, name, pts, **kw):
        A.append(ase(mid, art, name, **kw))
        if pts:
            S.append(shape(mid, art or "", name, pts))
    lr("m-ctr-bs", "CTR", "BRAUNSCHWEIG", kreis(*EDVE, 5), u=("HEI", 0, "FT"), o=("ALT", 2200 if variante == 1 else 2500, "FT"), klasse="D")
    lr("m-tma-area", "TMA", "AREA", rechteck(6.0, 47.6, 14.0, 55.0, 0.5))                  # Sammel-Eintrag ohne Höhen
    lr("m-cls-c", "CLASS", "AREA", None, u=("STD", 100, "FL"), o=("STD", 660, "FL"), klasse="C")
    lr("m-cls-e", "CLASS", "AREA", None, u=("HEI", 2500, "FT"), o=("STD", 100, "FL"), klasse="E")
    lr("m-e-low", "", "BRAUNSCHWEIG", kreis(*EDVE, 12), u=("HEI", 1000, "FT"), o=("HEI", 2500, "FT"), klasse="E")
    lr("m-r", "R", "ED-R 1 (TEST)", kreis(10.0, 52.0, 3), u=("HEI", 0, "FT"), o=("STD", 100, "FL"),
       att="<Att><codeWorkHr>TIMSH</codeWorkHr><Timsh><codeTimeRef>UTC</codeTimeRef><dateValidWef>01-01</dateValidWef><dateValidTil>31-12</dateValidTil>"
           "<codeDay>MON</codeDay><codeDayTil>FRI</codeDayTil><timeWef>0700</timeWef><timeTil>1600</timeTil></Timsh>"
           "<txtRmkWorkHr>Zeiten\r\n   laut NOTAM</txtRmkWorkHr></Att>",
       extra="<codeSelAvbl>Y</codeSelAvbl><txtRmk>Zeile 1\r\n  Zeile   2</txtRmk>")
    lr("m-rmz", "RMZ", "TESTRMZ", kreis(11.0, 53.0, 4), u=("HEI", 0, "FT"), o=("ALT", 1000, "FT"),
       att="<Att><codeWorkHr>H24</codeWorkHr></Att>")
    lr("m-ohne-umriss", "TMZ", "OHNE UMRISS", None, u=("ALT", 3500, "FT"), o=("STD", 65, "FL"))
    lr("m-sector", "SECTOR", "LANGEN FIS", rechteck(7, 49, 9, 51), u=("HEI", 0, "FT"), o=("STD", 100, "FL"))
    lr("m-draft", "DRAFT", "ENTWURF", kreis(8, 50, 2), u=("HEI", 0, "FT"), o=("ALT", 3000, "FT"))
    lr("m-fir", "FIR", "BREMEN", rechteck(6.0, 47.6, 14.0, 55.0, 0.05), u=("HEI", 0, "FT"), o=("STD", 245, "FL"))
    adg = ('<Adg><AdgUid mid="g1"><AseUid mid="m-cls-c" region="ED"><codeType>CLASS</codeType><codeId>X_C</codeId></AseUid></AdgUid>'
           '<AseUidSameExtent mid="m-tma-area" region="ED"><codeType>TMA</codeType><codeId>X</codeId></AseUidSameExtent></Adg>\r\n'
           '<Adg><AdgUid mid="g2"><AseUid mid="m-cls-e" region="ED"><codeType>CLASS</codeType><codeId>X_E</codeId></AseUid></AdgUid>'
           '<AseUidSameExtent mid="m-tma-area" region="ED"><codeType>TMA</codeType><codeId>X</codeId></AseUidSameExtent></Adg>\r\n')
    ahp = ('<Ahp><AhpUid mid="a1" region="ED"><codeId>EDVE</codeId></AhpUid><txtName>BRAUNSCHWEIG</txtName><codeIcao>EDVE</codeIcao><codeGps>EDVE</codeGps>'
           '<codeType>AD</codeType><geoLat>52.31936111N</geoLat><geoLong>010.55888889E</geoLong><valElev>296</valElev><uomDistVer>FT</uomDistVer></Ahp>\r\n'
           '<Ahp><AhpUid mid="a2" region="ED"><codeId>NI999</codeId></AhpUid><txtName>KLINIKUM</txtName><codeGps>NI999</codeGps>'
           '<codeType>HP</codeType><geoLat>52.2N</geoLat><geoLong>010.5E</geoLong><valElev>250</valElev><uomDistVer>FT</uomDistVer></Ahp>\r\n'
           '<Ahp><AhpUid mid="a3" region="ED"><codeId>NI123</codeId></AhpUid><txtName>UL-WIESE</txtName><codeGps>NI123</codeGps>'
           '<codeType>UL</codeType><geoLat>52.40000000N</geoLat><geoLong>010.70000000E</geoLong><valElev>100</valElev><uomDistVer>M</uomDistVer></Ahp>\r\n')
    dpn = ('<Dpn><DpnUid mid="d1" region="ED"><codeId>N1</codeId><geoLat>52.40000000N</geoLat><geoLong>010.50000000E</geoLong></DpnUid>'
           '<AhpUidAssoc mid="a1" region="ED"><codeId>EDVE</codeId></AhpUidAssoc><codeType>VFR-MRP</codeType><txtName>NOVEMBER1</txtName></Dpn>\r\n'
           '<Dpn><DpnUid mid="d2" region="ED"><codeId>S</codeId><geoLat>52.20000000N</geoLat><geoLong>010.55000000E</geoLong></DpnUid>'
           '<AhpUidAssoc mid="a1" region="ED"><codeId>EDVE</codeId></AhpUidAssoc><codeType>VFR-RP</codeType><txtName>SIERRA</txtName></Dpn>\r\n')
    o = ('<?xml version="1.0" encoding="utf-8"?>\r\n<OFMX-Snapshot version="0.1" effective="2026-10-12T01:00:00Z" created="2026-10-12T01:00:00Z">\r\n'
         + "".join(A[:2]) + adg + "".join(A[2:]) + ahp + dpn + "</OFMX-Snapshot>\r\n")
    s = ('<?xml version="1.0" encoding="utf-8"?>\r\n<OFM-AixmPlugin type="airspaceShapeExtension" version="0.1">\r\n<!--Kommentar-->\r\n'
         + "".join(S) + "</OFM-AixmPlugin>\r\n")
    return o.encode("utf-8"), s.encode("utf-8")


def archiv(variante: int) -> bytes:
    o, s = ofmx(variante)
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ofmx_ed/isolated/ofmx_ed.ofmx", o)
        z.writestr("ofmx_ed/isolated/ofmx_ed_ofmShapeExtension.xml", s)
        z.writestr("ofmx_ed/embedded/ofmx_ed.ofmx", b"<OFMX-Snapshot/>")
        z.writestr("ofmx_ed/readme.pdf", b"%PDF")
    return b.getvalue()


def uebersicht(kennung, ab, bis, url, stand):
    return (f'<?xml version="1.0" encoding="utf-8"?><publications><nearCycles><cycle id="{kennung}" string="x" startValidity="{ab}" endValidity="{bis}" />'
            f'<cycle id="2609" startValidity="2026-09-03T00:00:00Z" endValidity="2026-10-01T00:00:00Z" /></nearCycles>'
            f'<section><product type="OFMX"><download id="8" name="ARINC ED" timestamp="{stand}" inProgress="False" URL="{url}x"></download>'
            f'<download id="8" name="OFMX ED" timestamp="{stand}" inProgress="False" URL="{url}"><variant /></download></product></section></publications>').encode()


def test_umwandlung_und_datei():
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "ofm")
        os.makedirs(os.path.join(w, "publicationServices"))
        for k, v in (("2610", 1), ("2611", 2)):
            os.makedirs(os.path.join(w, "live", k, "ofmx", "ed", "latest"))
            open(os.path.join(w, "live", k, "ofmx", "ed", "latest", "ofmx_ed.zip"), "wb").write(archiv(v))
        s = server(w)
        q = f"http://127.0.0.1:{s.server_address[1]}"
        open(os.path.join(w, "publicationServices", "ED_2610.xml"), "wb").write(
            uebersicht("2610", "2026-10-01T00:00:00Z", "2026-10-29T00:00:00Z", f"{q}/live/2610/ofmx/ed/latest/ofmx_ed.zip", "2026-10-12T01:34:00Z"))
        try:
            # 1) nur der laufende Zyklus veröffentlicht (ED_2611.xml fehlt → 404)
            aus = os.path.join(tmp, "luftraum.bin")
            assert L.main(["--aus", aus, "--quelle", q, "--jetzt", "2026-10-15T12:00:00Z"]) == 0
            d = open(aus, "rb").read()
            K = F.kopf_lesen(d, b"FCYL")
            assert [z["zyklus"] for z in K["zyklen"]] == ["2610"], K
            assert K["erzeugt"] == "2026-10-12T01:34:00Z" and K["lauf"] == "2610@2026-10-12T01:34:00Z" and "open flightmaps" in K["quelle"]
            I = F.lese_luftraum(d)
            n = {e["t"] + ":" + e["n"]: e for e in I["lr"]}
            # Sammel-Eintrag ohne Höhen, FIR, SECTOR, DRAFT und Luftraum ohne Umriss fehlen; CLASS hat den Umriss des TMA-Eintrags
            namen = sorted(e["t"] + ":" + e["n"] for e in I["lr"])
            assert namen == ["CLASS:AREA", "CLASS:AREA", "CLASS:BRAUNSCHWEIG", "CTR:BRAUNSCHWEIG", "R:ED-R 1 (TEST)", "RMZ:TESTRMZ"], namen
            c = [e for e in I["lr"] if e["n"] == "AREA"]
            assert {e["k"] for e in c} == {"C", "E"} and all(e["b"] == [600000, 4760000, 1400000, 5500000] for e in c), c
            ctr = n["CTR:BRAUNSCHWEIG"]
            assert ctr["u"] == ["HEI", 0, "FT"] and ctr["o"] == ["ALT", 2200, "FT"] and ctr["k"] == "D" and "z" not in ctr
            pts = F.umriss_aus(ctr["p"])
            assert 12 <= len(pts) <= 72 and P.im_umriss(*EDVE, pts) and not P.im_umriss(10.75, 52.32, pts)
            # Umriss nach Vereinfachen und Runden höchstens etwa 25 m neben dem Kreis
            k = math.cos(math.radians(EDVE[1]))
            fehler = max(abs(math.hypot((x - EDVE[0]) * k, y - EDVE[1]) * 60 - 5) for x, y in pts) * 1852
            assert fehler < 25, fehler
            assert n["CLASS:BRAUNSCHWEIG"]["u"] == ["HEI", 1000, "FT"]
            r = n["R:ED-R 1 (TEST)"]
            assert r["z"] == "TIMSH" and r["zt"] == "Mo–Fr 0700–1600 UTC" and r["zr"] == "Zeiten\nlaut NOTAM" and r["s"] == 1 and r["r"] == "Zeile 1\nZeile 2", r
            assert n["RMZ:TESTRMZ"]["z"] == "H24" and "zt" not in n["RMZ:TESTRMZ"]
            assert I["ad"] == [["EDVE", "BRAUNSCHWEIG", "AD", 52.31936, 10.55889, 296], ["NI123", "UL-WIESE", "UL", 52.4, 10.7, 328]], I["ad"]
            assert I["dp"] == [["N1", "NOVEMBER1", "VFR-MRP", 52.4, 10.5, "EDVE"], ["S", "SIERRA", "VFR-RP", 52.2, 10.55, "EDVE"]], I["dp"]
            assert len(I["de"]) == 1 and P.im_umriss(*EDVE, F.umriss_aus(I["de"][0])) and len(I["de"][0]) // 2 < 40   # vereinfacht
            assert I["zyklus"] == "2610" and I["ab"] == "2026-10-01T00:00:00Z" and I["bis"] == "2026-10-29T00:00:00Z" and I["quelle"] == "open flightmaps"
            # gleiche Eingabe → gleiche Datei
            aus2 = os.path.join(tmp, "luftraum2.bin")
            assert L.main(["--aus", aus2, "--quelle", q, "--jetzt", "2026-10-16T08:00:00Z"]) == 0
            assert open(aus2, "rb").read() == d
            # Prüfung (Mindestanzahlen und Stichproben auf die künstlichen Daten abgestimmt)
            P.LR_MIN = {"lr": 5, "ad": 2, "dp": 2, "arten": {"CTR": 1, "R": 1, "RMZ": 1}}
            P.LR_PROBEN = [("EDVE", "BRAUNSCHWEIG")]
            assert P.pruefe_luftraum(aus, "2026-10-15T12:00:00Z")
            assert not P.pruefe_luftraum(aus, "2026-11-02T12:00:00Z")      # Zyklus für den Tag fehlt
            # 2) nächster Zyklus veröffentlicht: beide in der Datei, je eigener Inhalt
            open(os.path.join(w, "publicationServices", "ED_2611.xml"), "wb").write(
                uebersicht("2611", "2026-10-29T00:00:00Z", "2026-11-26T00:00:00Z", f"{q}/live/2611/ofmx/ed/latest/ofmx_ed.zip", "2026-10-22T01:34:00Z"))
            assert L.main(["--aus", aus, "--quelle", q, "--jetzt", "2026-10-26T12:00:00Z"]) == 0
            d = open(aus, "rb").read()
            K = F.kopf_lesen(d, b"FCYL")
            assert [z["zyklus"] for z in K["zyklen"]] == ["2610", "2611"] and K["lauf"] == "2610@2026-10-12T01:34:00Z 2611@2026-10-22T01:34:00Z"
            a, b = F.lese_luftraum(d, "2610"), F.lese_luftraum(d, "2611")
            ca = next(e for e in a["lr"] if e["t"] == "CTR"); cb = next(e for e in b["lr"] if e["t"] == "CTR")
            assert ca["o"][1] == 2200 and cb["o"][1] == 2500 and F.lese_luftraum(d)["zyklus"] == "2611"
            assert P.pruefe_luftraum(aus, "2026-10-26T12:00:00Z") and P.pruefe_luftraum(aus, "2026-11-02T12:00:00Z")
            # 3) Prüfsumme eines Inhalts falsch → Prüfung schlägt fehl
            z = K["zyklen"][1]
            kaputt = bytearray(d); kaputt[z["ab_byte"] + 20] ^= 0xFF
            open(aus2, "wb").write(bytes(kaputt))
            assert not P.pruefe_luftraum(aus2, "2026-10-26T12:00:00Z")
            # 4) laufender Zyklus fehlt → Fehler (der Server behält die vorige Datei)
            try:
                L.main(["--aus", aus2, "--quelle", q, "--jetzt", "2026-12-01T12:00:00Z"])
                raise AssertionError("kein Fehler")
            except SystemExit as e:
                assert "nicht verfügbar" in str(e)
            # 5) nächster Zyklus unfertig (Archiv fehlt) → nur der laufende
            os.remove(os.path.join(w, "live", "2611", "ofmx", "ed", "latest", "ofmx_ed.zip"))
            alt = L.netz.time.sleep          # Wiederholungen mit Wartezeit — für den Test abkürzen
            L.netz.time.sleep = lambda s: None
            try:
                assert L.main(["--aus", aus2, "--quelle", q, "--jetzt", "2026-10-26T12:00:00Z"]) == 0
            finally:
                L.netz.time.sleep = alt
            assert [z["zyklus"] for z in F.kopf_lesen(open(aus2, "rb").read(), b"FCYL")["zyklen"]] == ["2610"]
        finally:
            s.shutdown()
        print("ok: Luftraum-Job (open flightmaps)")


def test_airac_und_geometrie():
    import datetime as dt
    U = dt.timezone.utc
    for t, k in (("2026-10-26", "2610"), ("2026-10-29", "2611"), ("2025-12-31", "2513"), ("2026-01-22", "2601"), ("2020-01-02", "2001"), ("2026-12-24", "2613"), ("2020-12-31", "2014")):
        assert L.zyklus(dt.datetime.fromisoformat(t).replace(tzinfo=U))[0] == k, (t, k)
    # Ring wird nicht zur Linie; Kodierung verlustfrei auf 1e-5 Grad
    r = kreis(10, 52, 2, 360)
    v = L.vereinfache(r, 0.0002)
    assert 20 <= len(v) < 360 and v[0] != v[-1]
    p, b = L.kodiere(v)
    assert all(abs(x - y) < 6e-6 for q1, q2 in zip(F.umriss_aus(p), v) for x, y in zip(q1, q2))
    assert b[0] < 1000000 < b[2] and b[1] < 5200000 < b[3]
    assert L._grad("52.31936111N") == 52.31936111 and L._grad("010.55888889E") == 10.55888889 and L._grad("001.5W") == -1.5 and L._grad("x") is None
    print("ok: AIRAC und Geometrie")


if __name__ == "__main__":
    test_airac_und_geometrie()
    test_umwandlung_und_datei()
