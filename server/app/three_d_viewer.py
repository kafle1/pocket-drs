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

from .pipeline.process_job import _finite

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "three_d_viewer.html.tmpl"


def build_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Project a pipeline result dict to the viewer's JSON shape."""
    world_pts = result.get("world_trajectory") or {}
    pts = world_pts.get("points_m") or []
    pred = world_pts.get("predicted_to_stumps_m") or []
    events = result.get("events") or {}
    bounce = events.get("bounce") or {}
    impact = events.get("impact") or {}
    metrics = result.get("metrics") or {}
    lbw = result.get("lbw") or {}
    pred_at = lbw.get("prediction") or {}
    pitch_length_m = float(result["calibration"]["pose"]["pitch_length_m"])
    pitch_width_m = float(result["calibration"]["pose"]["pitch_width_m"])

    def cm(meters: Any) -> Any:
        return None if meters is None else round(float(meters) * 100)

    return {
        "pitch_length_m": float(pitch_length_m),
        "pitch_width_m": float(pitch_width_m),
        "tracked": [{"x": p["x"], "y": p["y"], "z": p["z"]} for p in pts],
        "predicted": [{"x": p["x"], "y": p["y"], "z": p["z"]} for p in pred],
        "bounce": {
            "x_m": bounce.get("x_m"),
            "y_m": bounce.get("y_m"),
            "z_m": bounce.get("z_m") or 0.0,
        },
        "impact": {
            "x_m": impact.get("x_m"),
            "y_m": impact.get("y_m"),
            "z_m": impact.get("z_m") or 0.0,
        },
        "speed_kmh": metrics.get("speed_kmh"),
        "swing_cm": metrics.get("swing_cm"),
        "spin_deg": metrics.get("spin_deg"),
        "lbw_decision": lbw.get("decision"),
        "checks": {
            "pitching_in_line": bool((lbw.get("checks") or {}).get("pitching_in_line", True)),
            "impact_in_line": bool((lbw.get("checks") or {}).get("impact_in_line", True)),
            "wickets_hitting": bool((lbw.get("checks") or {}).get("wickets_hitting", False)),
        },
        "y_at_stumps_cm": cm(pred_at.get("y_at_stumps_m")),
        "z_at_stumps_cm": cm(pred_at.get("z_at_stumps_m")),
    }


def render_html(result: dict[str, Any]) -> str:
    """Return the full HTML page with the payload inlined."""
    template = _TEMPLATE_PATH.read_text()
    payload = _finite(build_payload(result))
    return template.replace("__PAYLOAD__", json.dumps(payload, allow_nan=False))
