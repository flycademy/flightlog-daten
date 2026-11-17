"""Veröffentlichen: Beschreibung (Größe, SHA-256, Fassung) und Reihenfolge der GitHub-CLI-Aufrufe (gh durch ein
Protokollskript ersetzt): Release anlegen, wenn es fehlt; zuerst die Datei, dann die Beschreibung."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import format as F, schloss as S, veroeffentlichen as V  # noqa: E402


def test_veroeffentlichen():
    with tempfile.TemporaryDirectory() as tmp:
        datei = os.path.join(tmp, "orte.bin")
        F.schreibe_orte(datei, {"quelle": "Test", "erzeugt": "2026-10-24T21:00:00Z"},
                        [("braunschweig", "1", "Braunschweig", "Niedersachsen", "DE", 52.26, 10.52, 248292, "P", 0)])
        protokoll = os.path.join(tmp, "gh.log")
        gh = os.path.join(tmp, "gh")
        with open(gh, "w") as f:      # „release view“ schlägt beim ersten Mal fehl (Release fehlt), danach nicht
            f.write("#!/bin/sh\necho \"$*\" >> %s\n"
                    "if [ \"$1 $2\" = \"release view\" ] && [ ! -e %s/da ]; then exit 1; fi\n"
                    "if [ \"$1 $2\" = \"release create\" ]; then touch %s/da; fi\nexit 0\n" % (protokoll, tmp, tmp))
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        alt = os.environ["PATH"]
        os.environ["PATH"] = tmp + os.pathsep + alt
        os.environ["GITHUB_REPOSITORY"] = "flycademy/flightlog-daten"
        alt_schl = os.environ.get("FCY_SCHLUESSEL")
        os.environ["FCY_SCHLUESSEL"] = os.path.join(tmp, "fehlt.pub")   # ohne Schlüssel (auch wenn fcy_daten/schluessel.pub da ist)
        try:
            assert V.main([datei]) == 0
            assert V.main([datei]) == 0      # zweiter Lauf: Release ist da
        finally:
            os.environ["PATH"] = alt
            if alt_schl is None:
                os.environ.pop("FCY_SCHLUESSEL", None)
            else:
                os.environ["FCY_SCHLUESSEL"] = alt_schl
        b = json.load(open(datei + ".json", encoding="utf-8"))
        d = open(datei, "rb").read()
        assert b["groesse"] == len(d) and b["sha256"] == hashlib.sha256(d).hexdigest()
        assert b["art"] == "orte" and b["fassung"] == "2026-10-24T21:00:00Z" and b["datei"] == "orte.bin"
        z = [x.split(" ")[:3] for x in open(protokoll).read().splitlines()]
        assert z == [["release", "view", "daten"], ["release", "create", "daten"],
                     ["release", "upload", "daten"], ["release", "upload", "daten"],
                     ["release", "view", "daten"], ["release", "edit", "daten"],
                     ["release", "upload", "daten"], ["release", "upload", "daten"]], z
        assert "WorldDEM-30" in open(protokoll).read().splitlines()[5]   # Beschreibung mit dem Copernicus-Hinweis aktualisiert
        zeilen = open(protokoll).read().splitlines()
        assert zeilen[2].split(" ")[3].endswith("orte.bin") and zeilen[3].split(" ")[3].endswith("orte.bin.json")   # Datei vor Beschreibung
        print("ok: Veröffentlichen (offen, ohne Schlüssel)")


def _gh_falle(tmp, protokoll):
    gh = os.path.join(tmp, "gh")
    with open(gh, "w") as f:
        f.write("#!/bin/sh\necho \"$*\" >> %s\nexit 0\n" % protokoll)
    os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)


def test_verschluesselt():
    """25y: mit Schlüssel im Repository zusätzlich <datei>.v und .v.json; mit FCY_OFFEN = nein nur verschlüsselt."""
    with tempfile.TemporaryDirectory() as tmp:
        datei = os.path.join(tmp, "orte.bin")
        F.schreibe_orte(datei, {"quelle": "Test", "erzeugt": "2026-11-17T15:00:00Z"},
                        [("braunschweig", "1", "Braunschweig", "Niedersachsen", "DE", 52.26, 10.52, 248292, "P", 0)])
        S.main(["neu", os.path.join(tmp, "k")])
        kp = S.geheim_lesen(open(os.path.join(tmp, "k", "geheim.key")).read())
        alt = dict(os.environ)
        os.environ["PATH"] = tmp + os.pathsep + alt["PATH"]
        os.environ["FCY_SCHLUESSEL"] = os.path.join(tmp, "k", "oeffentlich.txt")
        try:
            for offen, erwartet in (("", ["orte.bin.v", "orte.bin.v.json", "orte.bin", "orte.bin.json"]),
                                    ("nein", ["orte.bin.v", "orte.bin.v.json"])):
                protokoll = os.path.join(tmp, "gh_" + (offen or "ja") + ".log")
                _gh_falle(tmp, protokoll)
                os.environ["FCY_OFFEN"] = offen
                for x in ("orte.bin.json", "orte.bin.v", "orte.bin.v.json"):
                    if os.path.exists(os.path.join(tmp, x)):
                        os.remove(os.path.join(tmp, x))
                assert V.main([datei]) == 0
                hoch = [os.path.basename(z.split(" ")[3]) for z in open(protokoll).read().splitlines() if z.startswith("release upload")]
                assert hoch == erwartet, (offen, hoch)
                bv = json.load(open(datei + ".v.json", encoding="utf-8"))
                d = open(datei, "rb").read(); dv = open(datei + ".v", "rb").read()
                assert bv["klar"] == "orte.bin" and bv["datei"] == "orte.bin.v" and bv["art"] == "orte"
                assert bv["groesse"] == len(dv) and bv["sha256"] == hashlib.sha256(dv).hexdigest()
                assert bv["klar_groesse"] == len(d) and bv["klar_sha256"] == hashlib.sha256(d).hexdigest()
                assert bv["schluessel"] == S.fp_hex(kp[32:]) and bv["fassung"] == "2026-11-17T15:00:00Z"
                assert S.entschluesseln(datei + ".v", kp) == d
                assert b"Braunschweig" not in dv
                assert os.path.exists(datei + ".json") == (offen != "nein")
            # weder offen noch Schlüssel: Abbruch
            os.environ["FCY_SCHLUESSEL"] = os.path.join(tmp, "fehlt.pub")
            os.environ["FCY_OFFEN"] = "nein"
            try:
                V.main([datei]); raise AssertionError("ohne Schlüssel und ohne offen veröffentlicht")
            except SystemExit:
                pass
        finally:
            os.environ.clear(); os.environ.update(alt)
        print("ok: Veröffentlichen (verschlüsselt, Übergang und nur verschlüsselt)")


if __name__ == "__main__":
    test_veroeffentlichen()
    test_verschluesselt()
