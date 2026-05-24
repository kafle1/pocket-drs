"""Build the PocketDRS final-defense presentation on top of the BIT template.

The official Lincoln-University / Phoenix-College BIT project deck
(`dump/BIT Project PPT Sample.pptx`) carries the approved master, theme,
fonts, and 16:9 slide size (10.00 x 5.625 in). We open it, strip its two
sample slides, and rebuild 17 defense slides using the master's named
layouts so the theme styling travels with every slide.

Re-run to regenerate `dump/report_docs/pocketdrs_presentation.pptx`.
Requires python-pptx (server venv).
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.util import Emu, Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE.parent / "BIT Project PPT Sample.pptx"
FIG = BASE / "figures"
OUT = BASE / "pocketdrs_presentation.pptx"

MUTED = RGBColor(0x60, 0x60, 0x60)


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
def open_template() -> Presentation:
    prs = Presentation(str(TEMPLATE))
    # Drop the two sample slides cleanly. Removing entries from
    # `_sldIdLst` alone leaves orphan slide parts in the zip and produces
    # duplicate-name warnings when we add fresh slides; we also have to
    # drop the part + its presentation-level relationship.
    pres_part = prs.part
    sld_id_lst = prs.slides._sldIdLst
    for sld_id in list(sld_id_lst):
        rId = sld_id.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        slide_part = pres_part.related_part(rId)
        # Drop the relationship so the part is no longer referenced.
        pres_part.drop_rel(rId)
        # Also drop the part from the package so it isn't re-serialised.
        try:
            del prs.part.package._parts[slide_part.partname]
        except (AttributeError, KeyError):
            pass
        sld_id_lst.remove(sld_id)
    return prs


def layout(prs: Presentation, name: str):
    for lay in prs.slide_masters[0].slide_layouts:
        if lay.name == name:
            return lay
    raise KeyError(f"layout {name!r} not in template")


def set_placeholder_text(ph, lines: list[tuple[str, dict]]):
    """Write multi-paragraph text into a placeholder.

    `lines` is a list of (text, opts) where opts may set `bold`, `size`,
    `align`. The layout-defined font family is preserved.
    """
    tf = ph.text_frame
    tf.word_wrap = True
    for i, (text, opts) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        # Clear default runs on first paragraph.
        for r in list(p.runs):
            r.text = ""
        align = opts.get("align")
        if align is not None:
            p.alignment = align
        run = p.add_run()
        run.text = text
        if "bold" in opts:
            run.font.bold = opts["bold"]
        if "size" in opts:
            run.font.size = Pt(opts["size"])
        if "color" in opts:
            run.font.color.rgb = opts["color"]


def set_bullets(ph, bullets: list[str], *, size: int | None = None):
    """Write plain bullet text into a body placeholder.

    The body placeholder already carries the bullet styling from the
    master (Arial / Calibri, 18 pt, dot bullets). We just feed it text.
    """
    tf = ph.text_frame
    tf.word_wrap = True
    for i, line in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        for r in list(p.runs):
            r.text = ""
        run = p.add_run()
        run.text = line
        if size is not None:
            run.font.size = Pt(size)


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------
def _fit_dims(img: Path, max_w_emu: int, max_h_emu: int) -> tuple[int, int]:
    from PIL import Image
    with Image.open(img) as im:
        iw, ih = im.size
    ar = iw / ih
    w = max_w_emu
    h = int(w / ar)
    if h > max_h_emu:
        h = max_h_emu
        w = int(h * ar)
    return w, h


def add_image_in_box(slide, img: Path, left: int, top: int, width: int, height: int):
    """Center-fit `img` inside the given EMU box. No-op if image missing."""
    if not img.exists():
        return None
    w, h = _fit_dims(img, width, height)
    x = left + (width - w) // 2
    y = top + (height - h) // 2
    return slide.shapes.add_picture(str(img), x, y, width=w, height=h)


def add_caption(slide, text: str, left: int, top: int, width: int, height: int):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text
    run.font.size = Pt(12)
    run.font.italic = True
    run.font.color.rgb = MUTED
    return tb


# ---------------------------------------------------------------------------
# Slide builders
# ---------------------------------------------------------------------------
def s_title(prs):
    slide = prs.slides.add_slide(layout(prs, "TITLE"))
    title = slide.placeholders[0]
    subtitle = slide.placeholders[1]

    title.text = ""
    tf = title.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "PocketDRS"
    r.font.bold = True
    r.font.size = Pt(43)
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run()
    r2.text = "Phone-Based Hawk-Eye LBW Decision Review System"
    r2.font.bold = True
    r2.font.size = Pt(24)

    # Subtitle: author block in the BIT "Name, BIT [tab]ID" style.
    subtitle.text = ""
    stf = subtitle.text_frame
    stf.word_wrap = True
    lines = [
        "Niraj Kafle, BIT 7th sem",
        "Lincoln University / Phoenix College, Kathmandu",
        "LC0003001674  •  2026-05-24",
    ]
    for i, line in enumerate(lines):
        p = stf.paragraphs[0] if i == 0 else stf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        for r in list(p.runs):
            r.text = ""
        run = p.add_run()
        run.text = line
        run.font.size = Pt(18)


def s_body(prs, title: str, bullets: list[str]):
    slide = prs.slides.add_slide(layout(prs, "TITLE_AND_BODY"))
    slide.placeholders[0].text = title
    set_bullets(slide.placeholders[1], bullets)
    return slide


def s_title_only_with_image(prs, title: str, img_name: str, caption: str | None = None):
    slide = prs.slides.add_slide(layout(prs, "TITLE_ONLY"))
    slide.placeholders[0].text = title

    # Slide is 10 x 5.625 in. Title occupies T=0.461..1.087. Use 1.20..5.20 in
    # for content with 0.5 in side margins.
    left = Inches(0.5)
    top = Inches(1.20)
    width = Inches(9.0)
    if caption:
        height = Inches(3.55)
    else:
        height = Inches(4.00)
    add_image_in_box(slide, FIG / img_name, left, top, width, height)
    if caption:
        add_caption(slide, caption,
                    left, top + height + Inches(0.05),
                    width, Inches(0.35))
    return slide


def s_two_columns_image_left(prs, title: str, img_name: str, bullets: list[str]):
    slide = prs.slides.add_slide(layout(prs, "TITLE_AND_TWO_COLUMNS"))
    slide.placeholders[0].text = title

    # Left placeholder bounds (from master): L=0.341 T=1.26 W=4.374 H=3.736
    left_ph = slide.placeholders[1]
    box_left = left_ph.left
    box_top = left_ph.top
    box_w = left_ph.width
    box_h = left_ph.height
    # Clear left placeholder text (we will fill it with a picture).
    left_ph.text = ""
    add_image_in_box(slide, FIG / img_name, box_left, box_top, box_w, box_h)

    # Right placeholder gets the bullets.
    right_ph = slide.placeholders[2]
    set_bullets(right_ph, bullets)
    return slide


# ---------------------------------------------------------------------------
# Build deck
# ---------------------------------------------------------------------------
def build():
    prs = open_template()

    # 1
    s_title(prs)

    # 2 Introduction
    s_body(prs, "Introduction", [
        "Amateur cricket has no review system for LBW decisions.",
        "Real Hawk-Eye needs 6 calibrated cameras and costs > USD 250,000.",
        "PocketDRS reconstructs the same decision from one phone video.",
        "Goal: bring DRS-style review to clubs, schools, and net practice.",
    ])

    # 3 Problem Statement
    s_body(prs, "Problem Statement", [
        "Umpires must judge LBW in real time, with no replay.",
        "Mistakes change match outcomes, especially at amateur level.",
        "Existing alternatives need stadium-grade hardware.",
        "No tool today turns a single phone recording into a DRS decision.",
    ])

    # 4 Objectives
    s_body(prs, "Objectives", [
        "General: Build a phone-only system that decides LBW from one video.",
        "Specific (a): Calibrate from 4 + 8 taps.",
        "Specific (b): Detect and track the ball each frame.",
        "Specific (c): Reconstruct the 3D trajectory.",
        "Specific (d): Apply ICC Rule 36.",
        "Specific (e): Render a Hawk-Eye 3D view.",
    ])

    # 5 Scope and Limitations
    s_body(prs, "Scope and Limitations", [
        "Scope: Net / amateur cricket, single phone, red ball, daylight or net lighting.",
        "Limit: Monocular depth from ball-size cue (noisier than multi-camera).",
        "Limit: Day / night camera-noise differences are not modelled.",
    ])

    # 6 Methodology
    s_body(prs, "Methodology", [
        "Iterative incremental development across five sprints.",
        "Each sprint adds one pipeline stage end-to-end.",
        "Real-video regression test on every change.",
        "Synthetic sweep documents accuracy bounds.",
    ])

    # 7 Literature Review
    s_body(prs, "Literature Review (Key References)", [
        "Owens et al. (2003) — original Hawk-Eye, 6-camera reconstruction.",
        "Zhang (2000) — flexible checkerboard calibration.",
        "Fischler & Bolles (1981) — RANSAC robust estimator.",
        "Hartley & Zisserman (2004) — multi-view geometry textbook.",
        "Ponglertnapakorn & Suwajanakorn (2025) — monocular 3D ball tracking.",
    ])

    # 8 System Architecture (image)
    s_title_only_with_image(prs, "System Architecture", "architecture.png")

    # 9 Data Flow Level 0
    slide = prs.slides.add_slide(layout(prs, "TITLE_ONLY"))
    slide.placeholders[0].text = "Data Flow — Level 0"
    # One-line caption above image.
    add_caption(slide,
                "User → App → Backend → CV Pipeline → Result + 3D Viewer",
                Inches(0.5), Inches(1.15), Inches(9.0), Inches(0.35))
    add_image_in_box(slide, FIG / "dfd_level0.png",
                     Inches(0.5), Inches(1.55), Inches(9.0), Inches(3.70))

    # 10 ER diagram
    s_title_only_with_image(prs, "Entity-Relationship Diagram", "er_diagram.png")

    # 11 Use-case
    s_title_only_with_image(prs, "Use-Case Diagram", "use_case_diagram.png")

    # 12 Pipeline 5 steps
    s_body(prs, "Pipeline — 5 Steps", [
        "1. Calibrate — solvePnP on 4 pitch corners + 8 stump-quad pts; auto-fits FOV.",
        "2. Detect — MOG2 motion + HSV colour + ROI; YOLO fallback.",
        "3. Link — RANSAC over constant-acceleration model; outputs (u, v, t) track.",
        "4. Reconstruct 3D — depth = fx · R / r_px; gravity-fit + bounce reflection.",
        "5. Decide — ICC Rule 36 (pitched / impact / hitting) + 25 mm umpire band.",
    ])

    # 13 test3.mp4
    s_two_columns_image_left(prs, "Real-Video Test — test3.mp4",
        "test3_overlay.png", [
            "Indoor net, zoomed phone (37° FOV pinned).",
            "29 detections, 28 RANSAC inliers.",
            "Speed: 64.1 km/h",
            "Decision: NOT OUT — missing stumps.",
            "Reproj 16.6 px, length auto-fit 12.7 m.",
        ])

    # 14 3D reconstruction
    s_title_only_with_image(prs,
        "3D Hawk-Eye Reconstruction",
        "test3_3d_path.png",
        caption="Tracked path (red) + predicted continuation (gold dashed) + LBW corridor (yellow band).")

    # 15 Synthetic Validation
    s_body(prs, "Synthetic Validation", [
        "8 scenarios swept (lines / lengths / pace) — 8/8 PASS.",
        "Mean speed error: 26.7 km/h • bounce: 60 cm • impact: 63 cm.",
        "Thresholds set to honest monocular bounds (one phone ≠ 6-camera).",
        "Pipeline rejects untrustworthy fits — never returns a confident-wrong decision.",
    ])

    # 16 Conclusion
    s_body(prs, "Conclusion", [
        "Built end-to-end phone-only LBW DRS pipeline.",
        "Real-video clip (test3) passes with overlay + 3D view.",
        "Monocular accuracy is bounded; the system is honest about it.",
        "Future: stereo phone, learned depth, real-time on-device.",
    ])

    # 17 Thank You
    slide = prs.slides.add_slide(layout(prs, "TITLE"))
    title = slide.placeholders[0]
    sub = slide.placeholders[1]
    title.text = ""
    p = title.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "Thank You — Questions?"
    r.font.bold = True
    r.font.size = Pt(43)
    sub.text = ""
    sp = sub.text_frame.paragraphs[0]
    sp.alignment = PP_ALIGN.CENTER
    sr = sp.add_run()
    sr.text = "contact.me.kafle@gmail.com"
    sr.font.size = Pt(18)

    prs.save(str(OUT))
    return OUT


def _shape_kind(sh) -> str:
    """Classify a shape as 'picture', 'text', 'title', or 'other'.

    We only flag overlaps between content-bearing shapes (text/picture/title).
    Empty placeholders are ignored — they ship from the master with bounds
    but draw nothing on the rendered slide.
    """
    # PICTURE = 13 per MSO_SHAPE_TYPE.
    if sh.shape_type == 13:
        return "picture"
    if sh.is_placeholder:
        idx = sh.placeholder_format.idx
        has_text = sh.has_text_frame and sh.text_frame.text.strip() != ""
        if not has_text:
            return "empty"
        if idx == 0:
            return "title"
        return "text"
    if sh.has_text_frame and sh.text_frame.text.strip() != "":
        return "text"
    return "other"


def _bbox(sh) -> tuple[int, int, int, int]:
    return (sh.left, sh.top, sh.left + sh.width, sh.top + sh.height)


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    """Return intersection area in EMU; 0 if no overlap."""
    dx = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    dy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return dx * dy


def _label(sh, kind: str) -> str:
    name = sh.name or "?"
    if kind in ("text", "title"):
        txt = sh.text_frame.text.replace("\n", " | ")
        if len(txt) > 40:
            txt = txt[:37] + "..."
        return f"{kind}:{name!r}={txt!r}"
    return f"{kind}:{name!r}"


def verify(path: Path):
    prs = Presentation(str(path))
    SLIDE_H = prs.slide_height
    TITLE_REGION_BOTTOM = Inches(1.10)  # title area top-region (titles live above this)
    print(f"Wrote {path}")
    print(f"Slides: {len(prs.slides)}")
    print(f"Slide size: {prs.slide_width/914400:.2f} x {prs.slide_height/914400:.3f} in")
    print()
    total_overlaps = 0
    print("Slide-by-slide:")
    for i, sl in enumerate(prs.slides, start=1):
        title = ""
        for ph in sl.placeholders:
            if ph.placeholder_format.idx == 0 and ph.has_text_frame:
                title = ph.text_frame.text.replace("\n", " | ")
                break
        shapes = list(sl.shapes)
        n_pics = sum(1 for s in shapes if s.shape_type == 13)
        print(f"  {i:02d}. layout={sl.slide_layout.name:<28} shapes={len(shapes):2d} pics={n_pics} "
              f"title={title!r}")

        # Build overlap candidates: only content-bearing shapes.
        contentful = []
        for sh in shapes:
            k = _shape_kind(sh)
            if k in ("empty", "other"):
                continue
            contentful.append((sh, k, _bbox(sh)))

        # Pairwise overlap check. Title-vs-body overlap is allowed only when
        # the title is in the very top band (≤ TITLE_REGION_BOTTOM); any
        # other text/picture overlap is a real problem.
        for a_idx in range(len(contentful)):
            for b_idx in range(a_idx + 1, len(contentful)):
                sh_a, k_a, bb_a = contentful[a_idx]
                sh_b, k_b, bb_b = contentful[b_idx]
                area = _overlap(bb_a, bb_b)
                if area <= 0:
                    continue
                # Title vs another shape sitting fully below the title band → OK.
                if k_a == "title" and bb_b[1] >= TITLE_REGION_BOTTOM:
                    continue
                if k_b == "title" and bb_a[1] >= TITLE_REGION_BOTTOM:
                    continue
                total_overlaps += 1
                print(f"        OVERLAP: {_label(sh_a, k_a)}  <>  {_label(sh_b, k_b)}")

        # Off-slide check: any contentful shape extending below the slide is bad.
        for sh, k, bb in contentful:
            if bb[3] > SLIDE_H:
                overflow_in = (bb[3] - SLIDE_H) / 914400
                total_overlaps += 1
                print(f"        OFF-SLIDE: {_label(sh, k)} extends {overflow_in:.2f} in below slide")

    print()
    if total_overlaps == 0:
        print("Result: no overlaps detected.")
    else:
        print(f"Result: {total_overlaps} overlap/off-slide issue(s) detected.")
    return total_overlaps


if __name__ == "__main__":
    out = build()
    verify(out)
