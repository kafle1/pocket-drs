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
# the app changed after submission: pose refine, false-detection tests, and a paragraph saying so
rep("and keeping the lowest reprojection\nerror.",
    "and keeping the lowest reprojection\nerror, then refining that pose by least squares on the pixel residuals.")
rep("the clip's span is static clutter and is suppressed.",
    "the clip's span is static clutter and is suppressed, as is any candidate too large or too small for a\nball anywhere in the flight volume.")
rep("horizontal motion. The learned track is preferred.",
    "horizontal motion. An arc the flight model cannot fit to 12~px rms is discarded and the next best tried.\nThe learned track is preferred.")
rep("\\label{sec:setup}\n\n", "\\label{sec:setup}\n\n" + snip("changes.tex") + "\n")
# cuts that pay for the changes paragraph
rep(" This stage is not the contribution; it is the input\nthe reconstruction is given.", "")
rep(", which at 40~m/s is a\ndeceleration comparable to $g$~\\cite{robinson2013projectile};", ";")
rep("Twelve taps on the stumps and pitch corners are required. Detecting the stumps\nand creases automatically would remove the step and the tap error with it.",
    "Twelve taps are required; detecting the stumps and creases would remove them\nand their error.")
rep(" As an instrument it installs nothing: the playing\nsurface supplies the calibration, and the acceptance band comes from the stated uncertainty and a risk limit\nrather than a fixed tolerance.", "")
rep("A single phone behind the batter can reconstruct a cricket delivery in metres if it uses the one event a\npitched delivery contains. The bounce fixes a point on a known plane at a known instant, and with that anchor\nthe monocular projectile problem, ill-conditioned along the depth of a ball flying at the camera, becomes two\nover-determined linear problems joined by a restitution coefficient.",
    "A single phone behind the batter can reconstruct a cricket delivery in metres if it uses the bounce,\nwhich fixes a point on a known plane at a known instant.")
rep("The next step is real deliveries with instrumented truth, most simply a\nsecond synchronised phone at right angles.",
    "A second phone at right angles would supply it.")
rep("The pipeline, generator, renderer,\nexperiment scripts, raw results and the generators for every number, table and figure are at\n\\url{https://github.com/kafle1/pocket-drs} under AGPL-3.0; \\texttt{verify\\_claims.py} regenerates the\nnumbers and fails if the manuscript is stale.",
    "Code, raw results and the scripts that regenerate every number are at\n\\url{https://github.com/kafle1/pocket-drs} (AGPL-3.0).")
rep("A full toss, a clip cut before the pitch, or a camera position from which\nthe batter hides the contact falls back to the flagged single-parabola estimator.",
    "A full toss, or a contact cut off or hidden, falls back to the flagged\nsingle-parabola fit.")
rep("The system is a\ncoaching instrument that says how sure it is, not a substitute for a multi-camera rig.",
    "It is a coaching\ninstrument that says how sure it is, not a substitute for a multi-camera rig.")
# table II shows no fall up to 12 px, so "until it is large" claims a knee the data don't have
rep("Calibration tap error has little effect until it is large\n",
    "Calibration tap error has little effect across the range tested\n")
open(f"{d}/main.tex", "w").write(src)
with open(f"{d}/refs.bib", "a") as fh:
    fh.write("\n" + snip("bib.bib"))
print("applied")
