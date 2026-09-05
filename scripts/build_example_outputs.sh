#!/usr/bin/env bash
# Builds, for every example project, an EPUB (`opm transform -t epub`), a
# print PDF (`opm transform -t print` piped through Prince), a Typst PDF
# (`opm transform -t typst` piped through `typst compile`), and a DOCX
# (`opm transform -t docx`).
#
# Results land in examples/output/<project>/<stem>.{epub,print.pdf,typst.pdf,docx}.
# Intermediate `-t print`/`-t typst` HTML/Typst source is kept alongside the
# PDFs for inspection.
#
# Usage: ./scripts/build_example_outputs.sh [project ...]
#   With no arguments, builds every project below. Pass one or more project
#   names (docbook, jats, serafin, shakespeare) to build a subset.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# opm's own `example_names()` catalogue (the bundled examples picker) only
# lists directories under examples/ that carry an opm.toml, so this doesn't
# get mistaken for a 5th bundled example. .gitignore excludes it, and the
# wheel build hook skips it too (see hatch_build.py's _SKIP).
OUT_ROOT="$ROOT/examples/output"

# project name -> XML inputs, relative to examples/<project>/, space-separated.
# (Kept as a case statement rather than an associative array — the bash
# shipped with macOS is 3.2 and has no associative array support.)
project_inputs() {
    case "$1" in
        docbook)     echo "data/doc/quickstart.xml" ;;
        jats)        echo "data/article/hertziana-digital-editions.xml" ;;
        serafin)     echo "data/letters/serafin01.xml data/letters/serafin02.xml" ;;
        shakespeare) echo "data/F-ado.xml" ;;
        *)           return 1 ;;
    esac
}
ALL_PROJECTS="docbook jats serafin shakespeare"

projects=("$@")
if [ ${#projects[@]} -eq 0 ]; then
    projects=($ALL_PROJECTS)
fi

for tool in prince typst; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "error: '$tool' not found on PATH" >&2
        exit 1
    }
done

for project in "${projects[@]}"; do
    inputs="$(project_inputs "$project")" || {
        echo "error: unknown project '$project' (expected one of: $ALL_PROJECTS)" >&2
        exit 1
    }

    project_dir="$ROOT/examples/$project"
    out_dir="$OUT_ROOT/$project"
    mkdir -p "$out_dir"

    for rel_xml in $inputs; do
        stem="$(basename "$rel_xml" .xml)"
        echo "== $project/$stem =="

        (
            cd "$project_dir"

            echo "-> epub"
            uv run opm transform "$rel_xml" -t epub -o "$out_dir/$stem.epub"

            echo "-> print PDF (prince)"
            uv run opm transform "$rel_xml" -t print -o "$out_dir/$stem.print.html"
            # Print output carries img/@src relative to the source XML's own
            # directory (same convention EPUB packaging uses); --baseurl
            # points Prince there since the HTML itself now lives in $out_dir.
            xml_dir="$(cd "$(dirname "$rel_xml")" && pwd)"
            prince "$out_dir/$stem.print.html" -o "$out_dir/$stem.print.pdf" \
                --baseurl "file://$xml_dir/"

            echo "-> typst PDF"
            uv run opm transform "$rel_xml" -t typst -o "$out_dir/$stem.typ"
            typst compile "$out_dir/$stem.typ" "$out_dir/$stem.typst.pdf"

            echo "-> docx"
            uv run opm transform "$rel_xml" -t docx -o "$out_dir/$stem.docx"
        )
    done
done

echo "Done. Output in $OUT_ROOT"
