"""Render the Three.js 3D Hawk-Eye viewer HTML for a finished analysis.

The HTML template lives at ``app/templates/three_d_viewer.html.tmpl``; the
``__PAYLOAD__`` placeholder is replaced with a JSON blob the page loads
inline. The /v1/jobs/{job_id}/three-d endpoint serves this so the app can
open the result in any browser as a standalone, self-contained scene.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    pred_at = (lbw.get("prediction") or {})
    pitch = result.get("pitch") or {}

    pitch_length_m = float(pitch.get("length_m") or 0.0)
    if pitch_length_m <= 0.0:
        pitch_length_m = max(
            [p["x"] for p in pts]
            + ([pred[-1]["x"]] if pred else [])
            + [6.3]
        )
    pitch_width_m = float(pitch.get("width_m") or 3.05)

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
        "speed_kmh": float(metrics.get("speed_kmh") or 0.0),
        "lbw_decision": lbw.get("decision"),
        "y_at_stumps_cm": cm(pred_at.get("y_at_stumps_m")),
        "z_at_stumps_cm": cm(pred_at.get("z_at_stumps_m")),
    }


def render_html(result: dict[str, Any]) -> str:
    """Return the full HTML page with the payload inlined."""
    template = _TEMPLATE_PATH.read_text()
    payload = build_payload(result)
    return template.replace("__PAYLOAD__", json.dumps(payload, allow_nan=False))
