#!/usr/bin/env bash
# Ergebnisdatei(en) als einzigen Stand in einen eigenen Zweig legen (zur Prüfung, überschreibt den vorigen Stand)
set -euo pipefail
zweig="$1"; shift
tmp="$(mktemp -d)"
cp "$@" "$tmp/"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git checkout --orphan "$zweig"
git rm -rfq . || true
git clean -fdxq -e out -e cache || true
cp "$tmp"/* .
for f in "$@"; do git add -f -- "$(basename "$f")"; done
git commit -qm "Ergebnis $(date -u +%Y-%m-%dT%H:%MZ) (Lauf ${GITHUB_RUN_ID:-lokal})"
git push -fq origin "HEAD:$zweig"
