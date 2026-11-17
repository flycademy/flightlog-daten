#!/usr/bin/env bash
# Datei(en) als einzigen Stand in einen eigenen Zweig legen (überschreibt den vorigen Stand).
# Ab Build 25y nur verschlüsselt (Accountable Manager 17.11.2026: nur unsere Seite soll die Daten lesen können): jede Datei wird mit dem
# öffentlichen Prüfschlüssel aus FCY_PRUEFSCHLUESSEL verschlüsselt und als <datei>.v abgelegt; ohne Prüfschlüssel bricht
# das Skript ab. Den geheimen Teil des Prüfschlüssels hat nur, wer den Lauf zur Prüfung gestartet hat (nicht der Server).
# Ausnahme: --beschreibung (nur Beschreibungen *.json mit Größe, Prüfsumme und Fassung, z. B. das Lebenszeichen im Zweig „stand“).
# Arbeitet in einem eigenen Arbeitsverzeichnis (git worktree): der Checkout des Jobs bleibt unverändert,
# das Skript kann im selben Lauf mehrmals aufgerufen werden.
#   bash werkzeug/ergebnis.sh ZWEIG DATEI…
#   bash werkzeug/ergebnis.sh --beschreibung ZWEIG BESCHREIBUNG.json…
set -euo pipefail
nur_beschreibung=0
if [ "${1:-}" = "--beschreibung" ]; then nur_beschreibung=1; shift; fi
zweig="$1"; shift
schl=""
if [ "$nur_beschreibung" = 1 ]; then
  for f in "$@"; do
    case "$f" in *.json) ;; *) echo "--beschreibung: nur *.json, nicht $f" >&2; exit 1 ;; esac
    python - "$f" <<'P'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
erlaubt = {"datei", "klar", "art", "groesse", "sha256", "klar_groesse", "klar_sha256", "schluessel", "fassung", "veroeffentlicht"}
if not isinstance(d, dict) or set(d) - erlaubt:
    raise SystemExit(f"{sys.argv[1]}: mehr als eine Beschreibung ({sorted(set(d) - erlaubt)})")
P
  done
else
  if [ -z "${FCY_PRUEFSCHLUESSEL:-}" ]; then
    echo "::error title=Ergebnis nicht abgelegt::Ohne Prüfschlüssel (Eingabe „pruefschluessel“) wird kein Ergebnis abgelegt — offen liegen keine Daten mehr im Repository."
    exit 1
  fi
  schl="$(mktemp)"
  printf '%s\n' "$FCY_PRUEFSCHLUESSEL" > "$schl"
fi
wt="$(mktemp -d)"
lokal="_ergebnis_$$_$(date +%s%N)"          # eigener lokaler Name, damit mehrere Aufrufe im selben Lauf gehen
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git worktree add -q --detach "$wt" HEAD
(
  cd "$wt"
  git checkout -q --orphan "$lokal"
  git rm -rfq . || true
  git clean -fdxq || true
)
namen=()
for f in "$@"; do
  if [ "$nur_beschreibung" = 1 ]; then
    cp "$f" "$wt/"; namen+=("$(basename "$f")")
  else
    python -m fcy_daten.schloss verschluesseln "$f" --aus "$wt/$(basename "$f").v" --schluessel "$schl"
    namen+=("$(basename "$f").v")
  fi
done
(
  cd "$wt"
  for n in "${namen[@]}"; do git add -f -- "$n"; done
  git commit -qm "Stand $(date -u +%Y-%m-%dT%H:%MZ) (Lauf ${GITHUB_RUN_ID:-lokal})"
  git push -fq origin "HEAD:refs/heads/$zweig"
)
git worktree remove --force "$wt"
git branch -D -q "$lokal" 2>/dev/null || true
[ -n "$schl" ] && rm -f "$schl"
exit 0
