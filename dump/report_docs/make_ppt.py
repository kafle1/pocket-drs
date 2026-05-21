"""Build the PocketDRS final-defense presentation.

Reproducible: re-run to regenerate dump/report_docs/pocketdrs_presentation.pptx.
Uses the institutional template theme (dump/BIT Project PPT Sample.pptx) for
background/fonts, but lays out every slide with explicit, controlled geometry
(manual title band + body box + fitted images) so nothing clips or overlaps.
Structured-approach order required for the defense (Use-Case, ER, DFD).
Requires python-pptx + opencv (already in the server venv).
"""

from __future__ import annotations

from pathlib import Path

import cv2
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE.parent / "BIT Project PPT Sample.pptx"
FIG = BASE / "figures"
OUT = BASE / "pocketdrs_presentation.pptx"

NAVY = RGBColor(0x12, 0x33, 0x5B)
INK = RGBColor(0x20, 0x20, 0x20)
ACCENT = RGBColor(0x2E, 0x6F, 0xB5)

prs = Presentation(str(TEMPLATE))
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[10]

# Layout geometry (EMU via Inches).
MARGIN = Inches(0.55)
TITLE_TOP = Inches(0.35)
TITLE_H = Inches(0.85)
BODY_TOP = Inches(1.35)
# Leave room at the bottom for the template's footer logos so tall images and
# long bullet lists never collide with them.
BODY_H = SH - BODY_TOP - Inches(0.95)
CONTENT_W = SW - 2 * MARGIN


def _new_slide():
    slide = prs.slides.add_slide(BLANK)
    # Force a clean white background so text is readable regardless of theme.
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return slide


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
    # Accent rule under the title.
    line = slide.shapes.add_shape(1, MARGIN, TITLE_TOP + TITLE_H, Inches(2.2), Pt(3))
    line.fill.solid(); line.fill.fore_color.rgb = ACCENT
    line.line.fill.background()
    line.shadow.inherit = False


def bullet_slide(title: str, bullets: list[tuple[int, str]]) -> None:
    slide = _new_slide()
    _add_title(slide, title)
    tb = slide.shapes.add_textbox(MARGIN, BODY_TOP, CONTENT_W, BODY_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE  # shrink if it ever overflows
    for i, (level, text) in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        glyph = "•  " if level == 0 else "◦  "
        p.text = glyph + text
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
    slide = _new_slide()
    _add_title(slide, title)
    n = len(images)
    gap = Inches(0.3)
    cap_h = Inches(0.3) if captions else Inches(0.0)
    cell_w = int((CONTENT_W - gap * (n - 1)) / n)
    area_h = int(BODY_H - cap_h)
    x = MARGIN
    for k, img in enumerate(images):
        w, h = _fit(img, cell_w, area_h)
        left = x + (cell_w - w) // 2
        top = BODY_TOP + (area_h - h) // 2
        slide.shapes.add_picture(str(img), left, top, width=w, height=h)
        if captions:
            cb = slide.shapes.add_textbox(x, BODY_TOP + area_h, cell_w, cap_h)
            cp = cb.text_frame.paragraphs[0]
            cp.text = captions[k]
            cp.alignment = PP_ALIGN.CENTER
            cp.font.size = Pt(12)
            cp.font.color.rgb = INK
        x += cell_w + gap


def title_slide() -> None:
    slide = _new_slide()
    box = slide.shapes.add_textbox(MARGIN, Inches(1.4), CONTENT_W, Inches(2.9))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    rows = [
        ("PocketDRS", 40, True, NAVY, 6),
        ("A Single-View 3D Trajectory Reconstruction and", 18, False, INK, 0),
        ("Decision Review System for Cricket", 18, False, INK, 14),
        ("Niraj Kafle, BIT (LC0003001674)", 16, False, INK, 2),
        ("Supervisor: Mr. Saishab Bhattarai", 15, False, INK, 2),
        ("Phoenix College of Management", 15, False, ACCENT, 0),
    ]
    for i, (text, size, bold, color, after) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text
        p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = color
        p.space_after = Pt(after)


# --- drop the template's sample slides cleanly (avoid orphan part collisions) ---
_sldIdLst = prs.slides._sldIdLst
for sid in list(_sldIdLst):
    prs.part.drop_rel(sid.get(qn("r:id")))
    _sldIdLst.remove(sid)

title_slide()

bullet_slide("Introduction", [
    (0, "Cricket officiating increasingly relies on technology for close LBW decisions."),
    (0, "Professional systems (e.g. Hawk-Eye) use 6 to 8 synchronised high-speed cameras."),
    (1, "Costly, complex, and impractical for schools, clubs, and training grounds."),
    (0, "PocketDRS: low-cost LBW support from a single smartphone camera + a lightweight server."),
    (1, "Record delivery → mark pitch corners → analyse → 3D visualisation + LBW verdict."),
])

bullet_slide("Problem Statement", [
    (0, "Professional DRS needs multiple synchronised cameras to recover depth, which is expensive and inaccessible."),
    (0, "A single consumer camera makes the problem hard:"),
    (1, "No direct depth from one view."),
    (1, "Ball is small, fast, motion-blurred, easily confused with clutter."),
    (1, "Small calibration errors cause large pitch-coordinate errors."),
    (0, "Can a single-phone workflow give consistent, understandable LBW review support?"),
])

bullet_slide("Objectives", [
    (0, "General: a low-cost single-camera system that analyses a delivery and assists LBW review."),
    (0, "Specific objectives:"),
    (1, "Study existing DRS and monocular sports-tracking work."),
    (1, "User-guided pitch-corner calibration."),
    (1, "Detect and track the ball from delivery video."),
    (1, "Map detections to pitch coordinates (homography); recover camera pose."),
    (1, "Detect bounce/impact; apply rule-based LBW (ICC Rule 36)."),
    (1, "Present an interactive 3D visualisation of the decision."),
])

bullet_slide("Functional Requirements", [
    (0, "User authentication via Firebase (email/password or Google sign-in)."),
    (0, "Record or select a delivery video, and trim to the delivery."),
    (0, "Calibrate the pitch by tapping the four corners; validate quality."),
    (0, "Submit the clip for server-side ball detection and 3D reconstruction."),
    (0, "Return an LBW decision (OUT / NOT OUT / UMPIRE'S CALL) with rationale."),
    (0, "Interactive 3D trajectory view and saved analysis history."),
])

bullet_slide("Non-functional Requirements", [
    (0, "Response time: process a 5-second clip within ~30 seconds."),
    (0, "Accuracy: synthetic-test position error under 80 cm."),
    (0, "Offline support: calibration and selection work offline; analysis needs connectivity."),
    (0, "Security: Firebase authentication; data encrypted in transit."),
    (0, "Cross-platform (Android / iOS), usability, maintainability, data privacy."),
])

image_slide("Data Modeling: ER Diagram", [FIG / "er_diagram.png"])
image_slide("Process Modeling: Data Flow Diagrams",
            [FIG / "dfd_level0.png", FIG / "dfd_level1.png"],
            ["Level 0 (context)", "Level 1"])

bullet_slide("Algorithm Details", [
    (0, "1.  Camera pose: from 4 tapped pitch corners (PnP); reject the below-ground mirror."),
    (0, "2.  Ball detection: motion plus colour, or a learned (YOLO) detector for real footage."),
    (0, "3.  Trajectory association: RANSAC links detections into one smooth path."),
    (0, "4.  3D reconstruction: depth-from-size plus projectile-motion fit, anchored at the bounce."),
    (0, "5.  LBW decision: ICC Rule 36 checks (pitching, impact, hitting stumps)."),
])

bullet_slide("Implementing Tools", [
    (0, "Mobile: Flutter (Dart) for capture, trim, calibration UI, and 3D WebView."),
    (0, "Backend: FastAPI (Python) on Google Cloud Run."),
    (0, "Computer vision: OpenCV, NumPy, SciPy; learned detection via Ultralytics YOLO."),
    (0, "Data / Auth: Firebase Authentication + Cloud Firestore."),
    (0, "Visualisation: Three.js (3D Hawk-Eye viewer) inside a WebView."),
])

bullet_slide("Implementation: Module Details", [
    (0, "Mobile app:"),
    (1, "Auth, video capture/trim, pitch-calibration canvas, REST client, 3D viewer."),
    (0, "Backend pipeline:"),
    (1, "Video decoder, ball detector, trajectory finder (RANSAC)."),
    (1, "Calibration / camera-pose solver (PnP + homography)."),
    (1, "3D reconstruction, LBW decision engine, async job manager."),
])

image_slide("Results: 3D Verdict Render", [FIG / "app_result_out.png"])

bullet_slide("Conclusion", [
    (0, "A complete single-camera LBW pipeline: calibrate → track → 3D → decision → visualise."),
    (0, "Synthetic validation: correct verdict on 53 / 66 deliveries (80.3%), OUT 16/16."),
    (0, "Calibration validated on real footage; learned (YOLO) detector tracks the ball on real clips."),
    (0, "Not ICC-certified; future work: multi-camera fusion, on-device inference, real-time streaming."),
])

prs.save(str(OUT))
print(f"Wrote {OUT}  ({len(prs.slides)} slides)")
