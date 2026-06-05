"""Generate all PocketDRS report diagrams from their textual sources.

Produces real, project-specific diagrams for a pure structured-analysis
report: architecture, use-case (UML), ER (crow's-foot), DFD level 0/1, and
a physical DFD. Reproducible: re-run after any design change.

Notation choices (all textbook-standard):
  * Use-case  -> PlantUML standard UML (stick-figure actors + system box).
  * ER        -> PlantUML crow's-foot / Information Engineering notation.
  * DFD L0/L1 -> Graphviz, Gane-Sarson convention (rounded-rectangle numbered
                 processes, external entities as plain rectangles, data stores
                 drawn as the standard open-ended rectangle glyph).
  * Physical  -> Gane-Sarson DFD mapped onto physical implementation nodes.

Requires graphviz (`dot`) and plantuml on PATH.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

FIGURES = Path(__file__).parent / "figures"
FIGURES.mkdir(exist_ok=True)

# Shared styling for a clean, consistent academic look.
_HEAD = """digraph {{
  rankdir={rankdir};
  bgcolor="white";
  fontname="Helvetica";
  node [fontname="Helvetica", fontsize=11];
  edge [fontname="Helvetica", fontsize=10];
"""


def render(name: str, dot: str) -> None:
    src = FIGURES / f"{name}.dot"
    out = FIGURES / f"{name}.png"
    src.write_text(dot)
    subprocess.run(["dot", "-Tpng", "-Gdpi=150", str(src), "-o", str(out)], check=True)
    src.unlink()
    print(f"  {out.name}")


def render_puml(name: str, puml: str) -> None:
    """Render a PlantUML source to figures/<name>.png."""
    src = Path(tempfile.gettempdir()) / f"pocketdrs_{name}.puml"
    src.write_text(puml)
    subprocess.run(["plantuml", "-tpng", "-o", str(FIGURES), str(src)], check=True)
    rendered = FIGURES / f"pocketdrs_{name}.png"
    if rendered.exists():
        rendered.replace(FIGURES / f"{name}.png")
    src.unlink()
    print(f"  {name}.png")


# Standard Gane-Sarson data-store glyph: an HTML-like table with borders only
# on the top and bottom edges, split into a narrow "Dn" cell and the store
# name. This reproduces the open-ended rectangle used in textbook DFDs.
def _datastore(ident: str, name: str) -> str:
    return (
        '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="6">'
        '<TR>'
        f'<TD SIDES="TB" BORDER="1" BGCOLOR="#eefbf0"><B>{ident}</B></TD>'
        f'<TD SIDES="TBL" BORDER="1" BGCOLOR="#eefbf0">{name}</TD>'
        '</TR></TABLE>>'
    )


# ---------------------------------------------------------------------------
# 1. Three-tier system architecture
# ---------------------------------------------------------------------------
ARCHITECTURE = _HEAD.format(rankdir="TB") + """
  node [shape=box, style="rounded,filled", fillcolor="#eef4ff"];

  subgraph cluster_mobile {
    label="Presentation Tier  -  Flutter Mobile App";
    style=filled; fillcolor="#f4f8ff"; fontname="Helvetica-Bold";
    cap [label="Video Capture\\n& Trim"];
    calib [label="Pitch Calibration\\n(tap 4 corners)"];
    apicli [label="API Client\\n(REST + auth)"];
    viewer [label="3D Hawk-Eye Viewer\\n(WebView + Three.js)"];
  }

  subgraph cluster_backend {
    label="Application Tier  -  FastAPI Backend";
    style=filled; fillcolor="#fff6ee"; fontname="Helvetica-Bold";
    api [label="REST Endpoints\\n/v1/jobs"];
    jobs [label="Job Manager\\n(async worker)"];
    subgraph cluster_pipe {
      label="CV Pipeline";
      style=filled; fillcolor="#ffeedd"; fontname="Helvetica";
      p1 [label="Calibration\\n(solvePnP)"];
      p2 [label="Ball Detection\\n(motion + colour + YOLO)"];
      p3 [label="Trajectory\\n(RANSAC)"];
      p4 [label="3D Reconstruction\\n(projectile fit)"];
      p5 [label="LBW Decision\\n(ICC Rule 36)"];
      p1 -> p2 -> p3 -> p4 -> p5;
    }
  }

  subgraph cluster_cloud {
    label="Data Tier  -  Firebase";
    style=filled; fillcolor="#eefbf0"; fontname="Helvetica-Bold";
    auth [label="Firebase Auth"];
    fs [label="Cloud Firestore\\n(pitches, analyses)"];
  }

  cap -> apicli; calib -> apicli;
  apicli -> api [label="HTTPS  video + calibration"];
  api -> jobs -> p1;
  p5 -> api [label="result JSON"];
  api -> apicli [label="job status + result"];
  apicli -> viewer [label="3D payload"];
  apicli -> auth [label="ID token", style=dashed];
  jobs -> fs [label="status + result", style=dashed];
}
"""

# ---------------------------------------------------------------------------
# 2. Use-case diagram (standard UML, rendered with PlantUML)
#
# Stick-figure actors, all use cases inside a named system-boundary box,
# solid association lines. Cricketer is the primary actor (left); Firebase is
# a secondary/supporting actor (right).
# ---------------------------------------------------------------------------
USECASE_PUML = """@startuml
skinparam dpi 150
skinparam shadowing false
left to right direction
skinparam packageStyle rectangle
skinparam actorStyle awesome
skinparam usecaseBackgroundColor #eef4ff
skinparam usecaseBorderColor #4a6fa5
skinparam actorBorderColor #4a6fa5
skinparam rectangleBorderColor #4a6fa5
skinparam ArrowColor #333333

actor "Cricketer" as User
actor "Firebase" as FB

rectangle "PocketDRS System" {
  usecase "Sign In / Register" as UC_SIGN
  usecase "Create Pitch" as UC_NEWPITCH
  usecase "Calibrate Pitch" as UC_CALIB
  usecase "Record / Upload Delivery" as UC_RECORD
  usecase "Trim Clip" as UC_TRIM
  usecase "Analyse Delivery" as UC_ANALYSE
  usecase "View 3D Ball Track" as UC_VIEW3D
  usecase "View LBW Decision" as UC_DECISION
  usecase "View Analysis History" as UC_HISTORY
}

User -- UC_SIGN
User -- UC_NEWPITCH
User -- UC_CALIB
User -- UC_RECORD
User -- UC_TRIM
User -- UC_ANALYSE
User -- UC_VIEW3D
User -- UC_DECISION
User -- UC_HISTORY

UC_SIGN -- FB
UC_ANALYSE -- FB
UC_HISTORY -- FB
@enduml
"""

# ---------------------------------------------------------------------------
# 3. Entity-Relationship diagram (crow's-foot / Information Engineering)
#
# Entities are rectangles with attribute lists, primary keys marked. Crow's
# foot cardinality on every relationship, each relationship labelled.
# ---------------------------------------------------------------------------
ER_PUML = """@startuml
skinparam dpi 150
skinparam shadowing false
skinparam linetype ortho
hide circle
skinparam class {
  BackgroundColor #eef4ff
  BorderColor #4a6fa5
  ArrowColor #333333
}

entity "User" as User {
  * uid : PK
  --
  email
}

entity "Pitch" as Pitch {
  * pitchId : PK
  --
  name
  corners
  dimensions
}

entity "Analysis" as Analysis {
  * analysisId : PK
  --
  jobId
  createdAt
}

entity "DeliveryVideo" as Video {
  * videoId : PK
  --
  segment
  fps
}

entity "LBWResult" as Result {
  * resultId : PK
  --
  decision
  reason
  confidence
}

entity "CalibrationProfile" as Calib {
  * calibId : PK
  --
  corners
  stumps
  homography
  quality
}

User    ||--o{ Pitch    : owns
User    ||--o{ Analysis : submits
Analysis }o--|| Pitch   : uses
Analysis ||--|| Video   : has
Analysis ||--|| Result  : produces
Pitch    ||--|| Calib   : defines
@enduml
"""

# ---------------------------------------------------------------------------
# 4. DFD Level 0 (context diagram) -- Gane-Sarson convention
#
# External entities = plain rectangles. The single context process is a
# numbered rounded rectangle (process 0). No data stores at context level.
# ---------------------------------------------------------------------------
DFD0 = _HEAD.format(rankdir="LR") + """
  node [fontsize=11];
  user  [shape=box, style=filled, fillcolor="#eef4ff", label="User"];
  fbase [shape=box, style=filled, fillcolor="#eef4ff", label="Firebase"];
  sys   [shape=Mrecord, style=filled, fillcolor="#fff6ee",
         label="{ 0 | PocketDRS System }"];

  user -> sys [label="delivery video,\\ncalibration taps"];
  sys -> user [label="LBW decision,\\n3D visualisation"];
  sys -> fbase [label="auth token,\\nanalysis docs"];
  fbase -> sys [label="user identity,\\nstored results"];
}
"""

# ---------------------------------------------------------------------------
# 5. DFD Level 1 -- Gane-Sarson convention
#
# Numbered rounded-rectangle processes (1..4), external entity as a plain
# rectangle, data stores drawn with the standard open-ended rectangle glyph.
# ---------------------------------------------------------------------------
DFD1 = _HEAD.format(rankdir="TB") + """
  node [fontsize=11];
  user  [shape=box, style=filled, fillcolor="#eef4ff", label="User"];
  node [shape=Mrecord, style=filled, fillcolor="#fff6ee"];
  p1 [label="{ 1.0 | Capture & Trim }"];
  p2 [label="{ 2.0 | Calibrate Pitch }"];
  p3 [label="{ 3.0 | Analyse Delivery }"];
  p4 [label="{ 4.0 | Present Result }"];
  d1 [shape=plaintext, label=""" + _datastore("D1", "Calibration Store") + """];
  d2 [shape=plaintext, label=""" + _datastore("D2", "Job / Result Store") + """];

  user -> p1 [label="raw video  ", labeldistance=2];
  user -> p2 [label="  corner taps"];
  p1 -> p3 [label="trimmed clip"];
  p2 -> d1 [label="calibration"];
  d1 -> p3 [label="pitch geometry"];
  p3 -> d2 [label="job status,\\n3D result"];
  d2 -> p4 [label="trajectory,\\ndecision"];
  p4 -> user [label="3D view + verdict"];
}
"""

# ---------------------------------------------------------------------------
# 6. Physical DFD -- Gane-Sarson convention mapped onto implementation nodes
#
# Same notation as the logical DFDs (numbered rounded-rectangle processes,
# plain-rectangle external entity, open-ended data-store glyphs) but the
# processes are the real physical components and stores are the real services.
# ---------------------------------------------------------------------------
PHYSICAL_DFD = _HEAD.format(rankdir="TB") + """
  node [fontsize=11];
  user [shape=box, style=filled, fillcolor="#eef4ff", label="User\\n(smartphone)"];
  node [shape=Mrecord, style=filled, fillcolor="#fff6ee"];
  p1 [label="{ 1.0 | Flutter Mobile App\\n(Android / iOS) }"];
  p2 [label="{ 2.0 | FastAPI Service\\n(Google Cloud Run) }"];
  p3 [label="{ 3.0 | CV Pipeline\\n(OpenCV / SciPy, Cloud Run) }"];
  p4 [label="{ 4.0 | Three.js WebView Viewer\\n(on device) }"];
  d1 [shape=plaintext, label=""" + _datastore("D1", "Cloud Firestore") + """];
  d2 [shape=plaintext, label=""" + _datastore("D2", "Cloud Storage (video files)") + """];

  user -> p1 [label="video + taps"];
  p1 -> p2 [label="HTTPS upload"];
  p2 -> p3 [label="run"];
  d2 -> p3 [label="read video"];
  p3 -> p2 [label="result"];
  p2 -> d1 [label="status + result"];
  d1 -> p1 [label="read history"];
  p1 -> p4 [label="3D payload"];
  p4 -> user [label="3D view + verdict"];
}
"""

# Graphviz-rendered diagrams.
DIAGRAMS = {
    "architecture": ARCHITECTURE,
    "dfd_level0": DFD0,
    "dfd_level1": DFD1,
    "physical_dfd": PHYSICAL_DFD,
}

# PlantUML-rendered diagrams.
PUML_DIAGRAMS = {
    "use_case_diagram": USECASE_PUML,
    "er_diagram": ER_PUML,
}


def main() -> int:
    print("Rendering PocketDRS report diagrams:")
    for name, dot in DIAGRAMS.items():
        render(name, dot)
    for name, puml in PUML_DIAGRAMS.items():
        render_puml(name, puml)
    print(f"Done -> {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
