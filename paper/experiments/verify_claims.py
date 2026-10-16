#!/usr/bin/env python
"""Check that the manuscript's numbers are the raw data's numbers.

1. Regenerates numbers.tex and every table from experiments/raw (make_numbers.py writes both) and fails if the committed
   copies differ, so a number in the text cannot be stale.
2. Scans main.tex for literal numbers with units in the results sections that are not
   macros, and lists them, so a hand-typed figure cannot creep in.
3. Confirms every macro used in main.tex is defined.

Usage:  python verify_claims.py     (exit code 1 on any failure)
"""
import filecmp
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)


def regenerate_and_compare():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(os.path.join(PAPER, "numbers.tex"), os.path.join(tmp, "numbers.tex"))
        tables_bak = os.path.join(tmp, "tables")
        shutil.copytree(os.path.join(PAPER, "tables"), tables_bak)
        subprocess.run([sys.executable, os.path.join(HERE, "make_numbers.py")], check=True, capture_output=True)
        if not filecmp.cmp(os.path.join(tmp, "numbers.tex"), os.path.join(PAPER, "numbers.tex"), shallow=False):
            print("FAIL numbers.tex was stale (now regenerated; rebuild the PDF)"); ok = False
        for f in os.listdir(tables_bak):
            if not filecmp.cmp(os.path.join(tables_bak, f), os.path.join(PAPER, "tables", f), shallow=False):
                print(f"FAIL tables/{f} was stale (now regenerated; rebuild the PDF)"); ok = False
    return ok


def macros_defined():
    defined = set(re.findall(r"\\newcommand\{\\(\w+)\}", open(os.path.join(PAPER, "numbers.tex")).read()))
    tex = open(os.path.join(PAPER, "main.tex")).read()
    used = set(re.findall(r"\\([A-Z][A-Za-z]+)\b", tex))
    missing = sorted(u for u in used if u not in defined and u[0].isupper() and u not in LATEX_BUILTIN)
    if missing:
        print("FAIL undefined macros:", ", ".join(missing))
    return not missing


LATEX_BUILTIN = {"IEEEPARstart", "IEEEkeywords", "Delta", "Phi", "Theta", "Big", "Bigl", "Bigr", "IEEEtran"}


def literal_numbers():
    tex = open(os.path.join(PAPER, "main.tex")).read()
    start = tex.find(r"\section{Results}")
    end = tex.find(r"\section{Limitations}")
    body = tex[start:end]
    body = re.sub(r"\\(ref|label|cite|includegraphics|input)\{[^}]*\}", "", body)
    body = re.sub(r"\$m\{=\}[0-9.]+\$", "", body)
    hits = re.findall(r"(?<![\w\\{])(\d+(?:\.\d+)?)\s*(?:~|\\%|%|\\,)?\s*(km/h|cm|mm|ms|Hz|px|m\b|s\b|\\%|%)", body)
    # sweep settings, risk limits, interval levels, the stump width and pitch geometry
    allowed = {"0.8", "1", "1.5", "2", "3", "5", "6", "8", "12", "20", "23", "30", "40", "60", "95", "120", "240"}
    flagged = sorted({n for n, _ in hits if n not in allowed})
    if flagged:
        print("WARN literal numbers in results (check each is a design constant, not a result):", ", ".join(flagged))
    return True


if __name__ == "__main__":
    ok = regenerate_and_compare()
    ok = macros_defined() and ok
    literal_numbers()
    print("verify_claims:", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)
