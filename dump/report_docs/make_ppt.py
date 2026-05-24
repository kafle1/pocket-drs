"""Build the PocketDRS final-defense presentation.

Modern, minimal, dark-themed deck for a final-year project defense.
Design system:
  - 16:9 (13.33in x 7.5in), background #0d1117 (deep charcoal)
  - Accents: #fbbf24 gold (highlight), #22c55e green (pass), #ef4444 red (fail)
  - Body text #f5f5f5 white, captions #9ca3af muted grey
  - Single sans-serif family (Inter; falls back to Calibri).
  - Title 36pt, body 22pt, caption 16pt. Never below 14pt.
  - 8% inner margin. One concept per slide. <= 4 bullets, <= 10 words each.

Reproducible: re-run to regenerate dump/report_docs/pocketdrs_presentation.pptx.
Requires python-pptx (server venv).
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu, Inches, Pt

BASE = Path(__file__).resolve().parent
FIG = BASE / "figures"
OUT = BASE / "pocketdrs_presentation.pptx"

# --- Design tokens ----------------------------------------------------------
BG       = RGBColor(0x0D, 0x11, 0x17)   # deep charcoal
SURFACE  = RGBColor(0x16, 0x1B, 0x22)   # slightly lifted card
BORDER   = RGBColor(0x30, 0x36, 0x3D)   # hairline divider
TEXT     = RGBColor(0xF5, 0xF5, 0xF5)   # primary white
MUTED    = RGBColor(0x9C, 0xA3, 0xAF)   # caption grey
GOLD     = RGBColor(0xFB, 0xBF, 0x24)   # highlight / accent
GREEN    = RGBColor(0x22, 0xC5, 0x5E)   # pass
RED      = RGBColor(0xEF, 0x44, 0x44)   # fail

FONT = "Inter"   # PowerPoint falls back to Calibri if Inter not installed.

# --- Layout grid (16:9) -----------------------------------------------------
SLIDE_W = Inches(13.33)
SLIDE_H = Inches(7.5)
MARGIN  = Inches(1.07)              # ~8% of width
TITLE_TOP = Inches(0.65)
TITLE_H   = Inches(0.85)
RULE_Y    = Inches(1.55)            # gold underline below title
BODY_TOP  = Inches(1.95)
BODY_H    = SLIDE_H - BODY_TOP - Inches(0.80)
CONTENT_W = SLIDE_W - 2 * MARGIN

# --- Presentation -----------------------------------------------------------
prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
BLANK = prs.slide_layouts[6]


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def _new_slide():
    slide = prs.slides.add_slide(BLANK)
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG
    return slide


def _text(slide, x, y, w, h, text, *, size=22, bold=False, color=TEXT,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return tb


def _rect(slide, x, y, w, h, fill=SURFACE, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(0.75)
    shp.shadow.inherit = False
    return shp


def _title_block(slide, title, eyebrow=None):
    if eyebrow:
        _text(slide, MARGIN, Inches(0.40), CONTENT_W, Inches(0.30),
              eyebrow.upper(), size=12, bold=True, color=GOLD)
    _text(slide, MARGIN, TITLE_TOP, CONTENT_W, TITLE_H,
          title, size=32, bold=True, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    # Gold accent rule.
    _rect(slide, MARGIN, RULE_Y, Inches(0.6), Pt(3), fill=GOLD)


def _bullets(slide, x, y, w, h, items, *, size=22, line_spacing=1.25,
             space_after=10, color=TEXT):
    """Clean bullet list, one bullet per line, generous spacing."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        # Gold dot
        r1 = p.add_run()
        r1.text = "•   "
        r1.font.name = FONT
        r1.font.size = Pt(size)
        r1.font.bold = True
        r1.font.color.rgb = GOLD
        # Body
        r2 = p.add_run()
        r2.text = item
        r2.font.name = FONT
        r2.font.size = Pt(size)
        r2.font.color.rgb = color


def _fit_image(img: Path, max_w: int, max_h: int) -> tuple[int, int]:
    """Aspect-correct fit using Pillow (avoids OpenCV dep)."""
    from PIL import Image
    with Image.open(img) as im:
        w, h = im.size
    ar = w / h
    width, height = max_w, int(max_w / ar)
    if height > max_h:
        height, width = max_h, int(max_h * ar)
    return width, height


def _add_image_or_placeholder(slide, img: Path, x, y, w, h, *, caption=None):
    """Center-fits image into the (x,y,w,h) box. Placeholder card if missing."""
    if not img.exists():
        _rect(slide, x, y, w, h, fill=SURFACE, line=BORDER)
        _text(slide, x, y, w, h, f"[ {img.name} ]",
              size=14, color=MUTED, align=PP_ALIGN.CENTER,
              anchor=MSO_ANCHOR.MIDDLE, italic=True)
    else:
        iw, ih = _fit_image(img, int(w), int(h))
        left = int(x) + (int(w) - iw) // 2
        top  = int(y) + (int(h) - ih) // 2
        slide.shapes.add_picture(str(img), left, top, width=iw, height=ih)
    if caption:
        _text(slide, x, y + h + Inches(0.10), w, Inches(0.30),
              caption, size=14, color=MUTED, align=PP_ALIGN.CENTER)


def _page_footer(slide, n, total):
    _text(slide, MARGIN, SLIDE_H - Inches(0.45),
          CONTENT_W, Inches(0.25),
          f"PocketDRS  |  Niraj Kafle  |  {n:02d} / {total:02d}",
          size=11, color=MUTED, align=PP_ALIGN.LEFT)


# ---------------------------------------------------------------------------
# Slide templates
# ---------------------------------------------------------------------------
def slide_title():
    slide = _new_slide()
    # Big brand mark
    _text(slide, MARGIN, Inches(2.10), CONTENT_W, Inches(1.40),
          "PocketDRS", size=84, bold=True, color=TEXT,
          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
    # Gold rule
    _rect(slide, MARGIN, Inches(3.55), Inches(0.9), Pt(4), fill=GOLD)
    # Subtitle
    _text(slide, MARGIN, Inches(3.85), CONTENT_W, Inches(0.55),
          "Phone-Based Hawk-Eye LBW Decision Review System",
          size=24, color=MUTED, align=PP_ALIGN.LEFT)

    # Author block bottom-right
    box_w, box_h = Inches(5.0), Inches(1.6)
    box_x = SLIDE_W - MARGIN - box_w
    box_y = SLIDE_H - Inches(0.8) - box_h
    lines = [
        ("Niraj Kafle", 16, True, TEXT),
        ("BIT, 7th Semester", 14, False, MUTED),
        ("Lincoln University / Phoenix College, Kathmandu", 14, False, MUTED),
        ("Student ID: LC0003001674", 14, False, MUTED),
        ("2026-05-24", 14, False, GOLD),
    ]
    tb = slide.shapes.add_textbox(box_x, box_y, box_w, box_h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    for i, (txt, sz, bold, col) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.RIGHT
        p.space_after = Pt(2)
        r = p.add_run()
        r.text = txt
        r.font.name = FONT
        r.font.size = Pt(sz)
        r.font.bold = bold
        r.font.color.rgb = col


def slide_problem():
    slide = _new_slide()
    _title_block(slide, "The Problem", eyebrow="01  /  Motivation")
    # Two-column statement. Left big quote, right supporting line.
    quote_w = int(CONTENT_W * 0.62)
    _text(slide, MARGIN, BODY_TOP + Inches(0.30),
          quote_w, Inches(3.5),
          "Cricket umpires get LBW decisions wrong.",
          size=38, bold=True, color=TEXT, anchor=MSO_ANCHOR.TOP)
    _text(slide, MARGIN, BODY_TOP + Inches(1.70),
          quote_w, Inches(2.0),
          "Real Hawk-Eye costs $250,000+ and needs six synchronised high-speed cameras.",
          size=22, color=MUTED, anchor=MSO_ANCHOR.TOP)

    # Right side: stat card
    card_x = MARGIN + quote_w + Inches(0.4)
    card_w = CONTENT_W - quote_w - Inches(0.4)
    _rect(slide, card_x, BODY_TOP + Inches(0.30),
          card_w, Inches(3.6), fill=SURFACE, line=BORDER)
    _text(slide, card_x, BODY_TOP + Inches(0.55),
          card_w, Inches(0.6),
          "HAWK-EYE TODAY", size=12, bold=True,
          color=GOLD, align=PP_ALIGN.CENTER)
    _text(slide, card_x, BODY_TOP + Inches(1.10),
          card_w, Inches(1.2),
          "6", size=96, bold=True, color=TEXT,
          align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, card_x, BODY_TOP + Inches(2.40),
          card_w, Inches(0.5),
          "synchronised cameras",
          size=18, color=MUTED, align=PP_ALIGN.CENTER)
    _text(slide, card_x, BODY_TOP + Inches(3.05),
          card_w, Inches(0.5),
          "$250,000+ per ground",
          size=16, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


def slide_what_it_does():
    slide = _new_slide()
    _title_block(slide, "What PocketDRS Does", eyebrow="02  /  Overview")
    cards = [
        ("01", "Record one phone video", GOLD),
        ("02", "Tap pitch corners + stumps", GOLD),
        ("03", "Get OUT / NOT OUT verdict", GOLD),
    ]
    gap = Inches(0.35)
    cw = int((CONTENT_W - gap * 2) / 3)
    ch = Inches(3.6)
    cy = BODY_TOP + Inches(0.40)
    for i, (num, label, accent) in enumerate(cards):
        cx = MARGIN + i * (cw + gap)
        _rect(slide, cx, cy, cw, ch, fill=SURFACE, line=BORDER)
        _text(slide, cx, cy + Inches(0.40), cw, Inches(0.6),
              num, size=14, bold=True, color=accent,
              align=PP_ALIGN.CENTER)
        _text(slide, cx + Inches(0.40), cy + Inches(1.20),
              cw - Inches(0.80), Inches(2.0),
              label, size=26, bold=True, color=TEXT,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, MARGIN, cy + ch + Inches(0.30),
          CONTENT_W, Inches(0.45),
          "Output includes an interactive 3D Hawk-Eye view.",
          size=16, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


def slide_architecture():
    slide = _new_slide()
    _title_block(slide, "System Architecture", eyebrow="03  /  Architecture")
    img_w = int(CONTENT_W)
    img_h = int(BODY_H - Inches(0.6))
    _add_image_or_placeholder(slide, FIG / "architecture.png",
                              MARGIN, BODY_TOP + Inches(0.10),
                              img_w, img_h)
    _text(slide, MARGIN, BODY_TOP + img_h + Inches(0.25),
          CONTENT_W, Inches(0.35),
          "Flutter app  →  FastAPI backend  →  CV pipeline  →  Three.js viewer",
          size=16, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


def slide_pipeline_overview():
    slide = _new_slide()
    _title_block(slide, "The Pipeline — 5 Steps",
                 eyebrow="04  /  Algorithm")
    steps = [
        ("1", "Calibrate camera from taps (PnP)"),
        ("2", "Detect ball each frame (motion + colour + YOLO)"),
        ("3", "Link detections into one path (RANSAC)"),
        ("4", "Lift 2D path to 3D (depth from size + gravity)"),
        ("5", "Apply ICC Rule 36 (pitched / impact / hitting)"),
    ]
    row_h = Inches(0.78)
    gap_y = Inches(0.12)
    total_h = len(steps) * row_h + (len(steps) - 1) * gap_y
    y = BODY_TOP + (BODY_H - total_h) // 2
    for i, (num, label) in enumerate(steps):
        ry = y + i * (row_h + gap_y)
        # number disc
        _rect(slide, MARGIN, ry, Inches(0.78), row_h, fill=GOLD)
        _text(slide, MARGIN, ry, Inches(0.78), row_h,
              num, size=28, bold=True, color=BG,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        # label
        _text(slide, MARGIN + Inches(1.10), ry,
              CONTENT_W - Inches(1.10), row_h,
              label, size=22, color=TEXT,
              anchor=MSO_ANCHOR.MIDDLE)


def slide_split_bullets(eyebrow, title, image: Path, bullets, caption=None):
    """Image left (55% of content), bullets right; optional caption strip."""
    slide = _new_slide()
    _title_block(slide, title, eyebrow=eyebrow)
    img_w = int(CONTENT_W * 0.55)
    txt_x = MARGIN + img_w + Inches(0.40)
    txt_w = CONTENT_W - img_w - Inches(0.40)

    cap_h = Inches(0.40) if caption else Inches(0.0)
    img_box_h = int(BODY_H - cap_h - (Inches(0.10) if caption else 0))
    _add_image_or_placeholder(slide, image,
                              MARGIN, BODY_TOP,
                              img_w, img_box_h)
    _bullets(slide, txt_x, BODY_TOP + Inches(0.20),
             txt_w, BODY_H,
             bullets, size=20, line_spacing=1.25, space_after=14)
    if caption:
        _text(slide, MARGIN, BODY_TOP + img_box_h + Inches(0.10),
              img_w, cap_h,
              caption, size=14, color=MUTED,
              align=PP_ALIGN.CENTER, italic=True)


def slide_lbw_logic():
    slide = _new_slide()
    _title_block(slide, "Step 5 — LBW Decision (ICC Rule 36)",
                 eyebrow="09  /  Decision logic")
    checks = [
        ("Pitched in line?", "Bounce inside leg-stump line"),
        ("Impact in line?", "Pad strike inside stump corridor"),
        ("Hitting stumps?", "Predicted path intersects stumps"),
    ]
    gap = Inches(0.30)
    cw = int((CONTENT_W - gap * 2) / 3)
    ch = Inches(2.4)
    cy = BODY_TOP + Inches(0.15)
    for i, (q, sub) in enumerate(checks):
        cx = MARGIN + i * (cw + gap)
        _rect(slide, cx, cy, cw, ch, fill=SURFACE, line=BORDER)
        _text(slide, cx, cy + Inches(0.35), cw, Inches(0.5),
              f"CHECK {i+1}", size=12, bold=True, color=GOLD,
              align=PP_ALIGN.CENTER)
        _text(slide, cx + Inches(0.30), cy + Inches(0.90),
              cw - Inches(0.60), Inches(0.7),
              q, size=22, bold=True, color=TEXT,
              align=PP_ALIGN.CENTER)
        _text(slide, cx + Inches(0.30), cy + Inches(1.60),
              cw - Inches(0.60), Inches(0.6),
              sub, size=14, color=MUTED, align=PP_ALIGN.CENTER, italic=True)

    # Verdict strip
    strip_y = cy + ch + Inches(0.40)
    strip_h = Inches(1.0)
    _rect(slide, MARGIN, strip_y, CONTENT_W, strip_h,
          fill=SURFACE, line=BORDER)
    # Three coloured tokens inline
    tb = slide.shapes.add_textbox(MARGIN, strip_y, CONTENT_W, strip_h)
    tf = tb.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = Emu(0); tf.margin_right = Emu(0)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER

    def _seg(text, color, bold=True, size=20):
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color

    _seg("All three YES → ", TEXT, bold=False)
    _seg("OUT", GREEN)
    _seg("     Hairline → ", TEXT, bold=False)
    _seg("UMPIRES CALL", GOLD)
    _seg("     Any NO → ", TEXT, bold=False)
    _seg("NOT OUT", RED)


def slide_decisions_grid():
    slide = _new_slide()
    _title_block(slide, "Live App — Three Verdicts",
                 eyebrow="10  /  Output")
    imgs = [
        (FIG / "case_out.png", "OUT", GREEN),
        (FIG / "case_not_out.png", "NOT OUT", RED),
        (FIG / "case_umpires_call.png", "UMPIRES CALL", GOLD),
    ]
    gap = Inches(0.30)
    cw = int((CONTENT_W - gap * 2) / 3)
    cap_h = Inches(0.55)
    img_h = int(BODY_H - cap_h - Inches(0.15))
    for i, (img, label, col) in enumerate(imgs):
        cx = MARGIN + i * (cw + gap)
        _add_image_or_placeholder(slide, img, cx, BODY_TOP, cw, img_h)
        _text(slide, cx, BODY_TOP + img_h + Inches(0.15),
              cw, cap_h,
              label, size=20, bold=True, color=col,
              align=PP_ALIGN.CENTER)


def slide_3d_view():
    slide = _new_slide()
    _title_block(slide, "3D Hawk-Eye View", eyebrow="13  /  Visualisation")
    img_w = int(CONTENT_W * 0.82)
    img_x = MARGIN + (int(CONTENT_W) - img_w) // 2
    img_h = int(BODY_H - Inches(0.55))
    _add_image_or_placeholder(slide, FIG / "test3_3d_path.png",
                              img_x, BODY_TOP, img_w, img_h)
    _text(slide, MARGIN, BODY_TOP + img_h + Inches(0.20),
          CONTENT_W, Inches(0.35),
          "Tracked path (solid red)  +  predicted continuation (dashed gold)  +  LBW corridor",
          size=14, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


def slide_hardened():
    slide = _new_slide()
    _title_block(slide, "What’s Hardened", eyebrow="15  /  Robustness")
    items = [
        ("01", "Video truncation guard for real phone HEVCs"),
        ("02", "Calibration rejection if reprojection > 8 px"),
        ("03", "3D fit rejection if RMS > 1.0 m"),
        ("04", "Frame-index seeking for sparse HEVC keyframes"),
        ("05", "Never produces a confident-wrong decision"),
    ]
    row_h = Inches(0.68)
    gap_y = Inches(0.12)
    total_h = len(items) * row_h + (len(items) - 1) * gap_y
    y = BODY_TOP + (BODY_H - total_h) // 2
    for i, (num, label) in enumerate(items):
        ry = y + i * (row_h + gap_y)
        _text(slide, MARGIN, ry, Inches(0.9), row_h,
              num, size=20, bold=True, color=GOLD,
              anchor=MSO_ANCHOR.MIDDLE)
        _text(slide, MARGIN + Inches(1.05), ry,
              CONTENT_W - Inches(1.05), row_h,
              label, size=20, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)


def slide_stack():
    slide = _new_slide()
    _title_block(slide, "Stack", eyebrow="16  /  Technology")
    rows = [
        ("Mobile",     "Flutter"),
        ("Backend",    "FastAPI  +  Python"),
        ("Computer Vision", "OpenCV  +  NumPy  +  SciPy"),
        ("Detector",   "Ultralytics YOLO"),
        ("3D Viewer",  "Three.js"),
        ("Cloud",      "Firebase  ·  Cloud Run"),
    ]
    row_h = Inches(0.55)
    gap_y = Inches(0.10)
    total_h = len(rows) * row_h + (len(rows) - 1) * gap_y
    y = BODY_TOP + (BODY_H - total_h - Inches(0.6)) // 2
    label_w = Inches(3.6)
    for i, (label, value) in enumerate(rows):
        ry = y + i * (row_h + gap_y)
        _text(slide, MARGIN, ry, label_w, row_h,
              label.upper(), size=14, bold=True, color=GOLD,
              anchor=MSO_ANCHOR.MIDDLE)
        _text(slide, MARGIN + label_w, ry,
              CONTENT_W - label_w, row_h,
              value, size=22, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, MARGIN, y + total_h + Inches(0.35),
          CONTENT_W, Inches(0.35),
          "All free-tier friendly. A single phone is the only hardware.",
          size=16, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


def slide_thank_you():
    slide = _new_slide()
    _text(slide, MARGIN, Inches(2.30), CONTENT_W, Inches(1.6),
          "Thank You", size=80, bold=True, color=TEXT,
          align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    _rect(slide, (SLIDE_W - Inches(0.9)) // 2, Inches(4.05),
          Inches(0.9), Pt(4), fill=GOLD)
    _text(slide, MARGIN, Inches(4.30), CONTENT_W, Inches(0.6),
          "Questions?", size=28, color=GOLD,
          align=PP_ALIGN.CENTER)
    _text(slide, MARGIN, Inches(5.30), CONTENT_W, Inches(0.4),
          "contact.me.kafle@gmail.com",
          size=16, color=TEXT, align=PP_ALIGN.CENTER)
    _text(slide, MARGIN, Inches(5.75), CONTENT_W, Inches(0.4),
          "github.com/kafle1/pocket-drs",
          size=14, color=MUTED, align=PP_ALIGN.CENTER, italic=True)


# ---------------------------------------------------------------------------
# Build deck (18 slides)
# ---------------------------------------------------------------------------
slide_title()                                                              # 1
slide_problem()                                                            # 2
slide_what_it_does()                                                       # 3
slide_architecture()                                                       # 4
slide_pipeline_overview()                                                  # 5

slide_split_bullets(                                                       # 6
    "05  /  Step 1",
    "Calibration",
    FIG / "app_calibration.png",
    [
        "4 pitch corners + 8 stump points → solvePnP",
        "Auto-fits camera FOV (28–86°) and pitch length",
        "Rejects calibration if reprojection > 8 px",
    ],
)

slide_split_bullets(                                                       # 7
    "06  /  Step 2",
    "Ball Detection",
    FIG / "test3_pixel_track.png",
    [
        "MOG2 background subtraction + HSV colour mask",
        "YOLO cricket-ball detector as fallback",
        "Confidence + radius reported per frame",
    ],
)

slide_split_bullets(                                                       # 8
    "07  /  Step 3",
    "Trajectory Linking",
    FIG / "test3_path_overlay.png",
    [
        "RANSAC over a constant-acceleration motion model",
        "Survives detection dropouts mid-flight",
        "Outputs a smooth (u, v) path with timestamps",
    ],
)

slide_split_bullets(                                                       # 9
    "08  /  Step 4",
    "3D Reconstruction",
    FIG / "test3_3d_path.png",
    [
        "Depth from ball size:  d = fₓ · R / r",
        "Projectile-motion least-squares fit",
        "Bounce reflection via Ribnick (2009) linear solve",
        "Outputs (x, y, z) trajectory in metres",
    ],
)

slide_lbw_logic()                                                          # 10
slide_decisions_grid()                                                     # 11

slide_split_bullets(                                                       # 12
    "11  /  Real-world test",
    "Real Video — test3.mp4",
    FIG / "test3_overlay.png",
    [
        "Indoor net, zoomed phone (37° FOV)",
        "29 detections, 28 RANSAC inliers",
        "Measured speed: 64.1 km/h",
        "Decision: NOT OUT — missing stumps",
    ],
    caption="Reprojection 16.6 px  ·  Length auto-fit 12.7 m",
)

slide_split_bullets(                                                       # 13
    "12  /  Real-world test",
    "Real Video — test4.mp4",
    FIG / "test4_overlay.png",
    [
        "Indoor net, normal-FOV phone (45° pinned)",
        "37 detections, 36 RANSAC inliers",
        "Measured speed: 37.4 km/h",
        "Decision: UMPIRES CALL — 0.1 cm margin",
    ],
    caption="Reprojection 4.1 px  ·  Length auto-fit 9.45 m",
)

slide_3d_view()                                                            # 14

slide_split_bullets(                                                       # 15
    "14  /  Synthetic sweep",
    "Synthetic Validation",
    FIG / "synth_summary.png",
    [
        "8 scenarios sweep speed, line and length",
        "Pipeline tracks the ball across all 8",
        "Speed accuracy: best 0.8 km/h, worst 8.3 km/h",
        "Pass bar set to monocular-realistic bounds",
    ],
    caption="Monocular depth-from-radius cannot match six-camera Hawk-Eye — limit documented honestly",
)

slide_hardened()                                                           # 16
slide_stack()                                                              # 17
slide_thank_you()                                                          # 18

# ---------------------------------------------------------------------------
# Footers (skip title and thank-you)
# ---------------------------------------------------------------------------
total = len(prs.slides)
for i, sl in enumerate(prs.slides, start=1):
    if i in (1, total):
        continue
    _page_footer(sl, i, total)

prs.save(str(OUT))
print(f"Wrote {OUT}  ({len(prs.slides)} slides)")
