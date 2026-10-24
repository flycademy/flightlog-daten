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
from fcy_daten import format as F, veroeffentlichen as V  # noqa: E402


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
        try:
            assert V.main([datei]) == 0
            assert V.main([datei]) == 0      # zweiter Lauf: Release ist da
        finally:
            os.environ["PATH"] = alt
        b = json.load(open(datei + ".json", encoding="utf-8"))
        d = open(datei, "rb").read()
        assert b["groesse"] == len(d) and b["sha256"] == hashlib.sha256(d).hexdigest()
        assert b["art"] == "orte" and b["fassung"] == "2026-10-24T21:00:00Z" and b["datei"] == "orte.bin"
        z = [x.split(" ")[:3] for x in open(protokoll).read().splitlines()]
        assert z == [["release", "view", "daten"], ["release", "create", "daten"],
                     ["release", "upload", "daten"], ["release", "upload", "daten"],
                     ["release", "view", "daten"], ["release", "upload", "daten"], ["release", "upload", "daten"]], z
        zeilen = open(protokoll).read().splitlines()
        assert zeilen[2].split(" ")[3].endswith("orte.bin") and zeilen[3].split(" ")[3].endswith("orte.bin.json")   # Datei vor Beschreibung
        print("ok: Veröffentlichen")


if __name__ == "__main__":
    test_veroeffentlichen()
