"""Job „Karte“ (ab 25y): Bündel nur verschlüsselt (<bündel>.v), Verzeichnis karte-verzeichnis.bin mit Fingerabdruck und
Größe/Prüfsumme der verschlüsselten Bündel; ohne Schlüssel nichts veröffentlicht; Bündel älterer Zyklen werden übernommen,
offene Bündel und abgelaufene Zyklen im Release entfernt."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fcy_daten import schloss as S  # noqa: E402
from fcy_daten.karte import buendel as BU, lauf as L  # noqa: E402


def test_karte():
    with tempfile.TemporaryDirectory() as t:
        aus = os.path.join(t, "aus"); os.makedirs(aus)
        S.main(["neu", os.path.join(t, "k")])
        kp = S.geheim_lesen(open(os.path.join(t, "k", "geheim.key")).read())
        fp = S.fp_hex(kp[32:])
        dateien = {}
        for n in ("karte-2612-u.bin", "karte-2612-52-10.bin"):
            d = os.urandom(70000); open(os.path.join(aus, n), "wb").write(d)
            dateien[n] = {"groesse": len(d), "sha256": hashlib.sha256(d).hexdigest(), "n": 3}
        alt = {"zyklus": "2611", "ab": "2026-10-29", "bis": "2026-11-26", "dateien": {
            "karte-2611-u.bin": {"groesse": 5, "sha256": "0" * 64, "n": 1, "v": {"groesse": 150, "sha256": "1" * 64}}}}
        BU.verzeichnis_schreiben(os.path.join(aus, "karte.bin"), {"format": "FCYM", "zyklen": [alt, {
            "zyklus": "2612", "ab": "2026-11-26", "bis": "2026-12-24", "dateien": dateien}], "deckung": [[[10, 52], [11, 52], [11, 53]]]})
        prot = os.path.join(t, "gh.log"); gh = os.path.join(t, "gh")
        with open(gh, "w") as f:
            f.write("#!/bin/sh\necho \"$*\" >> %s\n"
                    "if [ \"$1 $2\" = \"release view\" ]; then printf 'karte-2611-u.bin.v\\nkarte-2612-u.bin\\nkarte-2609-u.bin.v\\nwind.bin.v\\n'; fi\nexit 0\n" % prot)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        envalt = dict(os.environ)
        os.environ["PATH"] = t + os.pathsep + envalt["PATH"]
        try:
            os.environ["FCY_SCHLUESSEL"] = os.path.join(t, "fehlt.pub")
            try:
                L.veroeffentlichen(aus); raise AssertionError("ohne Schlüssel veröffentlicht")
            except SystemExit:
                pass
            assert not os.path.exists(prot)
            os.environ["FCY_SCHLUESSEL"] = os.path.join(t, "k", "oeffentlich.txt")
            L.veroeffentlichen(aus)
        finally:
            os.environ.clear(); os.environ.update(envalt)
        z = [x.split(" ") for x in open(prot).read().splitlines()]
        hoch = [os.path.basename(x[3]) for x in z if x[:2] == ["release", "upload"]]
        assert hoch == ["karte-2612-u.bin.v", "karte-2612-52-10.bin.v", L.VERZ, L.VERZ + ".json"], hoch
        weg = [x[3] for x in z if x[:2] == ["release", "delete-asset"]]
        assert sorted(weg) == ["karte-2609-u.bin.v", "karte-2612-u.bin"], weg     # abgelaufen und offen
        v = BU.verzeichnis_lesen(os.path.join(aus, L.VERZ))
        assert v["schluessel"] == fp
        z12 = [q for q in v["zyklen"] if q["zyklus"] == "2612"][0]
        for n, d in z12["dateien"].items():
            pv = os.path.join(aus, n + ".v"); dv = open(pv, "rb").read()
            assert d["v"] == {"groesse": len(dv), "sha256": hashlib.sha256(dv).hexdigest()}
            assert S.entschluesseln(pv, kp) == open(os.path.join(aus, n), "rb").read()
        assert [q for q in v["zyklen"] if q["zyklus"] == "2611"][0]["dateien"]["karte-2611-u.bin"]["v"]["groesse"] == 150
        b = json.load(open(os.path.join(aus, L.VERZ + ".json")))
        dd = open(os.path.join(aus, L.VERZ), "rb").read()
        assert b["groesse"] == len(dd) and b["sha256"] == hashlib.sha256(dd).hexdigest() and b["schluessel"] == fp
        print("ok: Karte veröffentlichen (verschlüsselt)")


if __name__ == "__main__":
    test_karte()
