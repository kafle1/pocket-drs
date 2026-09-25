# applies the edit plan to a copy of the paper; build.sh makes the copy, never point this at paper/ itself
import os, sys
d = sys.argv[1]
S = os.path.dirname(os.path.abspath(__file__)) + "/"
if os.path.samefile(d, os.path.join(S, "..", "..")):
    sys.exit("refusing to edit the real paper")
src = open(f"{d}/main.tex").read()

def rep(old, new):
    global src
    assert src.count(old) == 1, f"not unique or missing: {old[:70]!r}"
    src = src.replace(old, new)

def block(start, end, new):
    global src
    i = src.index(start); j = src.index(end, i) + len(end)
    assert src.count(start) == 1
    src = src[:i] + new + src[j:]

snip = lambda n: open(S + n).read()
rep("Law 36 is widened to umpire's call wherever the estimate's own one-sigma bound reaches a decision boundary.",
    "Law 36 is widened to umpire's call wherever a guard band set from the risk of a false out reaches a decision boundary.")
rep("propagated bound is slightly optimistic, covering \\CovYOne\\% of lateral and \\CovZOne\\% of vertical errors at\none sigma, and the paper reports",
    "propagated sigma misses model error and covers \\CovBFitYOne\\% and \\CovBFitZOne\\% of errors at one sigma; a\ncross-validated model term raises this to \\CovBFullYOne\\% and \\CovBFullZOne\\%, and the paper reports")
rep("The stumps are $h_s = 0.711$~m high and\nthe outer edges of a three-stump set are $\\pm w_o = 0.132$~m",
    "The stumps are $h_s = 0.711$~m high, the bails reach $h_b = 0.724$~m, and\nthe outer edges of a three-stump set are $\\pm w_o = 0.1143$~m")
rep("$z^\\star \\leq h_s$ for the centre.", "$z^\\star \\leq h_b$ for the centre.")
block("The playing conditions~\\cite{icc2023drs} treat", "Section~\\ref{sec:kcurve} traces the curve.\n", snip("decision.tex"))
rep("so the estimator never receives the true camera.",
    "so the estimator never receives the true camera; the focal length is solved from the taps with $L$ fixed.")
rep("and the frame-interval jitter enters through $t$ and is\nsmall beside it. Rolling-shutter skew is the one electronic error source the stated uncertainty does not\naccount for.",
    "and the frame-interval jitter enters through $t$\n(Table~\\ref{tab:budget}). Rolling-shutter skew up to 30~ms changes neither accuracy nor coverage measurably\n(Section~\\ref{sec:coverage}).")
rep("a target 26~cm wide", "a target 23~cm wide")
rep("Frame rate has almost no effect from 30 to 240~Hz (\\FpsThirtyAgree\\% at 30~Hz), because the\nanchor is one well-determined event and the parabolas on either side are over-determined from a handful of\nframes.",
    "Frame rate has almost no effect on agreement from 30 to 240~Hz (\\FpsThirtyAgree\\% at 30~Hz), because\nthe anchor is one well-determined event and the parabolas on either side are over-determined from a handful\nof frames; the stated sigma, though, shrinks with the frame count while the model error does not.")
# redundant with the method, which cites each of these again where it is used
block("Camera pose from known points follows the PnP literature", "standard~\\cite{seber1989nonlinear}.\n\n", "")
# the per-length table moves to the supplement; the text already carries its numbers
block("\\begin{table*}[t]\n\\centering\n\\caption{Experiment 2.", "\\end{table*}\n\n", "")
rep("(Table~\\ref{tab:rendered}). The median", "(the per-length table is in the supplement). The median")
# no produced number backs this clause
rep(" in one\ndirection or the other, and the decisive-for-marginal cases lie within a few millimetres of a band edge.", " in one\ndirection or the other.")
block("\\subsection{Camera placement}", "film from behind the batter.\n", snip("cameras.tex"))
block("\\subsection{How far the stated uncertainty can be trusted}", "laterally and \\MedSigmaZ~cm vertically.\n", snip("budget.tex"))
block("\\subsection{The decision band}", "\\KTwoUmpInverse.\n", snip("guard.tex"))
block("\\textbf{The uncertainty is a first-order approximation.}", "the arc, not the speed at the hand.\n", snip("limits.tex"))
rep("The propagated uncertainty is slightly optimistic, is reported as such,\nand is used as the Laws use umpire's call,",
    "The propagated uncertainty misses model error; with a cross-validated model term and a guard band set\nfrom the risk of a false out it is used as the Laws use umpire's call,")
rep("As an instrument it is a measurement chain that\ninstalls nothing: artefacts the playing surface already carries, a covariance taken from pixels to a measurand\nthe camera never sees, and an acceptance band set by that covariance rather than a fixed tolerance.",
    "As an instrument it installs nothing: the playing\nsurface supplies the calibration, and the acceptance band comes from the stated uncertainty and a risk limit\nrather than a fixed tolerance.")
open(f"{d}/main.tex", "w").write(src)
with open(f"{d}/refs.bib", "a") as fh:
    fh.write("\n" + snip("bib.bib"))
print("applied")
