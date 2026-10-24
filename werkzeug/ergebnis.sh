#!/usr/bin/env bash
# Datei(en) als einzigen Stand in einen eigenen Zweig legen (überschreibt den vorigen Stand).
# Arbeitet in einem eigenen Arbeitsverzeichnis (git worktree): der Checkout des Jobs bleibt unverändert,
# das Skript kann im selben Lauf mehrmals aufgerufen werden.
#   bash werkzeug/ergebnis.sh ZWEIG DATEI…
set -euo pipefail
zweig="$1"; shift
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
for f in "$@"; do cp "$f" "$wt/"; done
(
  cd "$wt"
  for f in "$@"; do git add -f -- "$(basename "$f")"; done
  git commit -qm "Stand $(date -u +%Y-%m-%dT%H:%MZ) (Lauf ${GITHUB_RUN_ID:-lokal})"
  git push -fq origin "HEAD:refs/heads/$zweig"
)
git worktree remove --force "$wt"
git branch -D -q "$lokal" 2>/dev/null || true
