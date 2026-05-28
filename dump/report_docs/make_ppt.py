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
from pptx.enum.shapes import MSO_SHAPE

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE.parent / "BIT Project PPT Sample.pptx"
FIG = BASE / "figures"
OUT = BASE / "pocketdrs_presentation.pptx"

MUTED = RGBColor(0x60, 0x60, 0x60)

# Brand palette (sourced from the BIT template theme1.xml clrScheme).
ACCENT  = RGBColor(0x42, 0x85, 0xF4)  # accent1 — primary blue
DARK    = RGBColor(0x21, 0x21, 0x21)  # accent2 — near-black
SLATE   = RGBColor(0x78, 0x90, 0x9C)  # accent3 — blue-grey
AMBER   = RGBColor(0xFF, 0xAB, 0x40)  # accent4 — amber highlight
TEAL    = RGBColor(0x00, 0x97, 0xA7)  # accent5 — teal
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
TEXT    = RGBColor(0x21, 0x21, 0x21)


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


def add_accent_bar(slide, color=ACCENT, *, left=Inches(0.29), top=Inches(0.38),
                   width=Inches(0.62), height=Inches(0.06)):
    """Draw a small coloured stripe under the title to brand each content slide."""
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    bar.line.fill.background()
    bar.fill.solid()
    bar.fill.fore_color.rgb = color
    bar.shadow.inherit = False
    return bar


def style_title(slide, *, color=DARK, size=28, bold=True):
    """Re-style the layout's title placeholder so titles read as a confident heading."""
    ph = slide.placeholders[0]
    tf = ph.text_frame
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.bold = bold
            r.font.size = Pt(size)
            r.font.color.rgb = color


def add_section_index(slide, idx: str, label: str, *, top=Inches(0.18)):
    """Tiny eyebrow text in the top-left ('01 · BACKGROUND') for navigability."""
    tb = slide.shapes.add_textbox(Inches(0.30), top, Inches(6.0), Inches(0.25))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    run = p.add_run()
    run.text = f"{idx}  ·  {label.upper()}"
    run.font.size = Pt(10)
    run.font.bold = True
    run.font.color.rgb = ACCENT


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


def s_body(prs, title: str, bullets: list[str], *, section: str | None = None,
           bullet_size: int = 18):
    slide = prs.slides.add_slide(layout(prs, "TITLE_AND_BODY"))
    slide.placeholders[0].text = title
    set_bullets(slide.placeholders[1], bullets, size=bullet_size)
    style_title(slide, color=DARK, size=28)
    add_accent_bar(slide)
    if section:
        add_section_index(slide, *section.split("|", 1))
    return slide


def s_section(prs, idx: str, title: str, subtitle: str | None = None):
    """Chapter divider using the master's SECTION_HEADER layout."""
    slide = prs.slides.add_slide(layout(prs, "SECTION_HEADER"))
    ph = slide.placeholders[0]
    tf = ph.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    for r in list(p.runs):
        r.text = ""
    r1 = p.add_run()
    r1.text = title
    r1.font.bold = True
    r1.font.size = Pt(40)
    r1.font.color.rgb = DARK

    # Big section number in the top-left.
    tb = slide.shapes.add_textbox(Inches(0.34), Inches(1.20), Inches(6.0), Inches(0.6))
    p2 = tb.text_frame.paragraphs[0]
    p2.alignment = PP_ALIGN.LEFT
    rn = p2.add_run()
    rn.text = idx
    rn.font.bold = True
    rn.font.size = Pt(64)
    rn.font.color.rgb = ACCENT

    if subtitle:
        sb = slide.shapes.add_textbox(Inches(0.34), Inches(3.35), Inches(9.32),
                                      Inches(0.6))
        sp = sb.text_frame.paragraphs[0]
        sp.alignment = PP_ALIGN.LEFT
        sr = sp.add_run()
        sr.text = subtitle
        sr.font.size = Pt(16)
        sr.font.color.rgb = MUTED

    # Coloured rule below the title to anchor the layout.
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0.34), Inches(3.18),
                                  Inches(1.20), Inches(0.05))
    rule.line.fill.background()
    rule.fill.solid()
    rule.fill.fore_color.rgb = ACCENT
    return slide


def s_main_point(prs, statement: str, attribution: str | None = None):
    """One-claim slide using the master's MAIN_POINT layout."""
    slide = prs.slides.add_slide(layout(prs, "MAIN_POINT"))
    ph = slide.placeholders[0]
    tf = ph.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    for r in list(p.runs):
        r.text = ""
    r = p.add_run()
    r.text = statement
    r.font.bold = True
    r.font.size = Pt(36)
    r.font.color.rgb = DARK
    if attribution:
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.LEFT
        r2 = p2.add_run()
        r2.text = attribution
        r2.font.size = Pt(16)
        r2.font.color.rgb = ACCENT
        r2.font.bold = False
    return slide


def s_big_number(prs, number: str, label: str, *, sub: str | None = None,
                 number_color=ACCENT):
    """Headline-stat slide using the master's BIG_NUMBER layout."""
    slide = prs.slides.add_slide(layout(prs, "BIG_NUMBER"))
    num_ph = slide.placeholders[0]
    lbl_ph = slide.placeholders[1]

    tf = num_ph.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    for r in list(p.runs):
        r.text = ""
    r = p.add_run()
    r.text = number
    r.font.bold = True
    r.font.size = Pt(140)
    r.font.color.rgb = number_color

    tf2 = lbl_ph.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    p2.alignment = PP_ALIGN.CENTER
    for r in list(p2.runs):
        r.text = ""
    r2 = p2.add_run()
    r2.text = label
    r2.font.size = Pt(22)
    r2.font.bold = True
    r2.font.color.rgb = DARK
    if sub:
        p3 = tf2.add_paragraph()
        p3.alignment = PP_ALIGN.CENTER
        r3 = p3.add_run()
        r3.text = sub
        r3.font.size = Pt(14)
        r3.font.color.rgb = MUTED
    return slide


def s_text_two_columns(prs, title: str, left_head: str, left_bullets: list[str],
                       right_head: str, right_bullets: list[str], *,
                       section: str | None = None):
    """Two text columns with bolded sub-headings — good for stage breakdowns."""
    slide = prs.slides.add_slide(layout(prs, "TITLE_AND_TWO_COLUMNS"))
    slide.placeholders[0].text = title
    style_title(slide, color=DARK, size=26)
    add_accent_bar(slide)
    if section:
        add_section_index(slide, *section.split("|", 1))

    def _fill(ph, head, bullets):
        tf = ph.text_frame
        tf.word_wrap = True
        # First paragraph: bold sub-head in accent.
        p = tf.paragraphs[0]
        for r in list(p.runs):
            r.text = ""
        rh = p.add_run()
        rh.text = head
        rh.font.bold = True
        rh.font.size = Pt(15)
        rh.font.color.rgb = ACCENT
        for b in bullets:
            pp = tf.add_paragraph()
            pp.level = 0
            for r in list(pp.runs):
                r.text = ""
            rb = pp.add_run()
            rb.text = b
            rb.font.size = Pt(15)
            rb.font.color.rgb = TEXT

    _fill(slide.placeholders[1], left_head, left_bullets)
    _fill(slide.placeholders[2], right_head, right_bullets)
    return slide


def s_title_only_with_image(prs, title: str, img_name: str, caption: str | None = None,
                            *, section: str | None = None):
    slide = prs.slides.add_slide(layout(prs, "TITLE_ONLY"))
    slide.placeholders[0].text = title
    style_title(slide, color=DARK, size=26)
    add_accent_bar(slide)
    if section:
        add_section_index(slide, *section.split("|", 1))

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


def s_two_columns_image_left(prs, title: str, img_name: str, bullets: list[str],
                             *, section: str | None = None):
    slide = prs.slides.add_slide(layout(prs, "TITLE_AND_TWO_COLUMNS"))
    slide.placeholders[0].text = title
    style_title(slide, color=DARK, size=26)
    add_accent_bar(slide)
    if section:
        add_section_index(slide, *section.split("|", 1))

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


def s_two_images(prs, title: str, left_img: str, right_img: str,
                 left_cap: str | None = None, right_cap: str | None = None,
                 *, section: str | None = None):
    """Side-by-side images with optional captions."""
    slide = prs.slides.add_slide(layout(prs, "TITLE_ONLY"))
    slide.placeholders[0].text = title
    style_title(slide, color=DARK, size=26)
    add_accent_bar(slide)
    if section:
        add_section_index(slide, *section.split("|", 1))

    box_top = Inches(1.25)
    box_w = Inches(4.40)
    box_h = Inches(3.50)
    add_image_in_box(slide, FIG / left_img,  Inches(0.34), box_top, box_w, box_h)
    add_image_in_box(slide, FIG / right_img, Inches(5.26), box_top, box_w, box_h)
    if left_cap:
        add_caption(slide, left_cap, Inches(0.34), box_top + box_h + Inches(0.05),
                    box_w, Inches(0.40))
    if right_cap:
        add_caption(slide, right_cap, Inches(5.26), box_top + box_h + Inches(0.05),
                    box_w, Inches(0.40))
    return slide


# ---------------------------------------------------------------------------
# Build deck
# ---------------------------------------------------------------------------
def build():
    prs = open_template()

    # ----- 01  TITLE -----
    s_title(prs)

    # ----- 02  SECTION DIVIDER — Problem & Goal -----
    s_section(prs, "01", "Problem & Goal",
              "Why a single phone needs a Hawk-Eye of its own.")

    # ----- 03  Problem Statement -----
    s_body(prs, "Problem Statement", [
        "Umpires call LBW in real time, with no replay.",
        "Real Hawk-Eye needs six cameras and costs > USD 250,000.",
        "Clubs, schools, and nets have none of that hardware.",
        "Nothing today turns one phone clip into a DRS verdict.",
    ], section="01|Problem & Goal", bullet_size=20)

    # ----- 04  Key claim -----
    s_main_point(prs,
        "One phone. Four taps. A DRS-grade LBW verdict in 90 seconds.",
        attribution="PocketDRS — the thesis in one line.")

    # ----- 05  Objectives -----
    s_body(prs, "Objectives", [
        "Build a phone-only system that decides LBW from one video.",
        "Calibrate the camera from 4 pitch + 4 stump taps.",
        "Detect, track, and lift the ball into 3D world coordinates.",
        "Apply ICC Rule 36 with an umpire's-call band for monocular noise.",
        "Render a Hawk-Eye 3D view alongside the verdict.",
    ], section="01|Problem & Goal", bullet_size=18)

    # ----- 06  Scope & Limitations -----
    s_text_two_columns(prs, "Scope & Limitations",
        "In scope",
        [
            "Net + amateur cricket.",
            "Single phone, handheld.",
            "Red ball, daylight or net lighting.",
        ],
        "Out of scope",
        [
            "Stadium broadcast video.",
            "Day/night camera-noise modelling.",
            "Spin-axis or seam-orientation analysis.",
        ],
        section="01|Problem & Goal")

    # ----- 07  SECTION DIVIDER — Background -----
    s_section(prs, "02", "Background",
              "Five papers that PocketDRS leans on.")

    # ----- 08  Literature Review -----
    s_body(prs, "Literature Review", [
        "Owens et al. 2003 — six-camera Hawk-Eye reconstruction.",
        "Zhang 2000 — flexible checkerboard intrinsic calibration.",
        "Fischler & Bolles 1981 — RANSAC robust model fitting.",
        "Hartley & Zisserman 2004 — multi-view geometry foundations.",
        "Ponglertnapakorn & Suwajanakorn 2025 — monocular 3D ball tracking.",
    ], section="02|Background", bullet_size=18)

    # ----- 09  SECTION DIVIDER — System Design -----
    s_section(prs, "03", "System Design",
              "Components, data flow, and the path of a delivery through the stack.")

    # ----- 10  Architecture -----
    s_title_only_with_image(prs, "System Architecture", "architecture.png",
                            section="03|System Design")

    # ----- 11  DFD Level 0 -----
    s_title_only_with_image(prs, "Data Flow — Level 0", "dfd_level0.png",
        caption="User → App → Backend → CV Pipeline → Verdict + 3D Viewer.",
        section="03|System Design")

    # ----- 12  ER -----
    s_title_only_with_image(prs, "Entity-Relationship Diagram", "er_diagram.png",
                            section="03|System Design")

    # ----- 13  Use-Case -----
    s_title_only_with_image(prs, "Use-Case Diagram", "use_case_diagram.png",
                            section="03|System Design")

    # ----- 14  Sequence -----
    s_title_only_with_image(prs, "Sequence — Capture to Verdict",
                            "sequence_diagram.png",
                            section="03|System Design")

    # ----- 15  SECTION DIVIDER — CV Pipeline -----
    s_section(prs, "04", "CV Pipeline",
              "Five stages from pixels to verdict.")

    # ----- 16  Pipeline overview -----
    s_body(prs, "Pipeline — Five Stages", [
        "Calibrate — solvePnP on 4 pitch + 4 stump taps; auto-fits FOV.",
        "Detect — MOG2 motion + HSV gating + ROI mask; YOLOv8 fallback.",
        "Link — RANSAC over a constant-acceleration model.",
        "Reconstruct — depth from ball radius + bounce-aware projectile fit.",
        "Decide — ICC Rule 36 with one-ball-radius umpire band.",
    ], section="04|CV Pipeline", bullet_size=18)

    # ----- 17  Stage 1 Calibration -----
    s_text_two_columns(prs, "Stage 1 — Calibration",
        "Inputs",
        [
            "4 pitch-corner taps (homography seed).",
            "4 stump-base/top taps (pose refinement).",
            "Optional FOV; otherwise auto-fit from geometry.",
        ],
        "Method",
        [
            "OpenCV solvePnP planar PnP.",
            "Mirror disambiguation: reject below-ground poses.",
            "Joint FOV + pitch-length non-linear refinement.",
        ],
        section="04|CV Pipeline")

    # ----- 18  Stage 2 Detection -----
    s_text_two_columns(prs, "Stage 2 — Ball Detection",
        "Primary detector",
        [
            "MOG2 background subtraction.",
            "HSV red-channel gating.",
            "Pitch-aligned ROI mask.",
        ],
        "Guards & fallback",
        [
            "Fixed-clutter suppression (>30% recurring drops).",
            "YOLOv8 learned-ball fallback for low contrast.",
            "Area + circularity + aspect-ratio filters.",
        ],
        section="04|CV Pipeline")

    # ----- 19  Stage 3 Linking -----
    s_text_two_columns(prs, "Stage 3 — Trajectory Linking",
        "Model",
        [
            "RANSAC over constant-acceleration fit.",
            "2D (u, v) image-plane parabola.",
            "Inlier set defines the track.",
        ],
        "Acceptance",
        [
            "≥ 25 image points after RANSAC.",
            "Image-RMS < 25 px on the synthetic harness.",
            "Returns ``no trajectory'' on degenerate input — never bluffs.",
        ],
        section="04|CV Pipeline")

    # ----- 20  Stage 4 3D Reconstruction -----
    s_text_two_columns(prs, "Stage 4 — 3D Reconstruction",
        "Depth cue",
        [
            "depth = fₓ · R_ball / r_px",
            "R_ball = 0.036 m (cricket-ball radius).",
            "Anchored at the bounce frame for stability.",
        ],
        "Projectile fit",
        [
            "Gravity-fit pre- and post-bounce.",
            "Vertical restitution e = 0.55.",
            "Bounce reflection at the pitch plane (Ribnick 2009).",
        ],
        section="04|CV Pipeline")

    # ----- 21  Stage 5 LBW Decision -----
    s_text_two_columns(prs, "Stage 5 — LBW Decision (ICC Rule 36)",
        "Three checks",
        [
            "Pitched in line — not outside leg.",
            "Impact in line — not outside off.",
            "Hitting stumps — predicted strike inside guard.",
        ],
        "Umpire's-call bands",
        [
            "1 ball radius horizontal margin.",
            "1 ball diameter vertical margin.",
            "Honest about monocular depth noise.",
        ],
        section="04|CV Pipeline")

    # ----- 22  SECTION DIVIDER — Results -----
    s_section(prs, "05", "Results",
              "Real video + 8-scenario synthetic sweep.")

    # ----- 23  Real video overlay -----
    s_two_columns_image_left(prs, "Real-Video Test — test3.mp4",
        "test3_overlay.png", [
            "Indoor net, zoomed phone (37° FOV).",
            "29 detections; 28 RANSAC inliers.",
            "Recovered delivery speed: 64.1 km/h.",
            "Verdict: NOT OUT — misses stumps.",
            "Reproj 16.6 px; pitch length auto-fit 12.7 m.",
        ], section="05|Results")

    # ----- 24  3D reconstruction -----
    s_title_only_with_image(prs, "3D Hawk-Eye View — test3",
        "test3_3d_path.png",
        caption="Tracked path (red) + predicted continuation (gold) + LBW corridor (yellow).",
        section="05|Results")

    # ----- 25  Synthetic summary chart -----
    s_title_only_with_image(prs, "Synthetic Validation — 8 Scenarios",
                            "synth_summary.png",
                            section="05|Results")

    # ----- 26  Big number — synth pass rate -----
    s_big_number(prs, "8 / 8", "synthetic scenarios pass",
                 sub="lines × lengths × pace — 100% within monocular thresholds")

    # ----- 27  App screenshots -----
    s_two_images(prs, "Mobile App — Calibration & Result",
                 "app_calibration.png", "app_result_out.png",
                 left_cap="Calibration screen (8.6 px reprojection error).",
                 right_cap="Result screen — verdict + 3D viewer.",
                 section="05|Results")

    # ----- 28  Decision cases gallery -----
    s_two_images(prs, "Decision Cases — OUT vs NOT OUT",
                 "case_out.png", "case_not_out.png",
                 left_cap="OUT — track hits the stumps cleanly.",
                 right_cap="NOT OUT — track sails over the bails.",
                 section="05|Results")

    # ----- 29  SECTION DIVIDER — Conclusion -----
    s_section(prs, "06", "Conclusion",
              "What ships, and what comes next.")

    # ----- 30  Conclusion -----
    s_body(prs, "Conclusion", [
        "Built an end-to-end phone-only LBW review pipeline.",
        "Real-video clip passes with overlay + 3D viewer.",
        "Synthetic sweep: 8/8 scenarios inside the honest thresholds.",
        "Monocular bounds are documented — the system refuses bad fits.",
    ], section="06|Conclusion", bullet_size=20)

    # ----- 31  Future work -----
    s_body(prs, "Future Work", [
        "Stereo capture from two phones for true depth.",
        "Learned monocular depth (Ponglertnapakorn-style).",
        "On-device real-time inference (no server round-trip).",
        "Spin and seam-orientation overlays for net coaching.",
    ], section="06|Conclusion", bullet_size=20)

    # ----- 32  Thank You -----
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
    r.font.color.rgb = DARK
    sub.text = ""
    sp = sub.text_frame.paragraphs[0]
    sp.alignment = PP_ALIGN.CENTER
    sr = sp.add_run()
    sr.text = "Niraj Kafle  •  contact.me.kafle@gmail.com"
    sr.font.size = Pt(18)
    sr.font.color.rgb = ACCENT

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
