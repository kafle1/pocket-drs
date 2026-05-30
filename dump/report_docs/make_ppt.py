"""Build the PocketDRS final-defense presentation.

Reproducible: re-run to regenerate pocketdrs_presentation.pptx. Uses the
institutional BIT template theme for background/footer logos, but lays out every
slide with explicit, controlled geometry (manual title band + body box + fitted
images) so nothing clips or overlaps. Structured-approach order (Use-Case, ER,
DFD, Architecture). Styling mirrors the approved SecureLogTI deck.
Requires python-pptx + opencv.
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

NAVY = RGBColor(0x12, 0x33, 0x5B)
INK = RGBColor(0x20, 0x20, 0x20)
ACCENT = RGBColor(0x2E, 0x6F, 0xB5)

prs = Presentation(str(TEMPLATE))
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[10]

MARGIN = Inches(0.55)
TITLE_TOP = Inches(0.35)
TITLE_H = Inches(0.85)
BODY_TOP = Inches(1.35)
BODY_H = SH - BODY_TOP - Inches(0.95)  # leave room for the template footer logos
CONTENT_W = SW - 2 * MARGIN


def _new_slide():
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return s


def _add_title(slide, text: str) -> None:
    tb = slide.shapes.add_textbox(MARGIN, TITLE_TOP, CONTENT_W, TITLE_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(26)
    p.font.bold = True
    p.font.color.rgb = NAVY
    line = slide.shapes.add_shape(1, MARGIN, TITLE_TOP + TITLE_H, Inches(2.2), Pt(3))
    line.fill.solid(); line.fill.fore_color.rgb = ACCENT
    line.line.fill.background(); line.shadow.inherit = False


def bullet_slide(title: str, bullets: list[tuple[int, str]]) -> None:
    s = _new_slide()
    _add_title(s, title)
    tb = s.shapes.add_textbox(MARGIN, BODY_TOP, CONTENT_W, BODY_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i, (level, text) in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = ("•  " if level == 0 else "◦  ") + text
        p.level = level
        p.font.size = Pt(17 if level == 0 else 14)
        p.font.color.rgb = INK
        p.space_after = Pt(7 if level == 0 else 3)
        p.line_spacing = 1.05


def _fit(img: Path, max_w: int, max_h: int) -> tuple[int, int]:
    h, w = cv2.imread(str(img)).shape[:2]
    ar = w / h
    width, height = max_w, int(max_w / ar)
    if height > max_h:
        height, width = max_h, int(max_h * ar)
    return width, height


def image_slide(title: str, images: list[Path], captions: list[str] | None = None) -> None:
    images = [im for im in images if im.exists()]
    if not images:
        return
    s = _new_slide()
    _add_title(s, title)
    n = len(images)
    gap = Inches(0.3)
    cap_h = Inches(0.3) if captions else Inches(0.0)
    cell_w = int((CONTENT_W - gap * (n - 1)) / n)
    area_h = int(BODY_H - cap_h)
    x = MARGIN
    for k, img in enumerate(images):
        w, h = _fit(img, cell_w, area_h)
        s.shapes.add_picture(str(img), x + (cell_w - w) // 2, BODY_TOP + (area_h - h) // 2, width=w, height=h)
        if captions:
            cb = s.shapes.add_textbox(x, BODY_TOP + area_h, cell_w, cap_h)
            cp = cb.text_frame.paragraphs[0]
            cp.text = captions[k]; cp.alignment = PP_ALIGN.CENTER
            cp.font.size = Pt(12); cp.font.color.rgb = INK
        x += cell_w + gap


def image_bullets_slide(title: str, image: Path, bullets: list[str]) -> None:
    """Image on the left, bullets on the right — for the result slides."""
    if not image.exists():
        bullet_slide(title, [(0, b) for b in bullets])
        return
    s = _new_slide()
    _add_title(s, title)
    half = int((CONTENT_W - Inches(0.3)) / 2)
    w, h = _fit(image, half, int(BODY_H))
    s.shapes.add_picture(str(image), MARGIN + (half - w) // 2, BODY_TOP + (int(BODY_H) - h) // 2, width=w, height=h)
    tb = s.shapes.add_textbox(MARGIN + half + Inches(0.3), BODY_TOP, half, BODY_H)
    tf = tb.text_frame; tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, text in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "•  " + text
        p.font.size = Pt(16); p.font.color.rgb = INK
        p.space_after = Pt(8); p.line_spacing = 1.05


def title_slide() -> None:
    s = _new_slide()
    tf = s.shapes.add_textbox(MARGIN, Inches(1.3), CONTENT_W, Inches(3.0)).text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    rows = [
        ("PocketDRS", 38, True, NAVY, 6),
        ("A Single-View 3D Trajectory Reconstruction and", 17, False, INK, 0),
        ("Decision Review System (DRS) for Cricket", 17, False, INK, 14),
        ("Niraj Kafle, BIT (LC0003001674)", 16, False, INK, 2),
        ("Supervisor: Mr. Saishab Bhattarai", 15, False, INK, 2),
        ("Phoenix College of Management", 15, False, ACCENT, 0),
    ]
    for i, (text, size, bold, color, after) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text; p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = color
        p.space_after = Pt(after)


_sldIdLst = prs.slides._sldIdLst
for sid in list(_sldIdLst):
    prs.part.drop_rel(sid.get(qn("r:id")))
    _sldIdLst.remove(sid)

title_slide()

bullet_slide("Introduction", [
    (0, "Leg Before Wicket (LBW) is one of cricket's most contested decisions, judged live from a single viewpoint."),
    (0, "Professional Decision Review Systems (Hawk-Eye) settle it with six to eight synchronised high-speed cameras and dedicated hardware."),
    (1, "That rig costs a fortune, so schools, clubs, and training grounds have no access to ball tracking."),
    (0, "PocketDRS reconstructs a delivery in real-world 3D from a single smartphone camera and supports the LBW decision."),
    (0, "A Flutter app records the ball; a FastAPI + OpenCV server tracks it, rebuilds the 3D path, and applies ICC Rule 36."),
])

bullet_slide("Problem Statement", [
    (0, "Umpires call LBW in real time from one angle — hard to read line, length, height, and impact at once."),
    (0, "Professional ball tracking needs multi-camera rigs and is out of reach for grassroots cricket:"),
    (1, "A single phone gives only 2D footage with depth ambiguity, motion blur, and an unknown camera pose."),
    (1, "Lifting a 2D pixel track to a correct 3D trajectory from one view is the core difficulty."),
    (0, "Need: a workflow that recovers 3D ball flight from one phone video and returns a transparent LBW verdict."),
])

bullet_slide("Objectives", [
    (0, "General: a phone-based system that reconstructs a cricket delivery in 3D from a single camera and supports the LBW decision."),
    (0, "Specific objectives:"),
    (1, "Recover the camera pose from four tapped pitch corners using Perspective-n-Point (PnP)."),
    (1, "Detect and track the ball across frames (motion + colour + a learned YOLO detector)."),
    (1, "Link the detections into one smooth trajectory using RANSAC."),
    (1, "Rebuild the ball path in real-world 3D using projectile-motion physics."),
    (1, "Apply the three ICC Rule 36 checks — pitching, impact, wickets — for the verdict."),
])

bullet_slide("Functional Requirements", [
    (0, "Record or upload a delivery clip and tap the four pitch corners for calibration."),
    (0, "Detect the ball per frame and link the detections into a single trajectory."),
    (0, "Recover the camera pose and reconstruct the ball path in real-world 3D."),
    (0, "Compute pitching, impact, and wicket-hitting and return an LBW verdict."),
    (0, "Render a broadcast-style 2D overlay and an interactive 3D Hawk-Eye view with speed, swing, and spin."),
])

bullet_slide("Non-functional Requirements", [
    (0, "Performance: analyse a delivery within about thirty seconds end to end."),
    (0, "Usability: four taps, no specialist hardware, no configuration."),
    (0, "Accuracy: correct camera recovery and a verdict consistent with the manual call."),
    (0, "Transparency: every verdict shows the three checks and the predicted impact at the stumps."),
    (0, "Portability: a standard Android or iOS phone plus a Python FastAPI server."),
])

image_slide("Use-Case Diagram", [FIG / "use_case_diagram.png"])
image_slide("Data Modeling: ER Diagram", [FIG / "er_diagram.png"])
image_slide("Process Modeling: Data Flow Diagrams",
            [FIG / "dfd_level0.png", FIG / "dfd_level1.png"],
            ["Level 0 (context)", "Level 1"])
image_slide("System Architecture", [FIG / "architecture.png"])

bullet_slide("Algorithm Details: The Five-Stage Pipeline", [
    (0, "Stage 1 — Calibration: four tapped pitch corners feed solvePnP to recover the camera pose at sub-pixel reprojection error."),
    (0, "Stage 2 — Ball detection: MOG2 motion + HSV colour + a YOLO detector isolate the ball in each frame."),
    (0, "Stage 3 — Trajectory linking: a two-pass RANSAC fits one smooth parabola through the bounce and rejects clutter."),
    (0, "Stage 4 — 3D reconstruction: a gravity-constrained projectile fit lifts the 2D track to a real-world 3D arc."),
    (0, "Stage 5 — LBW decision: ICC Rule 36 checks — pitching, impact, wickets — give out / not out / umpire's call."),
])

bullet_slide("Implementing Tools", [
    (0, "Flutter + Dart: cross-platform mobile app (capture, calibration taps, result viewer)."),
    (0, "FastAPI (Python): analysis server exposing the pipeline as a REST API."),
    (0, "OpenCV + NumPy + SciPy: detection, PnP, RANSAC, and projectile fitting."),
    (0, "Ultralytics YOLO + PyTorch: learned ball detector for cluttered real footage."),
    (0, "Three.js for the interactive 3D Hawk-Eye viewer; Firebase for auth and result storage."),
])

bullet_slide("Implementation: Module Details", [
    (0, "Calibration: stump-anchored PnP from the tapped corners derives pitch length and camera pose."),
    (0, "Detection: combined motion/colour and YOLO, ROI-masked, producing per-frame ball candidates."),
    (0, "Trajectory: RANSAC parabola seed → least-squares refine → bounce-aware arc merge."),
    (0, "Reconstruction: a gravity-constrained linear solver lifts pixels to 3D and predicts the path to the stumps."),
    (0, "Decision + overlay: the ICC Rule 36 engine plus a 2D overlay and a 3D viewer with speed, swing, and spin."),
])

image_bullets_slide("Real-Video Test: test3.mp4",
                    FIG / "test3_overlay.png", [
    "29 ball detections tracked across the delivery.",
    "Camera recovered at 0.76 px reprojection error.",
    "Release speed 64 km/h; ball pitches and is intercepted.",
    "Path predicted to the stumps — verdict NOT OUT (misses the wicket).",
])
image_slide("3D Hawk-Eye View: test3", [FIG / "test3_3d_path.png"])
image_bullets_slide("Synthetic Validation: 8 Scenarios",
                    FIG / "synth_summary.png", [
    "8 controlled deliveries spanning out, not-out, and umpire's-call lines.",
    "Camera pose recovered correctly in every scene.",
    "8 / 8 verdicts correct against the known ground truth.",
])
image_slide("Mobile App: Calibration & Result",
            [FIG / "app_calibration.png", FIG / "app_result_out.png"],
            ["Pitch calibration (tap 4 corners)", "Result + 3D viewer"])

bullet_slide("Conclusion", [
    (0, "PocketDRS reconstructs a cricket delivery in real-world 3D from a single phone camera and supports the LBW decision."),
    (0, "A complete pipeline: calibrate → detect → track → reconstruct → decide, with a broadcast overlay and a 3D Hawk-Eye view."),
    (0, "Validated on synthetic deliveries (8/8 correct) and real footage, with correct camera recovery throughout."),
    (0, "Future work: frame-accurate impact detection, learned bounce modelling, multi-phone capture, and on-device inference."),
])

prs.save(str(OUT))
print(f"Wrote {OUT}  ({len(prs.slides)} slides)")
