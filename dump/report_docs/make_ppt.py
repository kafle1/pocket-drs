"""Build the PocketDRS final-defense presentation.

Reproducible: re-run to regenerate pocketdrs_presentation.pptx. Uses the
institutional BIT template theme for background/footer logos, but lays out every
slide with explicit, controlled geometry (section tag + title + accent rule +
one-line lead + body) so nothing clips or overlaps and every slide stands on its
own. Structured-approach order (Use-Case, ER, DFD, Architecture).

Design goals: clean, readable, self-explaining. Each content slide opens with a
single bold "lead" sentence (the message) followed by supporting bullets, is
labelled with a section tag for orientation, and is numbered. Requires
python-pptx + opencv.
"""

from __future__ import annotations

from pathlib import Path

import cv2
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

BASE = Path(__file__).resolve().parent
TEMPLATE = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/BIT Project PPT Sample.pptx")
FIG = BASE / "figures"
OUT = BASE / "pocketdrs_presentation.pptx"

NAVY = RGBColor(0x12, 0x33, 0x5B)   # titles, lead text
INK = RGBColor(0x22, 0x22, 0x22)    # body text
ACCENT = RGBColor(0x2E, 0x6F, 0xB5) # rules, tags, accents
MUTE = RGBColor(0x8A, 0x8A, 0x8A)   # slide numbers, captions

prs = Presentation(str(TEMPLATE))
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[10]

MARGIN = Inches(0.55)
TAG_TOP = Inches(0.48)              # sits clear below the template header bar
TAG_H = Inches(0.22)
TITLE_TOP = Inches(0.70)
TITLE_H = Inches(0.58)
RULE_TOP = Inches(1.28)
BODY_TOP = Inches(1.46)
FOOTER_RESERVE = Inches(0.92)       # room for the template footer logos
BODY_H = SH - BODY_TOP - FOOTER_RESERVE
CONTENT_W = SW - 2 * MARGIN

_slide_no = 0


def _new_slide():
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return s


def _add_number(slide) -> None:
    global _slide_no
    _slide_no += 1
    if _slide_no == 1:
        return  # no number on the title slide
    tb = slide.shapes.add_textbox(SW - MARGIN - Inches(0.7), SH - Inches(0.42),
                                  Inches(0.7), Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    p.text = str(_slide_no)
    p.alignment = PP_ALIGN.RIGHT
    p.font.size = Pt(9)
    p.font.color.rgb = MUTE


def _add_header(slide, title: str, tag: str | None) -> None:
    if tag:
        tb = slide.shapes.add_textbox(MARGIN, TAG_TOP, CONTENT_W, TAG_H)
        tf = tb.text_frame
        tf.auto_size = MSO_AUTO_SIZE.NONE
        p = tf.paragraphs[0]
        p.text = tag.upper()
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = ACCENT
    tb = slide.shapes.add_textbox(MARGIN, TITLE_TOP, CONTENT_W, TITLE_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = NAVY
    line = slide.shapes.add_shape(1, MARGIN, RULE_TOP, Inches(2.0), Pt(3))
    line.fill.solid(); line.fill.fore_color.rgb = ACCENT
    line.line.fill.background(); line.shadow.inherit = False
    _add_number(slide)


def content_slide(tag: str, title: str, lead: str, bullets: list[str]) -> None:
    """Section tag + title + one bold lead sentence + supporting bullets."""
    s = _new_slide()
    _add_header(s, title, tag)
    # Lead: the single message of the slide.
    lb = s.shapes.add_textbox(MARGIN, BODY_TOP, CONTENT_W, Inches(0.55))
    lf = lb.text_frame; lf.word_wrap = True
    lf.auto_size = MSO_AUTO_SIZE.NONE
    lp = lf.paragraphs[0]
    lp.text = lead
    lp.font.size = Pt(17); lp.font.bold = True; lp.font.color.rgb = NAVY
    lp.line_spacing = 1.02
    # Supporting bullets.
    body_top = BODY_TOP + Inches(0.56)
    tb = s.shapes.add_textbox(MARGIN, body_top, CONTENT_W, BODY_H - Inches(0.56))
    tf = tb.text_frame; tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i, text in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "• " + text
        p.font.size = Pt(14)
        p.font.color.rgb = INK
        p.space_after = Pt(6)
        p.line_spacing = 1.04


def _fit(img: Path, max_w: int, max_h: int) -> tuple[int, int]:
    h, w = cv2.imread(str(img)).shape[:2]
    ar = w / h
    width, height = max_w, int(max_w / ar)
    if height > max_h:
        height, width = max_h, int(max_h * ar)
    return width, height


def image_slide(tag: str, title: str, images: list[Path],
                captions: list[str] | None = None) -> None:
    images = [im for im in images if im.exists()]
    if not images:
        return
    s = _new_slide()
    _add_header(s, title, tag)
    n = len(images)
    gap = Inches(0.3)
    cap_h = Inches(0.3) if captions else Inches(0.0)
    cell_w = int((CONTENT_W - gap * (n - 1)) / n)
    area_h = int(BODY_H - cap_h)
    x = MARGIN
    for k, img in enumerate(images):
        w, h = _fit(img, cell_w, area_h)
        s.shapes.add_picture(str(img), x + (cell_w - w) // 2,
                             BODY_TOP + (area_h - h) // 2, width=w, height=h)
        if captions:
            cb = s.shapes.add_textbox(x, BODY_TOP + area_h, cell_w, cap_h)
            cp = cb.text_frame.paragraphs[0]
            cp.text = captions[k]; cp.alignment = PP_ALIGN.CENTER
            cp.font.size = Pt(12); cp.font.color.rgb = INK
        x += cell_w + gap


def image_bullets_slide(tag: str, title: str, image: Path,
                        bullets: list[str]) -> None:
    """Image on the left, bullets on the right — for the result slides."""
    if not image.exists():
        content_slide(tag, title, bullets[0], bullets[1:])
        return
    s = _new_slide()
    _add_header(s, title, tag)
    half = int((CONTENT_W - Inches(0.3)) / 2)
    w, h = _fit(image, half, int(BODY_H))
    s.shapes.add_picture(str(image), MARGIN + (half - w) // 2,
                         BODY_TOP + (int(BODY_H) - h) // 2, width=w, height=h)
    tb = s.shapes.add_textbox(MARGIN + half + Inches(0.3), BODY_TOP, half, BODY_H)
    tf = tb.text_frame; tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, text in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "• " + text
        p.font.size = Pt(15); p.font.color.rgb = INK
        p.space_after = Pt(8); p.line_spacing = 1.04


def title_slide() -> None:
    s = _new_slide()
    _add_number(s)  # counts slide 1, prints nothing
    # Accent rule across the top for a clean, branded feel.
    bar = s.shapes.add_shape(1, MARGIN, Inches(1.15), Inches(2.4), Pt(4))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background(); bar.shadow.inherit = False
    tf = s.shapes.add_textbox(MARGIN, Inches(1.35), CONTENT_W, Inches(3.0)).text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    rows = [
        ("PocketDRS", 40, True, NAVY, 6, PP_ALIGN.LEFT),
        ("A Single-View 3D Trajectory Reconstruction and Decision", 18, False, INK, 0, PP_ALIGN.LEFT),
        ("Review System (DRS) for Cricket", 18, False, INK, 16, PP_ALIGN.LEFT),
        ("Niraj Kafle  ·  BIT 7th Semester  ·  LC0003001674", 15, False, INK, 3, PP_ALIGN.LEFT),
        ("Supervisor: Mr. Saishab Bhattarai", 14, False, INK, 3, PP_ALIGN.LEFT),
        ("Phoenix College of Management  ·  Lincoln University College", 14, False, ACCENT, 0, PP_ALIGN.LEFT),
    ]
    for i, (text, size, bold, color, after, align) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text; p.alignment = align
        p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = color
        p.space_after = Pt(after)


def agenda_slide() -> None:
    s = _new_slide()
    _add_header(s, "Agenda", None)
    items = [
        "Introduction & Problem",
        "Objectives & Requirements",
        "System Analysis & Design",
        "The Five-Stage Algorithm",
        "Implementation & Tools",
        "Results & Validation",
        "Limitations & Conclusion",
    ]
    tb = s.shapes.add_textbox(MARGIN, BODY_TOP, CONTENT_W, BODY_H)
    tf = tb.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, text in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run(); run.text = f"{i + 1}.  "
        run.font.size = Pt(17); run.font.bold = True; run.font.color.rgb = ACCENT
        run2 = p.add_run(); run2.text = text
        run2.font.size = Pt(17); run2.font.color.rgb = INK
        p.space_after = Pt(9); p.line_spacing = 1.05


def closing_slide() -> None:
    s = _new_slide()
    _add_number(s)
    bar = s.shapes.add_shape(1, MARGIN, Inches(2.05), Inches(2.4), Pt(4))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background(); bar.shadow.inherit = False
    tf = s.shapes.add_textbox(MARGIN, Inches(2.2), CONTENT_W, Inches(2.4)).text_frame
    tf.word_wrap = True
    rows = [
        ("Thank You", 40, True, NAVY, 6),
        ("Questions & Discussion", 18, False, ACCENT, 14),
        ("Niraj Kafle  ·  PocketDRS  ·  BIT Final-Year Project", 14, False, INK, 0),
    ]
    for i, (text, size, bold, color, after) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text; p.alignment = PP_ALIGN.LEFT
        p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = color
        p.space_after = Pt(after)


# Wipe the template's sample slides; keep its masters/layouts (footer logos).
_sldIdLst = prs.slides._sldIdLst
for sid in list(_sldIdLst):
    prs.part.drop_rel(sid.get(qn("r:id")))
    _sldIdLst.remove(sid)

title_slide()
agenda_slide()

content_slide("Introduction", "Introduction",
    "PocketDRS brings ball-tracking DRS to grassroots cricket with one smartphone.", [
    "LBW is one of cricket's most contested calls, judged live from a single viewpoint.",
    "Professional DRS (Hawk-Eye) needs six to eight synchronised high-speed cameras and dedicated hardware.",
    "That rig costs a fortune, so schools, clubs, and training grounds have no access to ball tracking.",
    "PocketDRS reconstructs a delivery in real-world 3D from one phone camera and supports the LBW decision.",
    "A Flutter app records the ball; a FastAPI + OpenCV server tracks it, rebuilds the 3D path, and applies ICC Rule 36.",
])

content_slide("Introduction", "Problem Statement",
    "Recovering a correct 3D ball path from a single 2D view is the core challenge.", [
    "Umpires call LBW in real time from one angle — line, length, height, and impact at once.",
    "Professional ball tracking needs multi-camera rigs, out of reach for grassroots cricket.",
    "A single phone gives only 2D footage: depth ambiguity, motion blur, and an unknown camera pose.",
    "Lifting that 2D pixel track to a correct 3D trajectory from one view is the hard part.",
    "Need: recover 3D ball flight from one phone video and return a transparent LBW verdict.",
])

content_slide("Introduction", "Objectives",
    "Build a phone-only pipeline that reconstructs a delivery in 3D and supports the LBW call.", [
    "Recover the camera pose from the marked stumps using PnP (the tapped corners set the detection region).",
    "Detect and track the ball across frames (motion + colour + a learned YOLO detector).",
    "Link the detections into one smooth trajectory using RANSAC.",
    "Rebuild the ball path in real-world 3D using projectile-motion physics.",
    "Apply the three ICC Rule 36 checks — pitching, impact, wickets — for the verdict.",
])

content_slide("Requirements", "Functional Requirements",
    "Twelve functional requirements span capture, calibration, analysis, and visualisation.", [
    "Record or upload a delivery clip and tap the four pitch corners for calibration.",
    "Detect the ball per frame and link the detections into a single trajectory.",
    "Recover the camera pose and reconstruct the ball path in real-world 3D.",
    "Compute pitching, impact, and wicket-hitting and return an LBW verdict.",
    "Render a broadcast-style 2D overlay and an interactive 3D Hawk-Eye view.",
])

content_slide("Requirements", "Non-functional Requirements",
    "Fast, usable, transparent, and portable — with no specialist hardware.", [
    "Performance: analyse a delivery within about thirty seconds end to end.",
    "Usability: four taps, no specialist hardware, no configuration.",
    "Accuracy: correct camera recovery and a verdict within honest monocular bounds.",
    "Transparency: every verdict shows the three checks and the predicted impact at the stumps.",
    "Portability: a standard Android or iOS phone plus a Python FastAPI server.",
])

image_slide("Analysis & Design", "Use-Case Diagram", [FIG / "use_case_diagram.png"])
image_slide("Analysis & Design", "Data Modeling: ER Diagram", [FIG / "er_diagram.png"])
image_slide("Analysis & Design", "Process Modeling: Data Flow Diagrams",
            [FIG / "dfd_level0.png", FIG / "dfd_level1.png"],
            ["Level 0 (context)", "Level 1"])
image_slide("Analysis & Design", "System Architecture", [FIG / "architecture.png"])

content_slide("Algorithm", "Algorithm: The Five-Stage Pipeline",
    "Five sequential stages turn one phone clip into an LBW verdict.", [
    "Stage 1 — Calibration: the marked stumps anchor solvePnP to recover the camera pose (sub-pixel on synthetic input; higher on real handheld clips).",
    "Stage 2 — Ball detection: MOG2 motion + HSV colour + a YOLO detector isolate the ball in each frame.",
    "Stage 3 — Trajectory linking: a two-pass RANSAC fits one smooth parabola through the bounce and rejects clutter.",
    "Stage 4 — 3D reconstruction: a gravity-constrained projectile fit lifts the 2D track to a real-world 3D arc.",
    "Stage 5 — LBW decision: ICC Rule 36 — pitching, impact, wickets — give out / not out / umpire's call.",
])

content_slide("Implementation", "Implementing Tools",
    "A standard, open-source mobile-to-cloud stack — no paid SDKs.", [
    "Flutter + Dart: cross-platform mobile app (capture, calibration taps, result viewer).",
    "FastAPI (Python): analysis server exposing the pipeline as a REST API.",
    "OpenCV + NumPy + SciPy: detection, PnP, RANSAC, and projectile fitting.",
    "Ultralytics YOLO + PyTorch: learned ball detector for cluttered real footage.",
    "Three.js for the interactive 3D Hawk-Eye viewer; Firebase for auth and result storage.",
])

content_slide("Implementation", "Implementation: Module Details",
    "One module per pipeline stage, each small and independently testable.", [
    "Calibration: stump-anchored PnP from the tapped points derives pitch length and camera pose.",
    "Detection: combined motion/colour and YOLO, ROI-masked, producing per-frame ball candidates.",
    "Trajectory: RANSAC parabola seed → least-squares refine → bounce-aware arc merge.",
    "Reconstruction: a gravity-constrained linear solver lifts pixels to 3D and predicts the path to the stumps.",
    "Decision + overlay: the ICC Rule 36 engine plus a 2D overlay and a 3D viewer with speed, swing, and spin.",
])

image_bullets_slide("Results", "Real-Video Test: test3.mp4",
                    FIG / "test3_overlay.png", [
    "29 ball detections tracked across the delivery (28 RANSAC inliers).",
    "Camera recovered from the marked stumps (16.56 px reprojection — high; see limitations).",
    "Release speed 64.1 km/h; swing 48 cm; spin 2.5°.",
    "Ball pitches and is intercepted; path predicted to the stumps.",
    "Verdict NOT OUT — predicted to miss the wicket.",
])
image_slide("Results", "3D Hawk-Eye View: test3", [FIG / "test3_3d_path.png"])
image_bullets_slide("Results", "Synthetic Validation: 8 Scenarios",
                    FIG / "synth_summary.png", [
    "8 controlled deliveries: medium pace, middle-stump corridor, full length.",
    "Camera pose recovered correctly in every scene.",
    "8 / 8 reconstructions within honest monocular bounds (speed, bounce, impact).",
    "All eight ground-truth OUT deliveries returned OUT.",
])

content_slide("Limitations", "Limitations & Honest Bounds",
    "Honest about what a single camera can and cannot do.", [
    "A single phone cannot triangulate depth like six to eight synchronised Hawk-Eye cameras.",
    "Depth-from-ball-radius is good to a few tens of centimetres, not millimetres.",
    "The synthetic 8/8 passes are within monocular bounds (speed ±55 km/h, bounce ±175 cm, impact ±110 cm), not broadcast bounds.",
    "On test3 the calibration reprojection was 16.56 px (high) — the verdict shape is right, the absolute scale approximate.",
    "Positioned as decision support for coaching nets and clubs, not an ICC broadcast replacement.",
])

content_slide("Conclusion", "Conclusion",
    "One phone, a known pitch, and projectile physics are enough for usable LBW support.", [
    "A complete pipeline: calibrate → detect → track → reconstruct → decide, with a broadcast overlay and a 3D Hawk-Eye view.",
    "Validated on synthetic deliveries (8/8 within bounds) and real footage, with correct camera recovery throughout.",
    "Refuses to invent a verdict on unusable clips — it fails clearly rather than guessing.",
    "Future work: frame-accurate impact detection, learned bounce modelling, multi-phone capture, and on-device inference.",
])

closing_slide()

prs.save(str(OUT))
print(f"Wrote {OUT}  ({len(prs.slides)} slides)")
