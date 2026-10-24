#!/usr/bin/env bash
# Befehl ausführen und das Ende der Ausgabe als Meldung (Annotation) am Lauf ablegen:
# bei Fehler als ::error, sonst als ::notice. So ist das Wichtigste auch ohne Öffnen des Protokolls sichtbar
# (Actions → Lauf → „Annotations“) und über die REST-Schnittstelle abrufbar.
set -uo pipefail
mkdir -p out
log="$(mktemp)"
PYTHONUNBUFFERED=1 "$@" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
zeilen=40
[ "$rc" -ne 0 ] && zeilen=60
msg="$(tail -n "$zeilen" "$log" | cut -c1-400 | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk '{printf "%s%%0A", $0}')"
titel="$(echo "$*" | cut -c1-80 | sed -e 's/%/%25/g' -e 's/:/%3A/g' -e 's/,/%2C/g')"
if [ "$rc" -ne 0 ]; then
  echo "::error title=Fehler bei ${titel}::${msg}"
else
  echo "::notice title=Ausgabe von ${titel}::${msg}"
fi
rm -f "$log"
exit "$rc"
