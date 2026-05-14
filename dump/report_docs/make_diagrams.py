"""Generate all PocketDRS report diagrams from Graphviz sources.

Produces real, project-specific diagrams (architecture, use-case, ER, DFD
L0/L1, class, state, sequence, deployment) into figures/. Reproducible:
re-run after any design change. Requires graphviz (`dot` on PATH).
"""

from __future__ import annotations

import subprocess
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
      p2 [label="Ball Detection\\n(motion + colour + streak)"];
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
# 2. Use-case diagram
# ---------------------------------------------------------------------------
USECASE = _HEAD.format(rankdir="LR") + """
  node [shape=ellipse, style=filled, fillcolor="#eef4ff"];
  user  [shape=none, fillcolor=none, label="Cricketer\\n(User)"];
  fbase [shape=none, fillcolor=none, label="Firebase\\n(Auth + Storage)"];

  signin   [label="Sign In /\\nRegister"];
  newpitch [label="Create Pitch"];
  calib    [label="Calibrate Pitch\\n(tap corners)"];
  record   [label="Record / Upload\\nDelivery"];
  trim     [label="Trim Clip"];
  analyse  [label="Analyse Delivery"];
  view3d   [label="View 3D\\nBall Track"];
  decision [label="View LBW\\nDecision"];
  history  [label="View Analysis\\nHistory"];

  user -> signin; user -> newpitch; user -> calib; user -> record;
  user -> trim; user -> analyse; user -> view3d; user -> decision;
  user -> history;
  signin -> fbase [style=dashed]; analyse -> fbase [style=dashed];
  history -> fbase [style=dashed];
  { rank=same; signin; newpitch; calib; record; trim; analyse; view3d; decision; history; }
}
"""

# ---------------------------------------------------------------------------
# 3. Entity-Relationship diagram
# ---------------------------------------------------------------------------
ER = _HEAD.format(rankdir="TB") + """
  node [shape=box, style=filled, fillcolor="#eef4ff"];
  edge [arrowhead=none];

  User    [label="User\\n(uid, email)"];
  Pitch   [label="Pitch\\n(pitchId, name,\\ncorners, dimensions)"];
  Analysis[label="Analysis\\n(analysisId, jobId,\\ncreatedAt)"];
  Video   [label="DeliveryVideo\\n(segment, fps)"];
  Calib   [label="CalibrationProfile\\n(corners, stumps,\\nhomography, quality)"];
  Result  [label="LBWResult\\n(decision, reason,\\nconfidence)"];

  r1 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="owns"];
  r2 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="submits"];
  r3 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="uses"];
  r4 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="has"];
  r5 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="produces"];
  r6 [shape=diamond, style=filled, fillcolor="#ffe9cc", label="defines"];

  User -> r1 [label="1"]; r1 -> Pitch [label="N"];
  User -> r2 [label="1"]; r2 -> Analysis [label="N"];
  Analysis -> r3 [label="N"]; r3 -> Pitch [label="1"];
  Analysis -> r4 [label="1"]; r4 -> Video [label="1"];
  Analysis -> r5 [label="1"]; r5 -> Result [label="1"];
  Pitch -> r6 [label="1"]; r6 -> Calib [label="1"];
}
"""

# ---------------------------------------------------------------------------
# 4. DFD Level 0 (context diagram)
# ---------------------------------------------------------------------------
DFD0 = _HEAD.format(rankdir="LR") + """
  node [fontsize=11];
  user  [shape=box, style=filled, fillcolor="#eef4ff", label="User"];
  fbase [shape=box, style=filled, fillcolor="#eefbf0", label="Firebase"];
  sys   [shape=circle, style=filled, fillcolor="#fff6ee", width=1.6,
         label="PocketDRS\\nSystem"];

  user -> sys [label="delivery video,\\ncalibration taps"];
  sys -> user [label="LBW decision,\\n3D visualisation"];
  sys -> fbase [label="auth token,\\nanalysis docs"];
  fbase -> sys [label="user identity,\\nstored results"];
}
"""

# ---------------------------------------------------------------------------
# 5. DFD Level 1
# ---------------------------------------------------------------------------
DFD1 = _HEAD.format(rankdir="TB") + """
  node [fontsize=11];
  user  [shape=box, style=filled, fillcolor="#eef4ff", label="User"];
  p1 [shape=circle, style=filled, fillcolor="#fff6ee", label="1\\nCapture\\n& Trim"];
  p2 [shape=circle, style=filled, fillcolor="#fff6ee", label="2\\nCalibrate\\nPitch"];
  p3 [shape=circle, style=filled, fillcolor="#fff6ee", label="3\\nAnalyse\\nDelivery"];
  p4 [shape=circle, style=filled, fillcolor="#fff6ee", label="4\\nPresent\\nResult"];
  d1 [shape=box, style=filled, fillcolor="#eefbf0", label="D1  Calibration Store"];
  d2 [shape=box, style=filled, fillcolor="#eefbf0", label="D2  Job / Result Store"];

  user -> p1 [label="raw video"];
  user -> p2 [label="corner taps"];
  p1 -> p3 [label="trimmed clip"];
  p2 -> d1 [label="calibration"];
  d1 -> p3 [label="pitch geometry"];
  p3 -> d2 [label="job status,\\n3D result"];
  d2 -> p4 [label="trajectory,\\ndecision"];
  p4 -> user [label="3D view + verdict"];
}
"""

# ---------------------------------------------------------------------------
# 6. Class diagram
# ---------------------------------------------------------------------------
CLASS = _HEAD.format(rankdir="TB") + """
  node [shape=record, style=filled, fillcolor="#eef4ff", fontsize=10];

  PitchCalibration [label="{PitchCalibration|+ imagePoints: List\\<Offset\\>\\l+ stumpPoints: List\\<Offset\\>\\l+ imageSizePx: Size\\l|+ validateImageQuad()\\l+ toJson()\\l}"];
  PitchPose [label="{PitchPose|+ K: Matrix3\\l+ R: Matrix3\\l+ t: Vector3\\l+ reprojErrorPx: double\\l|+ fromCalibration()\\l}"];
  BallTrack [label="{BallTrack|+ points: List\\<TrackPoint\\>\\l+ inliers: int\\l+ rmsPx: double\\l}"];
  WorldTrajectory [label="{WorldTrajectory|+ points: List\\<WorldPoint\\>\\l+ predictedToStumps: List\\l+ fit: ProjectileFit\\l|+ hasTrajectory()\\l}"];
  LbwResult [label="{LbwResult|+ decision: Decision\\l+ reason: String\\l+ checks: Map\\l+ confidence: double\\l|+ fromJson()\\l}"];
  AnalysisJob [label="{AnalysisJob|+ jobId: String\\l+ status: JobStatus\\l+ calibration: PitchCalibration\\l+ result: AnalysisResult\\l}"];
  PocketDrsApi [label="{PocketDrsApi|+ baseUrl: String\\l|+ createJob()\\l+ getJobStatus()\\l+ getJobResult()\\l}"];

  AnalysisJob -> PitchCalibration [arrowhead=diamond, label=" uses"];
  AnalysisJob -> WorldTrajectory [arrowhead=diamond, label=" produces"];
  AnalysisJob -> LbwResult [arrowhead=diamond, label=" produces"];
  WorldTrajectory -> BallTrack [arrowhead=vee, style=dashed, label=" from"];
  PitchPose -> PitchCalibration [arrowhead=vee, style=dashed, label=" derived from"];
  PocketDrsApi -> AnalysisJob [arrowhead=vee, style=dashed, label=" manages"];
}
"""

# ---------------------------------------------------------------------------
# 7. State diagram (analysis job lifecycle)
# ---------------------------------------------------------------------------
STATE = _HEAD.format(rankdir="LR") + """
  node [shape=circle, style=filled, fillcolor="#eef4ff", fontsize=11];
  start [shape=point, width=0.15, fillcolor=black];
  Queued; Running;
  Succeeded [shape=doublecircle, fillcolor="#eefbf0"];
  Failed    [shape=doublecircle, fillcolor="#ffe3e3"];

  start -> Queued [label="job created"];
  Queued -> Running [label="worker picks up"];
  Running -> Running [label="progress update"];
  Running -> Succeeded [label="result written"];
  Running -> Failed [label="decode / calibration\\n/ pipeline error"];
  Queued -> Failed [label="invalid request"];
}
"""

# ---------------------------------------------------------------------------
# 8. Sequence diagram (end-to-end delivery analysis)
#
# Sequence diagrams need true lifelines + ordered messages, which Graphviz
# cannot lay out cleanly, so this one is rendered with PlantUML instead.
# ---------------------------------------------------------------------------
SEQUENCE_PUML = """@startuml
skinparam dpi 150
skinparam shadowing false
skinparam sequenceMessageAlign center
skinparam ParticipantBackgroundColor #eef4ff
skinparam ParticipantBorderColor #4a6fa5
skinparam ArrowColor #333333
hide footbox

actor User
participant "Mobile App\\n(Flutter)" as M
participant "FastAPI\\nServer" as S
participant "CV Pipeline" as P
database "Firestore" as F

User -> M : record, trim,\\ntap 4 pitch corners
M -> S : POST /v1/jobs\\n(video + calibration)
activate S
S -> S : validate request,\\nstore video
S --> M : job_id (status: queued)
S -> P : run_pipeline()
activate P
P -> P : decode -> calibrate ->\\ndetect -> track ->\\nreconstruct -> LBW
P --> S : result (3D trajectory,\\nLBW decision)
deactivate P
S -> F : write status + result
deactivate S

loop until status = succeeded
  M -> S : GET /v1/jobs/{job_id}
  S --> M : status, progress %
end

M -> S : GET /v1/jobs/{job_id}/result
S --> M : analysis result JSON
M -> User : render 3D ball track\\n+ LBW verdict
@enduml
"""

# ---------------------------------------------------------------------------
# 9. Component & deployment diagram
# ---------------------------------------------------------------------------
DEPLOY = _HEAD.format(rankdir="LR") + """
  node [shape=box, style="rounded,filled"];

  subgraph cluster_phone {
    label="Device : Smartphone"; style=filled; fillcolor="#f4f8ff";
    fontname="Helvetica-Bold";
    flutter [fillcolor="#eef4ff", label="Flutter App\\n(.apk / .ipa)"];
    webview [fillcolor="#eef4ff", label="WebView\\nThree.js viewer"];
    flutter -> webview [label="local assets"];
  }
  subgraph cluster_cloud {
    label="Cloud : Google Cloud Run"; style=filled; fillcolor="#fff6ee";
    fontname="Helvetica-Bold";
    fastapi [fillcolor="#ffeedd", label="FastAPI Service\\n(uvicorn)"];
    pipeline [fillcolor="#ffeedd", label="CV Pipeline\\n(OpenCV, SciPy, NumPy)"];
    fastapi -> pipeline;
  }
  subgraph cluster_fb {
    label="Cloud : Firebase"; style=filled; fillcolor="#eefbf0";
    fontname="Helvetica-Bold";
    fbauth [fillcolor="#dff5e3", label="Authentication"];
    fbstore[fillcolor="#dff5e3", label="Cloud Firestore"];
  }

  flutter -> fastapi [label="HTTPS REST"];
  flutter -> fbauth  [label="sign-in", style=dashed];
  fastapi -> fbauth  [label="verify token", style=dashed];
  fastapi -> fbstore [label="status + result", style=dashed];
  flutter -> fbstore [label="read history", style=dashed];
}
"""

DIAGRAMS = {
    "architecture": ARCHITECTURE,
    "use_case_diagram": USECASE,
    "er_diagram": ER,
    "dfd_level0": DFD0,
    "dfd_level1": DFD1,
    "class_diagram": CLASS,
    "state_diagram": STATE,
    "deployment_diagram": DEPLOY,
}


def render_sequence() -> None:
    """Render the sequence diagram with PlantUML (Graphviz cannot lay out
    proper lifelines and ordered messages)."""
    import tempfile
    src = Path(tempfile.gettempdir()) / "pocketdrs_sequence.puml"
    src.write_text(SEQUENCE_PUML)
    subprocess.run(["plantuml", "-tpng", "-o", str(FIGURES), str(src)], check=True)
    rendered = FIGURES / "pocketdrs_sequence.png"
    if rendered.exists():
        rendered.replace(FIGURES / "sequence_diagram.png")
    src.unlink()
    print("  sequence_diagram.png")


def main() -> int:
    print("Rendering PocketDRS report diagrams:")
    for name, dot in DIAGRAMS.items():
        render(name, dot)
    render_sequence()
    print(f"Done -> {FIGURES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
