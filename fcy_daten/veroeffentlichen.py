"""Ergebnisdatei für den Flight Log veröffentlichen: als Download im Release „daten“ dieses Repositorys.

  python -m fcy_daten.veroeffentlichen out/wind.bin

Verschlüsselt (ab Build 25y, Accountable Manager 17.11.2026): Steht der öffentliche Schlüssel des Servers in fcy_daten/schluessel.pub,
legt der Job <datei>.v (siehe fcy_daten/schloss.py) und <datei>.v.json ab (Größe und SHA-256 der verschlüsselten Datei und
des Klartexts, Fingerabdruck des Schlüssels, Fassung). Lesen kann sie nur der Server des Flight Log.
Offen: <datei> und <datei>.json (Größe, SHA-256, Fassung), solange FCY_OFFEN nicht „nein“ ist (Übergang, bis Build 25y live
ist; danach entfallen die offenen Dateien). Hochgeladen mit der GitHub-CLI (GH_TOKEN = github.token, GITHUB_REPOSITORY aus
GitHub Actions). Der Datendienst des Flight Log (private/flightlog/dienst.php) holt sich die Dateien selbst; auf GitHub
liegt dafür kein Geheimnis.

Reihenfolge je Datei: zuerst die Datei, dann die Beschreibung. Der Dienst tauscht seine Datei nur aus, wenn Größe und
Prüfsumme zur Beschreibung passen; während des Austauschs auf GitHub behält er die vorige.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

from . import format as F
from . import schloss as S

TAG = "daten"
NOTIZ_V = ("Die Dateien *.v sind verschlüsselt; lesen kann sie nur der Server des FlyCademy Flight Log. ")
ARTEN = {b"FCYW": "wind", b"FCYG": "gelaende", b"FCYO": "orte", b"FCYL": "luftraum", b"FCYR": "pisten", b"FCYH": "hindernisse"}
NOTIZ = ("Automatisch erzeugte Daten für den FlyCademy Flight Log (training.flycademy.de/flightlog), abgeholt vom "
         "Datendienst des Flight Log. wind.bin: Höhenwind und Bodenwerte aus DWD ICON-D2 (Lauf alle 3 Stunden, Werte stündlich). "
         "gelaende.bin: produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH "
         "2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved (Höchstwert je 30″-Zelle, "
         "ergänzt um Gipfelhöhen aus GeoNames); the organisations in charge of the Copernicus programme by law or by "
         "delegation do not incur any liability for any use of the Copernicus WorldDEM-30. "
         "orte.bin: Ortsnamen aus GeoNames. "
         "luftraum.bin: Lufträume, Flugplätze und VFR-Meldepunkte Deutschlands aus open flightmaps (openflightmaps.org, "
         "OFMA General Users' License), laufender und nächster AIRAC-Zyklus; Fehler bitte an open flightmaps melden; "
         "nicht zertifiziert, nie Primärquelle für die Navigation. "
         "luftraum-dfs.bin (ab Build 25w): Lufträume Deutschlands aus DFS ED Airspace (aip.dfs.de/datasets), "
         "© DFS Deutsche Flugsicherung GmbH, CC BY 4.0; verändert: umgewandelt, Umrisse vereinfacht, Arten zusammengefasst; "
         "Flugplätze, VFR-Meldepunkte, Umriss Deutschlands sowie Naturschutz-, Segelflug- und Fallschirmsprunggebiete ohne "
         "Gegenstück bei der DFS aus open flightmaps (OFMA General Users' License). "
         "pisten.bin: Pistenrichtungen und -längen aus OurAirports (ourairports.com, gemeinfrei); maßgeblich ist die AIP. "
         "hindernisse.bin: Luftfahrthindernisse Deutschlands aus DFS ED Obstacles Area 1 (aip.dfs.de/datasets), "
         "© DFS Deutsche Flugsicherung GmbH, CC BY 4.0; verändert: umgewandelt, laufender und nächster AIRAC-Zyklus vereinigt. "
         "Quellen und Lizenzen: README des Repositorys.")


def beschreibung(pfad: str) -> dict:
    with open(pfad, "rb") as f:
        d = f.read()
    kennung = d[:4]
    if kennung not in ARTEN:
        raise SystemExit(f"{pfad}: unbekanntes Dateiformat {kennung!r}")
    k = F.kopf_lesen(d, kennung)
    return {"datei": os.path.basename(pfad), "art": ARTEN[kennung], "groesse": len(d),
            "sha256": hashlib.sha256(d).hexdigest(), "fassung": k.get("lauf") or k.get("erzeugt") or "",
            "veroeffentlicht": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def offen() -> bool:
    return os.environ.get("FCY_OFFEN", "").strip().lower() != "nein"


def _gh(*args: str, pruefen: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=pruefen, capture_output=not pruefen, text=True)


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 2
    pfad = argv[0]
    b = beschreibung(pfad)
    pk = S.oeffentlich_laden()
    if pk is None and not offen():
        raise SystemExit("weder offen (FCY_OFFEN = nein) noch verschlüsselt (kein Schlüssel in fcy_daten/schluessel.pub)")
    repo = os.environ.get("GITHUB_REPOSITORY", "flycademy/flightlog-daten")
    if _gh("release", "view", TAG, "-R", repo, pruefen=False).returncode != 0:
        r = _gh("release", "create", TAG, "-R", repo, "--title", "Daten für den Flight Log", "--notes", NOTIZ_V + NOTIZ,
                "--latest=false", pruefen=False)
        if r.returncode != 0 and _gh("release", "view", TAG, "-R", repo, pruefen=False).returncode != 0:
            raise SystemExit(f"Release „{TAG}“ ließ sich nicht anlegen: {r.stderr.strip()}")
    else:
        _gh("release", "edit", TAG, "-R", repo, "--notes", NOTIZ_V + NOTIZ, pruefen=False)   # Quellenhinweise aktuell halten
    if pk is not None:
        v = S.verschluesseln(pfad, pfad + ".v", pk)
        assert v["klar_sha256"] == b["sha256"] and v["klar_groesse"] == b["groesse"]
        bv = {"datei": b["datei"] + ".v", "klar": b["datei"], "art": b["art"], "groesse": v["groesse"], "sha256": v["sha256"],
              "klar_groesse": v["klar_groesse"], "klar_sha256": v["klar_sha256"], "schluessel": v["schluessel"],
              "fassung": b["fassung"], "veroeffentlicht": b["veroeffentlicht"]}
        with open(pfad + ".v.json", "w", encoding="utf-8") as f:
            json.dump(bv, f, ensure_ascii=False)
        _gh("release", "upload", TAG, pfad + ".v", "--clobber", "-R", repo)
        _gh("release", "upload", TAG, pfad + ".v.json", "--clobber", "-R", repo)
        print(f"veröffentlicht (verschlüsselt): {bv['datei']} ({bv['groesse']} Byte, Fassung {b['fassung']}, Schlüssel {v['schluessel']})")
    else:
        print("kein öffentlicher Schlüssel des Servers in fcy_daten/schluessel.pub — nur offen veröffentlicht")
    if offen():
        js = pfad + ".json"
        with open(js, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
        _gh("release", "upload", TAG, pfad, "--clobber", "-R", repo)
        _gh("release", "upload", TAG, js, "--clobber", "-R", repo)
        print(f"veröffentlicht (offen, Übergang): {b['datei']} ({b['groesse']} Byte, Fassung {b['fassung']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
