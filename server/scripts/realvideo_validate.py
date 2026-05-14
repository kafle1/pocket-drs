"""Best-effort run of the pipeline on the bundled test.mp4 real cricket video.

Throwaway. Marks pitch corners by visual estimate. The phone-mounted user
flow lets users tap the corners interactively; this script provides a
sanity-check end-to-end run against a real clip.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.pipeline.process_job import run_pipeline


VIDEO = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/test.mp4")
OUT_DIR = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/validation")


def main() -> int:
    art = Path(tempfile.mkdtemp(prefix="realval_"))

    # Corner picks read off frame 0 of the practice-nets clip. The camera is
    # at the bowler-end stumps; the striker (with bat) is at the far end of
    # the pitch (small v); the practice pitch is the green strip framed by
    # dirt/sand edges. Pipeline order: striker-left, striker-right,
    # bowler-right, bowler-left.
    # Corners picked precisely off a coordinate-grid overlay of frame 0. The
    # green playing strip runs from the batter's (striker) end at the far
    # side down to the bowler-end stumps near the camera.
    corners_px = [
        {"x": 185.0, "y": 1075.0},   # striker-left  (far end, left edge of green)
        {"x": 405.0, "y": 1075.0},   # striker-right (far end, right edge of green)
        {"x": 445.0, "y": 1700.0},   # bowler-right  (near end, right edge of green)
        {"x":  78.0, "y": 1700.0},   # bowler-left   (near end, left edge of green)
    ]

    req = {
        "segment": {"start_ms": 0, "end_ms": 6900},
        "calibration": {
            "mode": "taps",
            "pitch_corners_px": corners_px,
            "pitch_dimensions_m": {"length": 20.12, "width": 3.05},
        },
        "tracking": {"sample_fps": 30, "max_frames": 210, "ball_color": "red"},
    }

    print(f"input  : {VIDEO}")
    print(f"corners: {[(c['x'], c['y']) for c in corners_px]}")

    out = run_pipeline(video_path=VIDEO, request_json=req, artifacts_dir=art, progress=None)
    r = out.result

    cal = r["calibration"]
    print()
    print(f"-- calibration --")
    print(f"reproj px  : {cal['quality']['reproj_error_px']:.2f}")
    print(f"cam center : {[round(c, 3) for c in cal['pose']['cam_center_world_m']]}")
    print(f"notes      : {cal['quality']['notes']}")

    print()
    print(f"-- tracking --")
    print(f"candidates : {r['track']['candidates_total']}")
    print(f"inliers    : {r['track']['inliers']}")
    print(f"rms_px     : {r['track']['rms_px']:.2f}")

    wt = r.get("world_trajectory")
    if wt is None:
        print("\nNo 3D trajectory reconstructed.")
    else:
        print()
        print(f"-- 3D --")
        print(f"world pts: {len(wt['points_m'])}")
        ev = r.get("events")
        if ev:
            b = ev.get("bounce") or {}
            i = ev.get("impact") or {}
            print(f"bounce   : t={b.get('t_ms')}ms x={b.get('x_m')} y={b.get('y_m')}")
            print(f"impact   : t={i.get('t_ms')}ms x={i.get('x_m')} y={i.get('y_m')} z={i.get('z_m')}")
        lbw = r.get("lbw")
        if lbw:
            print(f"lbw      : {lbw['decision']} — {lbw.get('reason')}")

    print()
    print(f"warnings : {r['diagnostics']['warnings']}")

    (OUT_DIR / "realvideo_result.json").write_text(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
