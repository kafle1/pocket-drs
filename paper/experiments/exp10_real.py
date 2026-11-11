#!/usr/bin/env python
"""Experiment 10: checks on the real clips that take their truth from the world, not from a tape.

There is no measured ball path, so each check uses something the world fixes:
  landmarks  calibrate from the eight stump marks alone, then put the four tapped pitch corners on
             the ground with that pose and compare with where the pitch dimensions place them (mm)
  gravity    refit the tracked flight before a seen bounce with g free (no drag, as the app), the
             ball held at z = R at that bounce for scale, and set the fitted vertical acceleration
             and its 95 % interval against 9.81 m/s^2; not possible without a seen bounce. The same
             fit runs on SIM_N simulated bowler's-end World B deliveries to show what it returns
             when g is known
  ball size  camera depth of the ball from its apparent radius, d = f R / r, against the depth of
             the fitted path in the same frame. The anchored fit uses the ball's centre only, so
             the two are independent; a single-parabola fallback uses the size and is flagged.
             u(d)/d combines the radius scatter about a quadratic in time of 1/r, the ball's
             diameter (71 to 73 mm, uniform) and the calibrated focal length's median error in
             exp1's ablation. Frames with r <= 1 px are left out, as the fallback fit does.
  outcome    where a clip shows the ball reach the stumps, the stump-plane crossing and its
             interval against what is seen; in every bundled clip the batter plays the ball first
Nothing here is tuned on the comparison. CLIPS lists every real cricket clip found, processed
or not, by file name and sha256; only the bundled own-phone clips are processed, and the reason
is given for each one that is not. Third-party clips are named, never copied.

    python exp10_real.py      # needs server/models/cricket_ball.pt and the bundled clips; minutes
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import t as student_t

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = Path(HERE).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server" / "scripts"))
from app.pipeline.calibration import PITCH_LENGTH_M, PITCH_WIDTH_M, solve_camera_pose   # noqa: E402
from app.pipeline.process_job import detections, run_pipeline                                           # noqa: E402
from app.pipeline.reconstruction import BALL_RADIUS_M, GRAVITY                           # noqa: E402
from real_clip import CLIPS as TAPS, build_request                                       # noqa: E402

OUT = os.path.join(HERE, "raw")
U_BALL = (0.073 - 0.071) / 2 / math.sqrt(3) / 0.072      # relative 1-sigma of the ball's radius
SIM_N = 200
OUTCOME = "not seen: the batter plays the ball before the stumps in every bundled clip"
# the three own clips are cut from one video from one fixed phone (their backgrounds match within 1 px);
# the near stumps were moved after test3, and test4 and test5 show them in the same pixels
FIXED = "one fixed phone behind the bowler's stumps, the same for all three clips, 1080x1920 at 60 Hz"
CLIPS = [
    dict(file="test3.mp4", sha256="2e8b0bd5867937f065458e69c80d8a1d30d5c2e0f1438dbaadd7f47259a7c8c8", source="own phone",
         view=FIXED, both_stumps=True),
    dict(file="test4.mp4", sha256="3be6d3a3e67e284bcd22f8de45ff3f6749e7dda260b87ae4ac505298ab7b1baa", source="own phone",
         view=FIXED, both_stumps=True),
    dict(file="test5.mp4", sha256="09b27fb88220cfb3aaaa0c04be5e51e20f495224bd618293e7c3739b5b079052", source="own phone",
         view=FIXED, both_stumps=True, same_stumps_as="test4.mp4"),
    dict(file="test3-off-spin-clip.mp4", sha256="2e8b0bd5867937f065458e69c80d8a1d30d5c2e0f1438dbaadd7f47259a7c8c8",
         source="own phone", skip="the same file as test3.mp4 (same sha256)"),
    dict(file="clip1.mp4", sha256="8176a0e3a3eb31bf6ebcaabed3ea0dd0872661ef93dadf1701db3654a14c902c", source="internet",
         view="broadcast camera behind the batter's net, 1920x1080 at 25 Hz",
         skip="the near stumps are cut off at the bottom of the frame, so their bases cannot be tapped"),
    dict(file="clip2.mp4", sha256="108e809d692df2c7f5435f74e9e86ccd8fd6242fcc77beb34878cd5aac3422c3", source="internet",
         view="ground-level camera behind one set of stumps in a covered net, 1920x1080 at 25 Hz",
         skip="only one set of stumps and no pitch markings, so the twelve calibration marks do not exist"),
    dict(file="clip3.mp4", sha256="7c5abe28db25d3d78e4f3d4a75595043f08b0ac950e2b8c37364b328a410dc9e", source="internet",
         view="broadcast camera behind the batter, 1920x1080 at 50 Hz",
         skip="the bowler's end is out of frame and the batter hides the near stumps"),
    dict(file="clip4.mp4", sha256="957b2475cd3b5ca5ca09f7e30ef65ff0138254b59e3d3db57f0edb06f29db7c0", source="internet",
         view="broadcast camera behind the batter, 1920x1080 at 50 Hz",
         skip="the bowler's end is out of frame and the batter hides the near stumps"),
    dict(file="0VRP9dKPFzw.mp4", sha256="0b1611a969b7cfe8b73a3b467a9413d6f6c2045621226c7d1ce431ec7c1326cf", source="internet",
         view="tripod behind portable stumps in an indoor net, 640x360 at 30 Hz",
         skip="the near stumps' bases are below the frame, and the portable stumps' height and spacing are unknown"),
    dict(file="5LpMsb5_w7s.mp4", sha256="5983278f13388dcc4cb97f1b43e12d261851688bce57f75ea8826e235851d3d1", source="internet",
         view="tripod behind portable stumps on a base in an indoor net, screen recording of another app, 720x1280 at 30 Hz",
         skip="no pitch corners, and the portable stumps' height and the distance between the sets are unknown"),
    dict(file="GyG9zHZdpKM.mp4", sha256="d517e7729e3161d1ecf6d9e9e5382dc52685e2a2fcfe60ac89d7769800b28d2b", source="internet",
         view="promotional edit of another app, cuts between screens and cameras, 1080x1920 at 50 Hz",
         skip="no continuous single-camera delivery to calibrate and track"),
]


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def focal_rel_sigma():
    with open(os.path.join(OUT, "exp1_ablation.csv"), newline="") as fh:
        e = [abs(float(r["calib_focal_err_pct"])) for r in csv.DictReader(fh)
             if r["sweep"] == "calib=app" and r["estimator"] == "anchored" and r["calib_focal_err_pct"]]
    return float(np.median(e)) / 100


# where the mat's corners sit in the first frame (SL, SR, BR, BL); the near pair is the frame's bottom edge
CORNERS = {"test3": [(0.420, 0.465), (0.595, 0.465), (0.625, 0.800), (0.305, 0.800)],
           "test4": [(0.398, 0.532), (0.591, 0.532), (0.833, 0.982), (0.160, 0.982)],
           "test5": [(0.398, 0.532), (0.591, 0.532), (0.833, 0.982), (0.160, 0.982)]}


def landmarks(name, size):
    """Ground error (mm) of the four tapped pitch corners under a pose solved from the stumps alone."""
    (striker, bowler), corners = TAPS[name], CORNERS[name]
    px = lambda pts: [(x * size[0], y * size[1]) for x, y in pts]
    stumps = px(striker + bowler)
    pose = solve_camera_pose(image_size=size, stump_quads_px=stumps, crease_marks_px=None, pitch_length_m=PITCH_LENGTH_M)
    hw = PITCH_WIDTH_M / 2
    truth = [(0.0, -hw), (0.0, hw), (pose.pitch_length_m, hw), (pose.pitch_length_m, -hw)]
    out = []
    for (u, v), w in zip(px(corners), truth):
        g = pose.backproject_to_plane(u, v, 0.0)
        out.append(None if g is None else [float((g[0] - w[0]) * 1000), float((g[1] - w[1]) * 1000)])
    return pose.pitch_length_m, out


def gravity(pose_d, dets, t_b):
    """Residuals of the flight before the bounce with g free. A free g trades exactly against the
    scale about the camera, so the ball is held at z = R at the bounce the app found."""
    K, R, tv = (np.array(pose_d[k]) for k in ("K", "R", "t"))
    pre = [d for d in dets if d[0] < t_b]
    t = np.array([d[0] for d in pre]); uv = np.array([[d[1], d[2]] for d in pre]); w = np.sqrt([d[4] for d in pre])

    def res(th):
        p = th[:3] + np.outer(t, th[3:6]) + 0.5 * np.outer(t ** 2, [0.0, 0.0, -th[6]])
        q = (p @ R.T + tv) @ K.T
        z_b = th[2] + th[5] * t_b - 0.5 * th[6] * t_b ** 2
        return np.r_[((q[:, :2] / q[:, 2:3] - uv) * w[:, None]).ravel(), 1e4 * (z_b - BALL_RADIUS_M)]

    return pre, res


def fit_g(pose_d, dets, t_b, p0, v_pre):
    """Fitted g and its 95 % interval, started from the app's path; None if the fit fails or has no dof."""
    pre, resid = gravity(pose_d, dets, t_b)
    th0 = np.r_[p0, np.array(v_pre) + [0.0, 0.0, GRAVITY * t_b], GRAVITY]
    sol = least_squares(resid, th0, x_scale="jac")
    dof = sol.fun.size - 1 - sol.x.size
    if not sol.success or dof <= 0:
        return None
    sg = float(math.sqrt(np.linalg.pinv(sol.jac.T @ sol.jac)[6, 6] * float(sol.fun[:-1] @ sol.fun[:-1]) / dof))
    q = float(student_t.ppf(0.975, dof))
    return dict(n=len(pre), g=float(sol.x[6]), lo=float(sol.x[6] - q * sg), hi=float(sol.x[6] + q * sg))


def sim_gravity(n=SIM_N):
    """The same check on the first n bowler's-end World B deliveries with a seen bounce (drag on, as in
    World B), with the solved pose and the fitted bounce time, as on the real clips."""
    from exp6_coverage import draw
    from uq import CAMS, CalibrationError, estimate, fly, observe, solve, taps
    out = []
    for i in range(1, 10 ** 6, 2):          # odd i is the bowler's end in World B
        if len(out) == n:
            return out
        d, eff, rng = draw(i)
        pt = CAMS["bowler"].pose()
        xy = taps(pt, eff, rng)
        try:
            tr, pose = fly(d, dt=5e-4), solve(pt, xy)
        except (ValueError, CalibrationError):
            continue
        dets = observe(tr, pt, eff, rng)
        est = estimate(pose, dets)
        if est is None or not est["bounce"]:
            continue
        t = est["meas"].rec.trajectory
        g = fit_g(dict(K=pose.K, R=pose.R, t=pose.t), sorted(dets), t.t_b, t.position(0.0)[0], t.v_pre)
        out.append(dict(i=i, **(g or dict(n=0, g=None, lo=None, hi=None))))


def main():
    t0 = time.time()
    with open(os.path.join(OUT, "exp10_config.json"), "w") as fh:
        json.dump(CLIPS, fh, indent=2)
    u_f = focal_rel_sigma()
    rows, summary = [], dict(u_ball_rel=U_BALL, u_focal_rel=u_f, g_ref=GRAVITY, outcome=OUTCOME, clips={})
    for c in CLIPS:
        name = c["file"][:-4]
        ent = summary["clips"][c["file"]] = {k: v for k, v in c.items() if k != "file"}
        if "skip" in c:
            continue
        path = ROOT / c["file"]
        if sha256(path) != c["sha256"]:
            raise SystemExit(f"{c['file']} is not the clip this experiment names")
        res = run_pipeline(video_path=path, request_json=build_request(name),
                           artifacts_dir=Path(tempfile.mkdtemp(prefix=f"pdrs_real_{name}_")), progress=None).result
        size = (res["image_size"]["width"], res["image_size"]["height"])
        if "same_stumps_as" in c:
            # one scene, so one calibration check; record how far this clip's own taps sit from that one's
            other = c["same_stumps_as"][:-4]
            ent["landmarks"] = dict(same_as=c["same_stumps_as"], tap_diff_px=[
                round(float(np.hypot((a[0] - b[0]) * size[0], (a[1] - b[1]) * size[1])), 1)
                for a, b in zip(sum(TAPS[name], []), sum(TAPS[other], []))])
        else:
            L, corner_err = landmarks(name, size)
            ent["landmarks"] = dict(pitch_length_m=L, corner_err_mm=corner_err,
                                    corner_dist_mm=[None if e is None else float(np.hypot(*e)) for e in corner_err])
        wt = res.get("world_trajectory")
        if wt is None:
            ent["declined"] = [(res["no_call"] or {}).get("message")] + res["diagnostics"]["warnings"]
            continue
        pose = res["calibration"]["pose"]
        pts = res["track"]["image_points"]
        model = wt["model"]
        w0 = np.array([[p["x"], p["y"], p["z"]] for p in wt["points_m"]])
        if model["bounce_observed"]:      # without a seen bounce nothing but the size cue fixes the scale
            # gravity: before the bounce, from the same detections the app fitted
            t_b = model["t_b_s"]
            g = fit_g(pose, detections(pts, size[1]), t_b, w0[0], model["v_pre_ms"])
            if g:
                ent["gravity"] = g
        # ball size
        R_, tv, fx = np.array(pose["R"]), np.array(pose["t"]), float(pose["fx"])
        d_fit = (w0 @ R_.T + tv)[:, 2]
        r = np.array([p["radius_px"] for p in pts]); ts = np.array([p["t_ms"] for p in pts]) / 1000.0
        keep = r > 1.0
        ts, r, d_fit = ts[keep], r[keep], d_fit[keep]
        d_size = fx * BALL_RADIUS_M / r
        inv = 1.0 / r
        u_r = float(np.std(inv - np.polyval(np.polyfit(ts - ts[0], inv, 2), ts - ts[0]), ddof=3) / np.mean(inv)) if len(r) > 3 else float("nan")
        u_rel = math.sqrt(u_r ** 2 + U_BALL ** 2 + u_f ** 2)
        z = (d_size - d_fit) / (u_rel * d_size)
        for k in range(len(r)):
            rows.append(dict(clip=c["file"], t_s=round(float(ts[k]), 4), radius_px=round(float(r[k]), 2), d_size_m=round(float(d_size[k]), 3),
                             u_size_m=round(float(u_rel * d_size[k]), 3), d_fit_m=round(float(d_fit[k]), 3), z=round(float(z[k]), 3)))
        ent["size"] = dict(n=int(len(r)), u_size_rel=u_rel, median_ratio=float(np.median(d_size / d_fit)),
                           within_2u_pct=float(100 * np.mean(np.abs(z) <= 2)))
        print(c["file"], json.dumps({k: ent.get(k) for k in ("landmarks", "gravity", "size")}, default=float), flush=True)
    with open(os.path.join(OUT, "exp10_size.csv"), "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader(); wr.writerows(rows)
    summary["sim_gravity"] = sim_gravity()
    summary["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT, "exp10_real.json"), "w") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
