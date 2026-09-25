#!/bin/sh
# copies paper/ to a temp dir, applies the edit plan, compiles, and prints the page count
set -e
E=$(cd "$(dirname "$0")" && pwd)
P="$E/../.."
T=$(mktemp -d)
cp -R "$P/figures" "$P/tables" "$T/"
cp "$P/main.tex" "$P/numbers.tex" "$P/refs.bib" "$P"/IEEEtran.* "$T/"
python3 "$E/apply_edits.py" "$T"
cd "$T"
pdflatex -interaction=nonstopmode main >/dev/null || true
bibtex main >/dev/null || true
pdflatex -interaction=nonstopmode main >/dev/null || true
pdflatex -interaction=nonstopmode main >/dev/null || true
grep -E "Output written|Overfull|undefined" main.log || true
echo "edited paper: $T/main.pdf"
