#!/usr/bin/env python
"""One table for every pipeline change: both rendered sets of exp2 and the bundled real clips.

Rendered: the exp2 grid from each camera end at 60 Hz with 2 px tap noise, scored against the truth.
Real: test3 to test5 with the taps in server/scripts/real_clip.py; --dump DIR keeps each result json
and the rendered rows, so a run that was killed picks up where it stopped.

    server/.venv/bin/python paper/experiments/scoreboard.py [--workers 8] [--dump DIR]
"""
from __future__ import annotations

import collections
import json
import os
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(HERE).resolve().parents[1]
sys.path[:0] = [HERE, str(ROOT / "server"), str(ROOT / "server" / "scripts")]
from synth import Camera, fly, grid, truth_verdict   # noqa: E402
from render import render                            # noqa: E402
from app.pipeline.process_job import run_pipeline    # noqa: E402
import real_clip                                     # noqa: E402

CAMERAS = {"striker": Camera(end="striker", back_m=2.8, height_m=1.7), "bowler": Camera(end="bowler", back_m=2.8, height_m=1.7)}
FPS, TAP_PX = 60.0, 2.0
CLIPS = Path(tempfile.gettempdir()) / "pdrs_scoreboard"
VERDICT = {"OUT": "out", "NOT_OUT": "not_out", "UMPIRES_CALL": "umpires_call"}


def _quiet():
    # one thread per worker, or the pool fights itself for cores
    import cv2
    import torch
    cv2.setNumThreads(1)
    torch.set_num_threads(1)


def request(cal: dict, n_frames: int) -> dict:
    return {"segment": {"start_ms": 0, "end_ms": int(1000 * (n_frames - 1) / FPS)},
            "tracking": {"ball_type": "leather", "ball_color": "red"},
            "calibration": cal, "batsman_handedness": "right"}


def rendered(job):
    end, i = job
    truth = fly(grid()[i])
    clip = CLIPS / f"{end}_{i:03d}.mp4"
    cal = render(truth, CAMERAS[end], clip, fps=FPS)
    n = cal.pop("n_frames")
    rng = np.random.default_rng([7, i])
    W, H = CAMERAS[end].width, CAMERAS[end].height
    for key in [k for k in cal if k.endswith("_norm")]:
        cal[key] = [{"x": p["x"] + rng.normal(0, TAP_PX) / W, "y": p["y"] + rng.normal(0, TAP_PX) / H} for p in cal[key]]
    try:
        out = run_pipeline(video_path=clip, request_json=request(cal, n), artifacts_dir=Path(tempfile.mkdtemp()), progress=None).result
    except Exception as e:                           # noqa: BLE001
        return end, i, truth_verdict(truth), "refused", str(e)[:80]
    nc = out["no_call"] or {}
    return end, i, truth_verdict(truth), VERDICT.get(out["lbw"]["verdict"], "no_verdict"), f"{nc.get('code', '')}: {nc.get('message', '')}"[:80]


def real(name: str, dump: Path | None) -> dict:
    try:
        out = run_pipeline(video_path=ROOT / f"{name}.mp4", request_json=real_clip.build_request(name),
                           artifacts_dir=Path(tempfile.mkdtemp()), progress=None).result
    except Exception as e:                           # noqa: BLE001
        return dict(clip=name, stage="calibration", outcome=str(e)[:90])
    if dump:
        (dump / f"{name}.json").write_text(json.dumps(out))
    pose, lbw, nc = (out["calibration"] or {}).get("pose") or {}, out["lbw"], out["no_call"]
    n = len((out.get("track") or {}).get("image_points") or [])
    return dict(clip=name, stage="decline" if nc else "verdict", track=n,
                outcome=f"{lbw['verdict']}: " + (f"{nc['code']}: {nc['message']}" if nc else lbw["reason"]),
                L=pose.get("pitch_length_m"), fov=pose.get("fov_deg") and round(pose["fov_deg"], 1),
                cam=[round(c, 2) for c in pose.get("cam_center_world_m") or []])


def main():
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8
    dump = Path(sys.argv[sys.argv.index("--dump") + 1]) if "--dump" in sys.argv else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    saved = dump / "rendered.jsonl" if dump else None
    done = {}
    for line in saved.read_text().splitlines() if saved and saved.exists() else []:
        row = json.loads(line)
        done[tuple(row[:2])] = row
    with Pool(workers, initializer=_quiet) as pool:
        for row in pool.imap_unordered(rendered, [(e, i) for e in CAMERAS for i in range(len(grid())) if (e, i) not in done]):
            done[row[:2]] = row
            if saved:
                with saved.open("a") as f:
                    f.write(json.dumps(row) + "\n")
    rows = [r[:1] + r[2:] for r in done.values()]
    print("end      right wrong no_verdict false_out out->ump  top no-verdict reason")
    for end in CAMERAS:
        r = [x for x in rows if x[0] == end]
        nv = [x for x in r if x[2] in ("no_verdict", "refused")]
        print(f"{end:8} {sum(t == v for _, t, v, _ in r):5} {sum(t != v and v not in ('no_verdict', 'refused') for _, t, v, _ in r):5} "
              f"{len(nv):10} {sum(v == 'out' and t != 'out' for _, t, v, _ in r):9} "
              f"{sum(t == 'out' and v == 'umpires_call' for _, t, v, _ in r):8}  "
              f"{collections.Counter(x[3] for x in nv).most_common(1)}")
    for name in real_clip.CLIPS:
        print(json.dumps(real(name, dump)))


if __name__ == "__main__":
    main()
