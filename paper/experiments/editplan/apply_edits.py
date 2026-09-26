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
# detector retrained with video frames; exp 2 and exp 3 rerun on it
rep(r"""and the paper reports the real-footage behaviour, including one clip the system declines.""",
    r"""and on two of three real clips the stated sigma is smaller than the spread between repeat analyses.""")
rep(r"""and one of three real clips is declined.""",
    r"""and on two of three real clips the stated sigma is too small.""")
rep(r"""a YOLO detector~\cite{jocher2023ultralytics} fine-tuned on cricket balls and a
classical detector""",
    r"""a YOLO detector~\cite{jocher2023ultralytics}, fine-tuned on photos of cricket, tennis and other
sports balls~\cite{kuznetsova2020open,lin2014coco} and on cricket video frames with YouTube-sourced frames
excluded~\cite{rfcricv2,rftracker}, and a classical detector""")
rep(r"""\CalAppSdY~cm. The size and flight tests were added after the retrained detector fired on a large round
object in one real clip;""",
    r"""\CalAppSdY~cm. The submitted detector weights were lost; the retrained detector adds cricket video frames to
the photos. The size and flight tests were added after an earlier photo-only retrain fired on a large round
object in one real clip;""")
rep(r"""The vertical error is larger
than in Experiment~1 because the detector's centroid on a motion-smeared ball is biased along the streak, a pixel-noise level nearer 2 to 3~px than the reference 1~px, and the propagated
sigma reflects it: the median""",
    r"""The stump-plane errors are below
Experiment~1's reference because the grid flies without drag, swing or spin, the setting in which
Experiment~1 gives \PhysOffMedY{} and \PhysOffMedZ~cm. The median""")
block(r"""Table~\ref{tab:real} reports the real clips without embellishment.""",
      r"""uncertainty is not yet a guarantee.""",
      r"""On the outdoor off-spinner of Table~\ref{tab:real} (reproj.\ \RealTestThreeReproj~px, \RealTestThreeTrack{}
tracked frames, \RealTestThreeSpeed~km/h) only the even-frame analysis sees the bounce; the other two fall back
to the flagged single-parabola fit, and all three return umpire's call. Their predictions differ by
\RealTestThreeSpreadY~cm laterally and \RealTestThreeSpreadZ~cm vertically, inside a stated sigma of
\RealTestThreeSigmaY{} and \RealTestThreeSigmaZ~cm: the clip supports little, and the output says so. Both
indoor clips are not out on the pitching test in all three analyses, the leg-spinner pitching
\RealTestFourPitchMin{} to \RealTestFourPitchMax~cm outside the leg line and the off-spinner, on a short net
whose fitted length is \RealTestFiveLength~m, \RealTestFivePitchMin{} to \RealTestFivePitchMax~cm outside it.
On both the stated sigma looks too small. The half-rate predictions of the leg-spinner differ by
\RealTestFourSpreadY~cm laterally against a stated \RealTestFourSigmaY~cm on the full track, and those of the
off-spinner by \RealTestFiveSpreadZ~cm vertically against \RealTestFiveSigmaZ~cm. Halving the frames should
make the halves differ by about twice the full-track sigma, not four times. The cross-validated model term
(Section~\ref{sec:coverage}) grows with the distance from bounce to stumps, only \RealTestFourContactX~m here,
and takes these sigmas to just \RealTestFourFullSigmaY{} and \RealTestFiveFullSigmaZ~cm. The halves' own,
larger sigmas do cover their disagreement. Three clips with one split each make this a weak test: it suggests
the full-track sigma is too small on two of the three, but cannot say by how much. Real footage also carries
errors the synthetic study does not model, a moving camera, occlusion by the batter and a net rather than a
pitch.""")
# cuts that pay for the dataset credits
rep(r"""then through the full pipeline on rendered clips, then
on real hand-held footage with a repeatability test (Section~\ref{sec:results}).""",
    r"""then through the full pipeline on rendered clips and
on real hand-held footage (Section~\ref{sec:results}).""")
rep(r"""umpire's-call bands used by ball tracking in the professional game are set out in the ICC playing
conditions~\cite{icc2023drs}.""",
    r"""umpire's-call bands of professional ball tracking are set out in the ICC playing
conditions~\cite{icc2023drs}.""")
rep(r"""Coverage is the fraction of deliveries whose absolute error lies within one,
two and three propagated sigmas.""",
    r"""Coverage is the fraction of errors within one,
two and three propagated sigmas.""")
rep(r"""so the decision band takes its $k$ from risk and not from a nominal
Gaussian.""",
    r"""so the band takes its $k$ from risk, not a nominal
Gaussian.""")
rep(r"""The reported release speed is an average over the arc, not the speed
at the hand.""",
    r"""The reported release speed is an arc average, not the speed
at the hand.""")
# long dataset urls in the references need to break at hyphens
rep("\\usepackage{url}", "\\usepackage[hyphens]{url}")
open(f"{d}/main.tex", "w").write(src)
with open(f"{d}/refs.bib", "a") as fh:
    fh.write("\n" + snip("bib.bib"))
print("applied")
