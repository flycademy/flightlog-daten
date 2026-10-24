"""Datei per FTPS in den Datenordner des Flight Log laden (private/flightlog/daten/ auf training.flycademy.de).

  python -m fcy_daten.hochladen out/wind.bin wx/wind.bin

Zugangsdaten aus den GitHub-Secrets FTP_HOST, FTP_USER, FTP_PASS (und optional FTP_DIR, FTP_PORT). Das FTP-Konto sollte
nur in den Datenordner schreiben dürfen (eigenes Konto in Plesk), dann ist mit diesen Secrets nichts anderes erreichbar.

Sind die Secrets noch gar nicht eingetragen, wird nur gewarnt (Lauf bleibt grün, keine Fehler-Mail alle 3 Stunden).
Sind sie eingetragen, aber falsch, schlägt der Lauf fehl.
"""
from __future__ import annotations

import os
import sys

from . import netz

FEHLT = ("Nicht hochgeladen: Die GitHub-Secrets FTP_HOST, FTP_USER und FTP_PASS sind noch nicht eingetragen "
         "(Settings → Secrets and variables → Actions).")


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 2:
        print(__doc__)
        return 2
    if not any(os.environ.get(k) for k in ("FTP_HOST", "FTP_USER", "FTP_PASS")):
        print(f"::warning title=Nicht hochgeladen::{FEHLT}")
        zusammenfassung = os.environ.get("GITHUB_STEP_SUMMARY")
        if zusammenfassung:
            with open(zusammenfassung, "a", encoding="utf-8") as f:
                f.write(f"\n**{FEHLT}**\n")
        return 0
    netz.hochladen(argv[0], argv[1])
    print(f"hochgeladen: {argv[0]} → {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
