#!/usr/bin/env bash
# Builds the TEI Guidelines reference with `opm odd document --guidelines` and
# drops it into docs/guidelines/, where the documentation build copies it
# verbatim: the site ends up served at /guidelines/. It is deliberately
# absent from the mkdocs.yml nav — static files are copied whether or not
# they are listed there — and linked from guide/odd-documentation.md.
#
# The output is generated, not tracked — .gitignore excludes /docs/guidelines/.
# Run this before `zensical build`/`zensical serve` if you want the subsite
# locally; the docs workflow runs it on every deployment.
#
# Usage: ./scripts/build_guidelines_docs.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Generating TEI Guidelines reference docs into $ROOT/docs/guidelines/"

# --guidelines pulls the TEI schema (specs plus Guidelines prose) into the user
# cache on first use, so the first run is slower and needs network access.
uv run --project "$ROOT" opm odd document --guidelines \
    -o "$ROOT/docs/guidelines" --force

echo "Wrote $ROOT/docs/guidelines"
