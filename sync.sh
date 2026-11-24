#!/usr/bin/env bash
# Regenerate the ICS feed, then commit and push it if it changed.
set -euo pipefail
cd "$(dirname "$0")"

set -a; . ./.env; set +a
.venv/bin/python generate_ics.py

git add docs
git diff --cached --quiet && { echo "No changes."; exit 0; }
git commit -q -m "Update lesson calendar feed"
git push -q origin HEAD
