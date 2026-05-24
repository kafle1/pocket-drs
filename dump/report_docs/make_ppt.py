"""Build the PocketDRS final-defense presentation.

Reproducible: re-run to regenerate dump/report_docs/pocketdrs_presentation.pptx.
Uses the institutional template theme (dump/BIT Project PPT Sample.pptx) for
background/fonts, but lays out every slide with explicit, controlled geometry
(manual title band + body box + fitted images) so nothing clips or overlaps.
Structured-approach order required for the defense (ER, DFD; no OO diagrams).
Target: >= 22 content slides covering report end-to-end in defense order.
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
MUTED = RGBColor(0x55, 0x55, 0x55)

prs = Presentation(str(TEMPLATE))
SW, SH = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[10]

MARGIN = Inches(0.55)
TITLE_TOP = Inches(0.35)
TITLE_H = Inches(0.85)
BODY_TOP = Inches(1.35)
BODY_H = SH - BODY_TOP - Inches(0.95)
CONTENT_W = SW - 2 * MARGIN


def _new_slide():
    slide = prs.slides.add_slide(BLANK)
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return slide


def _add_title(slide, text: str, subtitle: str | None = None) -> None:
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
    if subtitle:
        p2 = tf.add_paragraph()
        p2.text = subtitle
        p2.font.size = Pt(13)
        p2.font.italic = True
        p2.font.color.rgb = MUTED
    line = slide.shapes.add_shape(1, MARGIN, TITLE_TOP + TITLE_H, Inches(2.2), Pt(3))
    line.fill.solid(); line.fill.fore_color.rgb = ACCENT
    line.line.fill.background()
    line.shadow.inherit = False


def bullet_slide(title: str, bullets: list[tuple[int, str]], subtitle: str | None = None) -> None:
    slide = _new_slide()
    _add_title(slide, title, subtitle)
    tb = slide.shapes.add_textbox(MARGIN, BODY_TOP, CONTENT_W, BODY_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i, (level, text) in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        glyph = "•  " if level == 0 else "◦  "
        p.text = glyph + text
        p.level = level
        p.font.size = Pt(17 if level == 0 else 14)
        p.font.color.rgb = INK
        p.space_after = Pt(7 if level == 0 else 3)
        p.line_spacing = 1.08


def _fit(img: Path, max_w: int, max_h: int) -> tuple[int, int]:
    h, w = cv2.imread(str(img)).shape[:2]
    ar = w / h
    width, height = max_w, int(max_w / ar)
    if height > max_h:
        height, width = max_h, int(max_h * ar)
    return width, height


def image_slide(title: str, images: list[Path], captions: list[str] | None = None,
                subtitle: str | None = None) -> None:
    slide = _new_slide()
    _add_title(slide, title, subtitle)
    n = len(images)
    gap = Inches(0.3)
    cap_h = Inches(0.32) if captions else Inches(0.0)
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
            cp.font.bold = True
            cp.font.color.rgb = INK
        x += cell_w + gap


def image_with_bullets(title: str, image: Path, bullets: list[str],
                       subtitle: str | None = None) -> None:
    """Image on the left, supporting bullets on the right."""
    slide = _new_slide()
    _add_title(slide, title, subtitle)
    img_w = int(CONTENT_W * 0.50)
    text_w = int(CONTENT_W * 0.46)
    text_x = MARGIN + img_w + Inches(0.2)
    w, h = _fit(image, img_w, int(BODY_H))
    left = MARGIN + (img_w - w) // 2
    top = BODY_TOP + (int(BODY_H) - h) // 2
    slide.shapes.add_picture(str(image), left, top, width=w, height=h)
    tb = slide.shapes.add_textbox(text_x, BODY_TOP, text_w, BODY_H)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    for i, text in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = "•  " + text
        p.font.size = Pt(15)
        p.font.color.rgb = INK
        p.space_after = Pt(8)
        p.line_spacing = 1.1


def section_divider(label: str, number: int) -> None:
    """A clean 'section break' slide between major parts of the talk."""
    slide = _new_slide()
    nb = slide.shapes.add_textbox(MARGIN, Inches(2.4), CONTENT_W, Inches(1.2))
    np_ = nb.text_frame.paragraphs[0]
    np_.text = f"PART {number:02d}"
    np_.alignment = PP_ALIGN.CENTER
    np_.font.size = Pt(20)
    np_.font.bold = True
    np_.font.color.rgb = ACCENT

    tb = slide.shapes.add_textbox(MARGIN, Inches(3.2), CONTENT_W, Inches(1.5))
    p = tb.text_frame.paragraphs[0]
    p.text = label
    p.alignment = PP_ALIGN.CENTER
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = NAVY


def title_slide() -> None:
    slide = _new_slide()
    box = slide.shapes.add_textbox(MARGIN, Inches(1.2), CONTENT_W, Inches(3.4))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    rows = [
        ("PocketDRS", 44, True, NAVY, 6),
        ("A Single-View 3D Trajectory Reconstruction", 18, False, INK, 0),
        ("and Decision Review System for Cricket", 18, False, INK, 16),
        ("Final-Year Project Defense", 14, True, ACCENT, 14),
        ("Niraj Kafle  |  BIT 7th Semester  |  ID: LC0003001674", 14, False, INK, 4),
        ("Supervisor: Mr. Saishab Bhattarai", 14, False, INK, 4),
        ("Phoenix College of Management, Maitidevi, Kathmandu", 13, False, MUTED, 4),
        ("Lincoln University College, Faculty of Computer Science and Multimedia", 12, False, MUTED, 0),
    ]
    for i, (text, size, bold, color, after) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text
        p.alignment = PP_ALIGN.CENTER
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = color
        p.space_after = Pt(after)
    # Date band at the bottom.
    db = slide.shapes.add_textbox(MARGIN, Inches(5.6), CONTENT_W, Inches(0.5))
    dp = db.text_frame.paragraphs[0]
    dp.text = "May, 2026"
    dp.alignment = PP_ALIGN.CENTER
    dp.font.size = Pt(13)
    dp.font.color.rgb = MUTED


#, drop the template's sample slides cleanly,
_sldIdLst = prs.slides._sldIdLst
for sid in list(_sldIdLst):
    prs.part.drop_rel(sid.get(qn("r:id")))
    _sldIdLst.remove(sid)


# ============================================================
# SLIDE DECK ,  target: 22 slides (1 title + 20 content + 1 close)
# ============================================================

title_slide()

bullet_slide("Introduction & Problem Statement", [
    (0, "Cricket relies on tech to review close LBW decisions, Hawk-Eye uses 6–8 synchronised high-speed cameras."),
    (0, "Hawk-Eye is accurate (3–5 mm) but unaffordable for schools, clubs, nets."),
    (0, "Single phone camera makes the problem hard:"),
    (1, "No direct depth from one view; ball is small, fast, motion-blurred."),
    (1, "Small calibration errors blow up at the far end of the pitch."),
    (0, "Question: can a single-camera workflow + pitch geometry give consistent LBW review support?"),
])

bullet_slide("Objectives, Scope, Limitations", [
    (0, "Goal: low-cost single-camera system that analyses a delivery and assists LBW review."),
    (0, "Specific objectives:"),
    (1, "User-guided pitch-corner calibration; ball detection + trajectory association."),
    (1, "Camera pose + monocular 3D reconstruction; ICC Rule 36 LBW logic; interactive 3D viewer."),
    (0, "Limitations: umpire-POV camera; not ICC-certified; monocular depth fundamentally limited."),
    (0, "Decision support only, umpire still calls the game."),
])

bullet_slide("Literature Review", [
    (0, "Owens et al. (2003), original Hawk-Eye (multi-camera ball tracking), accuracy benchmark."),
    (0, "Zhang (2000), checkerboard camera calibration → intrinsic-model foundation."),
    (0, "Hartley & Zisserman (2004), multiple-view geometry → homography theory."),
    (0, "Fischler & Bolles (1981), RANSAC → used for homography + trajectory association."),
    (0, "Triggs et al. (2000), bundle adjustment → motivates least-squares projectile fit."),
    (0, "Ponglertnapakorn & Suwajanakorn (CVPRW 2025), closest prior work (single-view 3D ball)."),
    (0, "Zivkovic (2004) MOG2 + Redmon et al. (2016) YOLO → motion + learned detectors."),
])

image_slide("ER Diagram + Data Flow Diagrams",
            [FIG / "er_diagram.png", FIG / "dfd_level0.png", FIG / "dfd_level1.png"],
            ["ER Diagram", "DFD Level 0 (context)", "DFD Level 1"],
            subtitle="Structured approach: data model + 2-level DFD (no OO diagrams per syllabus).")

image_slide("System Architecture + Physical DFD",
            [FIG / "architecture.png", FIG / "physical_dfd.png"],
            ["3-Tier Architecture", "Physical DFD (deployed)"],
            subtitle="Flutter app → HTTPS → FastAPI on Cloud Run → Firestore + Cloud Storage; Three.js viewer in WebView.")

bullet_slide("Requirements (Functional + Non-Functional)", [
    (0, "Functional: auth (Firebase); record/trim video; tap 4 pitch corners; save calibration."),
    (0, "Submit clip → server detects ball, reconstructs 3D, returns LBW verdict + reason."),
    (0, "Interactive 3D viewer; analysis history."),
    (0, "Non-functional:"),
    (1, "Response ≤ 30 s for a 5-s clip; accuracy < 80 cm position error (synthetic)."),
    (1, "Offline calibration; HTTPS + Firestore privacy rules; Android 6+/iOS 12+ via Flutter."),
    (1, "Usability: first analysis in < 5 minutes."),
])

bullet_slide("Algorithm, the 5-Step Pipeline", [
    (0, "1.  Camera pose from 4 tapped pitch corners (PnP, reject below-ground mirror)."),
    (0, "2.  Ball detection per frame, motion (MOG2) + colour (HSV), or YOLO on real clips."),
    (1, "Fixed-clutter suppression: drop anything sitting in same pixel > 30% of frames."),
    (0, "3.  Trajectory association, RANSAC links detections into one projectile path."),
    (0, "4.  3D reconstruction, depth-from-size + projectile fit, anchored at the bounce."),
    (1, "Quality gate: fit RMS > 0.75 m ⇒ discard (no fake verdict)."),
    (0, "5.  LBW decision, ICC Rule 36 (pitched, impact, hitting) + ±2.5 cm umpire's-call band."),
])

bullet_slide("Step 1, Camera Pose (PnP)", [
    (0, "Input: 4 pitch corners (user-tapped) + known real-world pitch size."),
    (0, "Output: where the phone stood + which way it pointed."),
    (0, "Method: Perspective-n-Point, pose whose projected corners match the tapped pixels."),
    (0, "Edge case: planar PnP has a twofold mirror, reject the below-ground answer."),
    (0, "Verified: 0.00 px reprojection error on every synthetic scenario."),
])

bullet_slide("Step 2, Ball Detection", [
    (0, "Two independent detectors per frame:"),
    (1, "Motion (MOG2): accepts round blobs AND short streaks (fast ball blurs)."),
    (1, "Colour (HSV): looks for the ball's tone (red / white)."),
    (0, "Agreement between the two boosts confidence."),
    (0, "Fixed-clutter suppression, same pixel > 30% of frames ⇒ background, not the ball."),
    (0, "Real handheld clips additionally use a learned YOLO cricket-ball detector."),
])

bullet_slide("Step 3, Trajectory Association (RANSAC)", [
    (0, "Input: candidate detections from Step 2 (mix of real ball + false positives)."),
    (0, "RANSAC: try pairs → fit projectile path → count inliers → keep the best."),
    (0, "Phone-shot-from-behind specifics:"),
    (1, "Measure TOTAL motion across the clip (ball moves towards camera, per-frame motion tiny)."),
    (1, "Reject tracks covering < 20% of image width, leftover clutter, not a real delivery."),
    (0, "Output: one consistent path + inlier count + fit RMS."),
])

bullet_slide("Step 4, 3D Reconstruction", [
    (0, "Input: 2D ball path (Step 3) + camera pose (Step 1)."),
    (0, "Depth-from-size: cricket ball always 0.036 m radius → smaller in image ⇒ further away."),
    (0, "Rough 3D points → fitted to projectile motion (gravity 9.81 m/s²)."),
    (0, "Bounce anchor: bounce pixel back-projected onto pitch plane, the most reliable single point."),
    (0, "Physical bounds on release height + downward velocity prevent impossible solutions."),
    (0, "Quality gate: fit RMS > 0.75 m ⇒ discard reconstruction (return warning, no fake verdict)."),
])

bullet_slide("Step 5, LBW Decision (ICC Rule 36)", [
    (0, "Three checks, in order:"),
    (1, "Pitched in line?  Bounce inside leg-stump line + tolerance."),
    (1, "Impact in line?  Pad strike inside stump line + ball radius."),
    (1, "Hitting stumps?  Project path on to the stump plane."),
    (0, "All three pass ⇒ OUT; inside ±2.5 cm margin ⇒ UMPIRE'S CALL; else NOT OUT."),
    (0, "Vertical band widened to 7.2 cm (one ball-diameter) to reflect monocular depth noise."),
    (0, "Plain-English reason returned with every verdict."),
])

bullet_slide("Tools & Implementation", [
    (0, "Mobile: Flutter 3.8 (Dart), capture, trim, calibration canvas, REST client, WebView."),
    (0, "Backend: FastAPI on Google Cloud Run, async job manager."),
    (0, "Computer vision: OpenCV 4.8, NumPy 1.24, SciPy 1.11; Ultralytics YOLO."),
    (0, "Data: Firebase Auth + Cloud Firestore + Cloud Storage."),
    (0, "Visualisation: Three.js Hawk-Eye viewer inside a Flutter WebView."),
    (0, "Backend modules per algorithm step; mobile modules per UI screen (testable in isolation)."),
])

bullet_slide("Robustness / Edge-Case Hardening", [
    (0, "A review pass made the system fail safely, never confidently-wrong:"),
    (1, "Truncated video headers, decoder stops at last real frame, no padding."),
    (1, "Bad calibration (collinear / duplicate corners), rejected with a clear message."),
    (1, "Invalid numbers (negative dims, NaN detections), caught at input boundary."),
    (1, "Network / token failures in app, clean error after retries, no infinite polling."),
    (1, "3D viewer, non-finite values coerced; reload prompt if scripts never load."),
    (0, "Net effect: correct result, or clear/safe failure, never a fake verdict."),
])

bullet_slide("Testing, 20 Unit + 12 System (all pass)", [
    (0, "Unit (20): calibration (4), detection (4), trajectory (3), reconstruction (2), LBW (5), hardening (1), API (1)."),
    (0, "Edge cases covered: twofold-mirror, degenerate corners, fixed-clutter, motion-blur streak, quality gate."),
    (0, "System (12): all 3 verdict classes; bad real clip; good real clip; truncated video; session recovery; viewer safety."),
    (0, "Status: 20 / 20 unit + 12 / 12 system pass on the deployed build."),
])

bullet_slide("Synthetic Validation, 66 deliveries", [
    (0, "Controlled OpenCV harness: textured pitch, crease lines, red ball; 1080×1920 @ 60 fps."),
    (0, "Sweep: 3 release speeds × 11 release lines × 2 angles = 66 scenarios."),
    (0, "Camera calibration: 0.00 px reprojection error on every scenario."),
    (0, "Detection: 60–130 candidates / scenario; RANSAC keeps ~95% inliers; image-RMS 10–25 px."),
    (0, "LBW decisions: 53 / 66 correct (80.3%):"),
    (1, "OUT 16 / 16 (100%); NOT OUT 36 / 44 (81.8%); Umpire's Call 1 / 6."),
])

image_slide("Result Renders, Three LBW Verdicts",
            [FIG / "case_out.png", FIG / "case_not_out.png", FIG / "case_umpires_call.png"],
            ["OUT", "NOT OUT", "Umpire's Call"],
            subtitle="Real Three.js viewer renders from real pipeline output (synthetic sweep).")

image_with_bullets("Real-World Validation, bad clip vs good clip",
                   FIG / "test3_path_overlay.png", [
    "Clip 1 (bad): low camera + netting + clutter ⇒ system safely refused, no fake verdict.",
    "Clip 2 (good, shown): off-spin (flighted), ball stays visible above the bowler.",
    "YOLO + RANSAC: 25 ball positions, 22 inliers, image-RMS 14.4 px.",
    "Fixed-clutter suppression removed a recurring red false-positive.",
    "Truncation guard stopped at frame 101 (header claimed 290).",
    "Same unchanged pipeline produced a clean full-flight 2D track + plausible 3D arc.",
], subtitle="Bowler's release (green) → arrival at the batter (red).")

bullet_slide("Conclusion + Lessons Learned", [
    (0, "Full single-camera LBW pipeline: calibrate → detect → track → 3D → decide → visualise."),
    (0, "Synthetic: 53 / 66 correct (80.3%); OUT class 16 / 16 (100%)."),
    (0, "Real clip (good): clean track + plausible 3D arc. Real clip (bad): safe refusal."),
    (0, "Lessons:"),
    (1, "Strong physical constraints beat raw ML on small data."),
    (1, "User calibration is the single biggest accuracy driver."),
    (1, "Fail-safe behaviour matters more than coverage for a decision-support tool."),
])

bullet_slide("Future Recommendations", [
    (0, "Multi-camera fusion (stereo / two phones), removes depth ambiguity entirely."),
    (0, "Learned detection by default, make YOLO the primary detector."),
    (0, "Automatic landmark detection, find stumps / crease lines instead of asking the user."),
    (0, "Real-time streaming + on-device inference."),
    (0, "Better bounce model (drag / spin) + statistical confidence intervals."),
    (0, "Field user studies with umpires and players."),
])

bullet_slide("Thank You, Questions?", [
    (0, "PocketDRS: a phone, a tripod, and the geometry of a cricket pitch."),
    (0, "Niraj Kafle, BIT 7th Semester, Phoenix College of Management."),
    (0, "Supervisor: Mr. Saishab Bhattarai."),
    (0, "Final report, defense-prep guide, and demo clips available on request."),
])

prs.save(str(OUT))
print(f"Wrote {OUT}  ({len(prs.slides)} slides)")
