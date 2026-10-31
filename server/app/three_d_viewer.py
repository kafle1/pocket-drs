"""Render the Three.js 3D ball path viewer HTML for a finished analysis.

The HTML template lives at ``app/templates/three_d_viewer.html.tmpl``; the
``__PAYLOAD__`` placeholder is replaced with a JSON blob the page loads
inline. The /v1/jobs/{job_id}/three-d endpoint serves this so the app can
open the result in any browser; three.js itself comes from /static on the same server.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline.calibration import STUMP_OUTER_HALF_M
from .pipeline.process_job import _finite
from .pipeline.reconstruction import BALL_RADIUS_M

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "three_d_viewer.html.tmpl"

OUT, CALL, NONE = "out", "umpires_call", "none"


def _verdict(lbw: dict[str, Any] | None, bounce: dict[str, Any]) -> dict[str, Any] | None:
    """The three DRS rows and the final call, coloured as decision.py made them."""
    if not lbw or "tones" not in lbw:
        return None
    tone, reason = lbw["tones"], str(lbw.get("reason") or "")

    def value(row: str, against: str, saved: str) -> str:
        return "Umpire's call" if tone[row] == CALL else against if tone[row] == OUT else saved

    y_b = bounce.get("y_m")
    # pitching outside off never saves the batter, so it reads against him like in line
    off = y_b is not None and -float(y_b) * float(lbw.get("leg_sign") or 1.0) - STUMP_OUTER_HALF_M > BALL_RADIUS_M
    side = "off" if "impact outside off" in reason else "leg"
    rows = [("Pitching", "Full toss", NONE) if y_b is None else
            ("Pitching", value("pitching", "Outside off" if off else "In line", "Outside leg"), tone["pitching"]),
            ("Impact", value("impact", "In line", f"Outside {side}"), tone["impact"]),
            ("Wickets", value("wickets", "Hitting", "Missing"), tone["wickets"])]
    return {
        "decision": lbw["decision"],
        "reason": reason[:1].upper() + reason[1:],
        "rows": [{"label": a, "value": b, "tone": c} for a, b, c in rows],
    }


def build_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Project a pipeline result dict to the viewer's JSON shape."""
    world = result.get("world_trajectory") or {}
    events = result.get("events") or {}
    bounce = events.get("bounce") or {}
    impact = events.get("impact") or {}
    metrics = result.get("metrics") or {}
    pose = result["calibration"]["pose"]

    def pts(rows: list[dict[str, Any]]) -> list[list[float]]:
        return [[int(p["t_ms"]), p["x"], p["y"], max(0.0, p["z"])] for p in rows]

    def event(e: dict[str, Any]) -> list[float] | None:
        if e.get("x_m") is None or e.get("t_ms") is None:
            return None
        return [int(e["t_ms"]), e["x_m"], e["y_m"], max(0.0, e.get("z_m") or 0.0)]

    return {
        "pitch_length_m": float(pose["pitch_length_m"]),
        "pitch_width_m": float(pose["pitch_width_m"]),
        # rows of t_ms, x, y, z: x runs from the striker's stumps (0) to the bowler's, z is up
        "tracked": pts(world.get("points_m") or []),
        "predicted": pts(world.get("predicted_to_stumps_m") or []),
        "bounce": event(bounce),
        "impact": event(impact),
        "speed_kmh": metrics.get("speed_kmh"),
        "swing_cm": metrics.get("swing_cm"),
        "spin_deg": metrics.get("spin_deg"),
        "verdict": _verdict(result.get("lbw"), bounce),
    }


def render_html(result: dict[str, Any]) -> str:
    """Return the full HTML page with the payload inlined."""
    template = _TEMPLATE_PATH.read_text()
    payload = _finite(build_payload(result))
    # "</" inside the inlined json would end the script tag early
    return template.replace("__PAYLOAD__", json.dumps(payload, allow_nan=False).replace("</", "<\\/"))
