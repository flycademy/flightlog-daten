"""Luftraum aus dem DFS-Datensatz (luftraum-dfs.bin) gegen künstliche AIXM-Daten: Arten, Namen, Grenzen, Bögen, Teile,
Zeitpläne, Ergänzung aus open flightmaps, Datei und Prüfung. Kein Netz zur DFS."""
from __future__ import annotations

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F, luftraum as L, luftraum_dfs as D, pruefen as P  # noqa: E402

EDVE = (10.55888889, 52.31936111)
KOPF = ('<?xml version="1.0" encoding="UTF-8"?>\n<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message" '
        'xmlns:aixm="http://www.aixm.aero/schema/5.1.1" xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xlink="http://www.w3.org/1999/xlink">\n')
FUSS = "</message:AIXMBasicMessage>\n"


def poslist(pts):
    return " ".join(f"{la} {lo}" for lo, la in pts)


def volumen(segmente, u, o, ref_u="SFC", ref_o="MSL", uom_u="FT", uom_o="FT", contrib=""):
    flaeche = ""
    if segmente:
        flaeche = ("<aixm:horizontalProjection><aixm:Surface><gml:patches><gml:PolygonPatch><gml:exterior><gml:Ring><gml:curveMember>"
                   f"<gml:Curve><gml:segments>{segmente}</gml:segments></gml:Curve></gml:curveMember></gml:Ring></gml:exterior>"
                   "</gml:PolygonPatch></gml:patches></aixm:Surface></aixm:horizontalProjection>")
    return (f"<aixm:AirspaceVolume><aixm:upperLimit uom=\"{uom_o}\">{o}</aixm:upperLimit><aixm:upperLimitReference>{ref_o}</aixm:upperLimitReference>"
            f"<aixm:lowerLimit uom=\"{uom_u}\">{u}</aixm:lowerLimit><aixm:lowerLimitReference>{ref_u}</aixm:lowerLimitReference>{flaeche}{contrib}</aixm:AirspaceVolume>")


def luftraum(uid, typ, kennung, name, vols, lokal="", klasse="", zp="", notes="", op="BASE"):
    k = f"<aixm:class><aixm:AirspaceLayerClass><aixm:classification>{klasse}</aixm:classification></aixm:AirspaceLayerClass></aixm:class>" if klasse else ""
    gc = "".join(f"<aixm:geometryComponent><aixm:AirspaceGeometryComponent><aixm:operation>{op}</aixm:operation><aixm:theAirspaceVolume>{v}"
                 "</aixm:theAirspaceVolume></aixm:AirspaceGeometryComponent></aixm:geometryComponent>" for v in vols)
    return (f"<message:hasMember><aixm:Airspace gml:id=\"a{uid}\"><gml:identifier codeSpace=\"urn:uuid:\">{uid}</gml:identifier>"
            f"<aixm:timeSlice><aixm:AirspaceTimeSlice gml:id=\"t{uid}\"><aixm:type>{typ}</aixm:type><aixm:designator>{kennung}</aixm:designator>"
            f"<aixm:localType>{lokal}</aixm:localType><aixm:name>{name}</aixm:name>{k}{zp}{notes}{gc}"
            "</aixm:AirspaceTimeSlice></aixm:timeSlice></aixm:Airspace></message:hasMember>\n")


def kreis_seg(lon, lat, r_nm):
    return (f"<gml:CircleByCenterPoint numArc=\"1\"><gml:pos>{lat} {lon}</gml:pos><gml:radius uom=\"NM\">{r_nm}</gml:radius>"
            "</gml:CircleByCenterPoint>")


def linie(pts):
    return f"<gml:GeodesicString><gml:posList>{poslist(pts)}</gml:posList></gml:GeodesicString>"


def zeitplan(*blaetter, beschreibung="TIMSH", bemerkung=""):
    ts = "".join(
        "<aixm:timeInterval><aixm:Timesheet>" + "".join(f"<aixm:{k}>{v}</aixm:{k}>" for k, v in b.items()) + "</aixm:Timesheet></aixm:timeInterval>"
        for b in blaetter)
    act = f"<aixm:activation><aixm:AirspaceActivation>{ts}<aixm:status>ACTIVE</aixm:status></aixm:AirspaceActivation></aixm:activation>" if blaetter else ""
    n = (f"<aixm:annotation><aixm:Note><aixm:propertyName>activation</aixm:propertyName><aixm:purpose>DESCRIPTION</aixm:purpose><aixm:translatedNote>"
         f"<aixm:LinguisticNote><aixm:note>{beschreibung}</aixm:note></aixm:LinguisticNote></aixm:translatedNote></aixm:Note></aixm:annotation>")
    if bemerkung:
        n += (f"<aixm:annotation><aixm:Note><aixm:propertyName>activation</aixm:propertyName><aixm:purpose>REMARK</aixm:purpose><aixm:translatedNote>"
              f"<aixm:LinguisticNote><aixm:note>{bemerkung}</aixm:note></aixm:LinguisticNote></aixm:translatedNote></aixm:Note></aixm:annotation>")
    return act + n


def bemerkung(txt):
    return (f"<aixm:annotation><aixm:Note><aixm:purpose>REMARK</aixm:purpose><aixm:translatedNote><aixm:LinguisticNote><aixm:note>{txt}"
            "</aixm:note></aixm:LinguisticNote></aixm:translatedNote></aixm:Note></aixm:annotation>")


def teil_ref(uid):
    return (f"<aixm:contributorAirspace><aixm:AirspaceVolumeDependency><aixm:dependency>FULL_GEOMETRY</aixm:dependency>"
            f"<aixm:theAirspace xlink:href=\"urn:uuid:{uid}\"/></aixm:AirspaceVolumeDependency></aixm:contributorAirspace>")


def rechteck(lon0, lat0, lon1, lat1):
    return [(lon0, lat0), (lon0, lat1), (lon1, lat1), (lon1, lat0), (lon0, lat0)]


def aixm() -> bytes:
    x = KOPF
    tag = dict(timeReference="UTC", startDate="SDLST", endDate="EDLST", day="WORK_DAY", startTime="05:00", endTime="19:30", daylightSavingAdjust="NO", excluded="NO")
    tag2 = dict(timeReference="UTC", startDate="SDLST", endDate="EDLST", day="SAT", startTime="07:00", endTime="18:30", daylightSavingAdjust="NO", excluded="NO")
    tag3 = dict(tag2, day="SUN")
    x += luftraum("u1", "CTR", "EDVE", "BRAUNSCHWEIG", [volumen(kreis_seg(*EDVE, 5), 0, 2200)], klasse="D",
                  zp=zeitplan(tag, tag2, tag3), notes=bemerkung("Aktivierung\n\t\t  per NOTAM möglich"))
    # ED-R mit Bogen (Mittelpunkt, Radius 3 NM, mathematische Winkel) und Linie zurück
    c = (10.9, 52.6)
    bogen = (f"<gml:ArcByCenterPoint numArc=\"1\"><gml:pos>{c[1]} {c[0]}</gml:pos><gml:radius uom=\"NM\">3</gml:radius>"
             "<gml:startAngle uom=\"deg\">0</gml:startAngle><gml:endAngle uom=\"deg\">180</gml:endAngle></gml:ArcByCenterPoint>")
    dlon = 3 / 60 / math.cos(math.radians(c[1]))
    x += luftraum("u2", "OTHER:R_AMC", "EDR99A", "TESTPLATZ A", [volumen(linie([(c[0] - dlon, c[1]), (c[0] - dlon, c[1] - 0.1), (c[0] + dlon, c[1] - 0.1), (c[0] + dlon, c[1])]) + bogen, 0, 100, uom_o="FL", ref_o="STD")],
                  zp=zeitplan(dict(timeReference="UTC", day="MON", dayTil="FRI", startTime="07:00", endTime="16:00", daylightSavingAdjust="YES", excluded="NO"),
                              bemerkung="Erweiterung per NOTAM"))
    x += luftraum("u3", "A", "EDVEPJA", "BRAUNSCHWEIG-WOLFSBURG/NIEDERSACHSEN", [volumen(kreis_seg(10.6, 52.33, 1), 0, 100, uom_o="FL", ref_o="STD")], lokal="PJA",
                  zp=zeitplan(dict(timeReference="UTC", day="SAT", startEvent="SR", endEvent="SS", daylightSavingAdjust="YES", excluded="NO"),
                              dict(timeReference="UTC", day="SUN", startEvent="SR", endEvent="SS", daylightSavingAdjust="YES", excluded="NO")))
    de = rechteck(6.0, 47.5, 14.5, 55.0)
    x += luftraum("u4", "CLASS", "EDCLEN", "DEUTSCHLAND OHNE ALPENGEBIET/GERMANY WITHOUT ALPINE AREA", [volumen(linie(de), 2500, 100, uom_o="FL", ref_o="STD")], klasse="E", zp=zeitplan(beschreibung="H24"))
    x += luftraum("u5", "CLASS", "EDCLG", "DEUTSCHLAND/GERMANY G", [volumen(linie(de), 0, 2500, ref_o="SFC")], klasse="G")
    x += luftraum("u6", "CLASS", "EDXXCLCA", "TESTSTADT A", [volumen(linie(rechteck(10.3, 52.2, 10.8, 52.5)), 2500, 65, ref_u="MSL", uom_o="FL", ref_o="STD")], klasse="C")
    x += luftraum("u7", "PART", "EDXXTMZ1", "EDXXTMZ1", [volumen(linie(rechteck(11.0, 52.0, 11.2, 52.1)), 0, 5000)])
    x += luftraum("u8", "PART", "EDXXTMZ2", "EDXXTMZ2", [volumen(linie(rechteck(11.2, 52.0, 11.4, 52.1)), 1500, 5000, ref_u="MSL")])
    x += luftraum("u9", "RAS", "EDXXTMZ", "TESTSTADT", [volumen("", 0, 4500, contrib=teil_ref("u7")), volumen("", 1500, 4500, ref_u="MSL", contrib=teil_ref("u8"))],
                  lokal="TMZ", op="UNION", zp=zeitplan(beschreibung="HX"))
    x += luftraum("u10", "SECTOR", "EDWWTEST", "TESTSEKTOR", [volumen(linie(rechteck(9, 52, 10, 53)), 0, 100, uom_o="FL", ref_o="STD")])
    x += luftraum("u11", "PROTECT", "ETLFA01", "NIEDERSACHSEN", [volumen(linie(rechteck(8, 52, 9, 53)), 250, 1500, ref_o="SFC")], lokal="MIL LOW FLYING AREA")
    x += luftraum("u12", "OTHER:D_AMC", "EDD19A", "TODENDORF-PUTLOS A", [volumen(linie(rechteck(10.6, 54.3, 10.8, 54.4)), 0, 40000)], zp=zeitplan(beschreibung="NOTAM"))
    return (x + FUSS).encode("utf-8")


def ofm_datei(pfad: str):
    """luftraum.bin wie vom Job „Luftraum“ (open flightmaps): CTR (ersetzt), Fallschirmsprung gleich der DFS-Fläche (entfällt),
    Naturschutzgebiet und Segelfluggebiet ohne Gegenstück (bleiben, q = ofm)."""
    def e(t, n, pts, **k):
        p, b = L.kodiere(pts)
        return dict({"t": t, "n": n, "u": ["HEI", 0, "FT"], "o": ["ALT", 2000, "FT"], "p": p, "b": b}, **k)
    pja = [(lo, la) for lo, la in D._kreis((10.6, 52.33), 1852.0)]
    lr = [e("CTR", "BRAUNSCHWEIG", L.vereinfache(pja, 0.0002)),     # andere Fläche — wird trotzdem nicht übernommen (Art der DFS)
          e("HPGLDR", "PJE BRAUNSCHWEIG", L.vereinfache(pja, 0.0002)),
          e("NRA", "TESTMOOR 1", rechteck(10.0, 52.0, 10.1, 52.05)[:-1]),
          e("GLDR", "TESTSEGELFLUG", rechteck(10.2, 52.6, 10.4, 52.7)[:-1], k="D")]
    lr.sort(key=lambda x: (x["t"], x["n"], x["b"]))
    de, _ = L.kodiere(rechteck(6.0, 47.5, 14.0, 55.0)[:-1])   # Prag (14,26 E) außerhalb
    inhalt = {"zyklus": "2611", "ab": "2026-10-29T00:00:00Z", "bis": "2026-11-26T00:00:00Z", "stand": "2026-10-22T01:34:00Z", "quelle": "open flightmaps",
              "lr": lr, "ad": [["EDVE", "BRAUNSCHWEIG", "AD", 52.31936, 10.55889, 296], ["EDOV", "STENDAL", "AD", 52.62889, 11.81833, 184]],
              "dp": [["N1", "NOVEMBER1", "VFR-MRP", 52.4, 10.5, "EDVE"], ["S", "SIERRA", "VFR-RP", 52.2, 10.55, "EDVE"]], "de": [de]}
    F.schreibe_luftraum(pfad, {"quelle": "open flightmaps (OFMA General Users' License)", "region": "ED", "erzeugt": "2026-10-22T01:34:00Z",
                               "lauf": "2611@2026-10-22T01:34:00Z"}, [inhalt])


def test_uebersicht():
    html = ('<div>AIRAC 26 NOV 2026</div><a href="scripts/getItem.php?amdt=1&content=ED_Airspace_ReferencedBorders_2026-10-29_2026-11-26_revision.xml">'
            '<a href="scripts/getItem.php?amdt=1&content=ED_Airspace_StrokedBorders_2026-10-29_2026-11-26_revision.xml">')
    u = D.lies_uebersicht(html, 1)
    assert u == {"n": 1, "name": "ED_Airspace_StrokedBorders_2026-10-29_2026-11-26_revision.xml", "airac": "2026-11-26"}, u
    assert D.zyklus_von("2026-11-26") == "2612" and D.zyklus_von("2026-10-29") == "2611"
    assert D.lies_uebersicht("<div>keine Daten</div>", 0) is None
    print("ok: Übersicht der DFS")


def test_umwandlung_und_datei():
    with tempfile.TemporaryDirectory() as tmp:
        ofm, xml, aus = os.path.join(tmp, "luftraum.bin"), os.path.join(tmp, "ED_Airspace.xml"), os.path.join(tmp, "luftraum-dfs.bin")
        ofm_datei(ofm)
        open(xml, "wb").write(aixm())
        assert D.main(["--ofm", ofm, "--aus", aus, "--xml", f"2611={xml}"]) == 0
        d = open(aus, "rb").read()
        K = F.kopf_lesen(d, b"FCYL")
        assert "DFS" in K["quelle"] and "CC BY 4.0" in K["quelle"] and "open flightmaps" in K["quelle"], K["quelle"]
        I = F.lese_luftraum(d, "2611")
        n = {(e["t"], e["n"]): e for e in I["lr"]}
        arten = sorted(n)
        assert arten == [("CLASS", "AREA"), ("CTR", "BRAUNSCHWEIG"), ("D", "ED-D 19A TODENDORF-PUTLOS A"), ("GLDR", "TESTSEGELFLUG"),
                         ("HPGLDR", "BRAUNSCHWEIG-WOLFSBURG"), ("LFA", "LFA 1 NIEDERSACHSEN"), ("NRA", "TESTMOOR 1"), ("R", "ED-R 99A TESTPLATZ A"),
                         ("TMA", "TESTSTADT A"), ("TMZ", "TESTSTADT")], arten     # TMZ zweimal (zwei Teile), ohne Sektor und Luftraum G
        # Teile mit eigenen Grenzen
        tmz = [e for e in I["lr"] if e["t"] == "TMZ"]
        assert len(tmz) == 2 and sorted(e["u"] for e in tmz) == [["ALT", 1500, "FT"], ["HEI", 0, "FT"]] and all(e["o"] == ["ALT", 4500, "FT"] and e["z"] == "HX" and e["s"] == 1 for e in tmz), tmz
        # CTR: Kreis 5 NM (WGS84) bleibt nach Vereinfachen auf rund 25 m
        ctr = n[("CTR", "BRAUNSCHWEIG")]
        assert ctr["k"] == "D" and ctr["u"] == ["HEI", 0, "FT"] and ctr["o"] == ["ALT", 2200, "FT"] and "q" not in ctr and ctr["a"] == "EDVE"
        pts = F.umriss_aus(ctr["p"])
        G = D._geod()
        fehler = max(abs(G.inv(EDVE[0], EDVE[1], x, y)[2] - 5 * 1852) for x, y in pts)
        assert fehler < 25 and P.im_umriss(*EDVE, pts), fehler
        assert ctr["zt"] == "Sommer: werktags 05:00–19:30, Sa/So 07:00–18:30 UTC", ctr["zt"]
        assert ctr["z"] == "TIMSH" and ctr["s"] == 1 and ctr["r"] == "Aktivierung\nper NOTAM möglich", ctr
        # ED-R mit Bogen: Umriss reicht bis 3 NM nördlich des Mittelpunkts, Zeiten mit Sommerzeit-Ausgleich
        r = n[("R", "ED-R 99A TESTPLATZ A")]
        nord = max(y for _, y in F.umriss_aus(r["p"]))
        assert abs(G.inv(10.9, 52.6, 10.9, nord)[2] - 3 * 1852) < 40, nord
        assert r["o"] == ["STD", 100, "FL"] and r["zt"] == "Mo–Fr 07:00–16:00 UTC (während der Sommerzeit 1 Std früher)" and r["zr"] == "Erweiterung per NOTAM" and r["s"] == 1, r
        pja = n[("HPGLDR", "BRAUNSCHWEIG-WOLFSBURG")]
        assert pja["zt"] == "Sa/So SR–SS" and "q" not in pja, pja          # Ereignisse SR/SS: ohne UTC und ohne Sommerzeit-Hinweis
        assert n[("CLASS", "AREA")]["k"] == "E" and n[("CLASS", "AREA")]["u"] == ["HEI", 2500, "FT"] and "zt" not in n[("CLASS", "AREA")]
        assert n[("TMA", "TESTSTADT A")]["k"] == "C" and n[("TMA", "TESTSTADT A")]["u"] == ["ALT", 2500, "FT"]
        assert n[("D", "ED-D 19A TODENDORF-PUTLOS A")]["s"] == 1 and n[("LFA", "LFA 1 NIEDERSACHSEN")]["u"] == ["HEI", 250, "FT"]
        # aus open flightmaps nur, was die DFS nicht führt
        assert n[("NRA", "TESTMOOR 1")]["q"] == "ofm" and n[("GLDR", "TESTSEGELFLUG")]["q"] == "ofm"
        assert not any(e["n"] == "PJE BRAUNSCHWEIG" for e in I["lr"])
        assert I["ad"][0][0] == "EDVE" and len(I["dp"]) == 2 and len(I["de"]) == 1 and I["stand"] == "2026-10-22T01:34:00Z" and I["stand_lr"].startswith("2026-10-29")
        # gleiche Eingabe → gleiche Datei
        aus2 = os.path.join(tmp, "luftraum-dfs-2.bin")
        assert D.main(["--ofm", ofm, "--aus", aus2, "--xml", f"2611={xml}"]) == 0 and open(aus2, "rb").read() == d
        # Prüfung (Mindestanzahlen und Stichproben auf die künstlichen Daten abgestimmt)
        P.LR_MIN = {"lr": 5, "ad": 2, "dp": 2, "arten": {"CTR": 1, "R": 1, "TMZ": 1}}
        P.LR_DFS_MIN = {"CTR": 1, "TMA": 1, "R": 1}
        P.LR_PROBEN = [("EDVE", "BRAUNSCHWEIG")]
        assert P.pruefe_luftraum(aus, "2026-11-17T12:00:00Z", dfs=True)
        assert not P.pruefe_luftraum(ofm, "2026-11-17T12:00:00Z", dfs=True)      # luftraum.bin nennt die DFS nicht
        P.LR_DFS_MIN = {"CTR": 2}
        assert not P.pruefe_luftraum(aus, "2026-11-17T12:00:00Z", dfs=True)      # zu wenige CTR aus dem DFS-Datensatz
        # laufender Zyklus bei der DFS nicht verfügbar → Fehler
        try:
            D.main(["--ofm", ofm, "--aus", aus2, "--xml", f"2612={xml}"])
            raise AssertionError("kein Fehler")
        except SystemExit as e:
            assert "nicht verfügbar" in str(e), e
    print("ok: Luftraum aus dem DFS-Datensatz")


def test_zeitplan():
    t = lambda **k: dict({"timeReference": "UTC", "startDate": None, "endDate": None, "day": "ANY", "dayTil": None, "startTime": None,
                          "startEvent": None, "endTime": None, "endEvent": None, "daylightSavingAdjust": "NO", "excluded": "NO"}, **k)
    assert D.zeitplan_text([t(startTime="00:00", endTime="24:00")]) == "täglich ganztags"
    assert D.zeitplan_text([t(startDate="01-04", endDate="31-10", startTime="07:00", endTime="18:00")]) == "01.04.–31.10.: täglich 07:00–18:00 UTC"
    assert D.zeitplan_text([t(day="FRI", startTime="14:00", endEvent="SS", daylightSavingAdjust="YES"),
                            t(day="SAT", startEvent="SR", endEvent="SS", daylightSavingAdjust="YES")]) == "Fr 14:00–SS, Sa SR–SS UTC (während der Sommerzeit 1 Std früher)"
    assert D.zeitplan_text([t(day="HOL", startTime="00:00", endTime="24:00", excluded="YES"), t(day="WORK_DAY", startTime="06:00", endTime="20:00")]) \
        == "werktags 06:00–20:00, außer Feiertage ganztags UTC"
    assert D.zeitplan_text([]) is None
    assert D.grenze_app(("GND", "FT", "SFC")) == ["HEI", 0, "FT"] and D.grenze_app(("UNL", "FL", "STD")) == ["STD", 999, "FL"]
    assert D.grenze_app(("100", "M", "SFC")) == ["HEI", 100, "M"] and D.grenze_app(("4500", "FT", "MSL")) == ["ALT", 4500, "FT"]
    print("ok: Zeitpläne und Grenzen")


if __name__ == "__main__":
    test_uebersicht()
    test_zeitplan()
    test_umwandlung_und_datei()
