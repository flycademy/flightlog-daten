#!/usr/bin/env bash
# Lufträume aus open flightmaps für den Umriss Deutschlands (Jobs Hindernisse und Karte) selbst rechnen — ab Build 25y liegt
# luftraum.bin im Release nur noch verschlüsselt. Klappt das nicht (open flightmaps gerade ohne Datei für den laufenden Zyklus),
# die Fassung aus dem letzten erfolgreichen Lauf nehmen (Zwischenspeicher des Jobs, nicht öffentlich).
#   bash werkzeug/luftraum_umriss.sh AUS VORRAT
set -uo pipefail
aus="$1"; vorrat="$2"
mkdir -p "$(dirname "$aus")" "$(dirname "$vorrat")"
if python -m fcy_daten.luftraum --aus "$aus"; then
  cp "$aus" "$vorrat"
  exit 0
fi
if [ -s "$vorrat" ]; then
  cp "$vorrat" "$aus"
  echo "::warning title=Lufträume aus dem vorigen Lauf::open flightmaps gerade nicht verfügbar — Umriss Deutschlands aus dem letzten erfolgreichen Lauf"
  exit 0
fi
# Übergang (bis die offenen Dateien entfallen): die offene Datei aus dem Release
if curl -fsSL --retry 3 -o "$aus" "https://github.com/${GITHUB_REPOSITORY:-flycademy/flightlog-daten}/releases/download/daten/luftraum.bin"; then
  cp "$aus" "$vorrat"
  echo "::warning title=Lufträume aus dem Release::open flightmaps gerade nicht verfügbar — Umriss aus der offenen Datei im Release (Übergang)"
  exit 0
fi
echo "Lufträume weder von open flightmaps noch aus einem vorigen Lauf" >&2
exit 1
