"""Ergebnisdatei für den Flight Log veröffentlichen: als Download im Release „daten“ dieses Repositorys.

  python -m fcy_daten.veroeffentlichen out/wind.bin

Legt daneben <datei>.json an (Größe, SHA-256, Fassung) und lädt beide mit der GitHub-CLI hoch (GH_TOKEN = github.token,
GITHUB_REPOSITORY aus GitHub Actions). Der Datendienst des Flight Log (private/flightlog/dienst.php) holt sich die
Dateien von dort; er braucht dafür weder Konto noch Zugangsdaten.

Reihenfolge: zuerst die Datei, dann die Beschreibung. Der Dienst tauscht seine Datei nur aus, wenn Größe und Prüfsumme
zur Beschreibung passen; während des Austauschs auf GitHub behält er die vorige.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

from . import format as F

TAG = "daten"
ARTEN = {b"FCYW": "wind", b"FCYG": "gelaende", b"FCYO": "orte", b"FCYL": "luftraum", b"FCYR": "pisten"}
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
         "pisten.bin: Pistenrichtungen und -längen aus OurAirports (ourairports.com, gemeinfrei); maßgeblich ist die AIP. "
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


def _gh(*args: str, pruefen: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=pruefen, capture_output=not pruefen, text=True)


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 2
    pfad = argv[0]
    b = beschreibung(pfad)
    js = pfad + ".json"
    with open(js, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False)
    repo = os.environ.get("GITHUB_REPOSITORY", "flycademy/flightlog-daten")
    if _gh("release", "view", TAG, "-R", repo, pruefen=False).returncode != 0:
        r = _gh("release", "create", TAG, "-R", repo, "--title", "Daten für den Flight Log", "--notes", NOTIZ,
                "--latest=false", pruefen=False)
        if r.returncode != 0 and _gh("release", "view", TAG, "-R", repo, pruefen=False).returncode != 0:
            raise SystemExit(f"Release „{TAG}“ ließ sich nicht anlegen: {r.stderr.strip()}")
    else:
        _gh("release", "edit", TAG, "-R", repo, "--notes", NOTIZ, pruefen=False)   # Beschreibung (Quellenhinweise) aktuell halten
    _gh("release", "upload", TAG, pfad, "--clobber", "-R", repo)
    _gh("release", "upload", TAG, js, "--clobber", "-R", repo)
    print(f"veröffentlicht: {b['datei']} ({b['groesse']} Byte, Fassung {b['fassung']}) → "
          f"https://github.com/{repo}/releases/download/{TAG}/{b['datei']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
