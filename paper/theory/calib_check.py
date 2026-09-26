#!/usr/bin/env python
"""Is the app's calibration step efficient? Solve the pose from the twelve taps (2 px) many
times, compare the pose error covariance with its CRLB (pose and focal length unknown), and
push both through the first-order crossing map of the ball fit. Rows: the app's pose without
its refine (the submitted solver), the app's pose as it now ships, and this file's own refine
started from the unrefined pose.
Seeded. Usage:  <venv>/bin/python paper/theory/calib_check.py   (writes out/calib_check.txt)"""
import os
import sys

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crlb import OUT, CAMERAS, truth_theta, frame_times, setup, lin_bound, tap_points  # noqa: E402
from synth import Delivery, calibration_taps                                         # noqa: E402
from app.pipeline.calibration import CalibrationError, solve_camera_pose             # noqa: E402

N, SIG_TAP, SEED = 400, 2.0, 20260926
POSE = CAMERAS["striker_ref"].pose()


def pose_error(p):
    w = Rotation.from_matrix(p.R @ POSE.R.T).as_rotvec()   # R_hat = exp([w]x) R, the crlb.py convention
    return np.concatenate([w, p.t - POSE.t, [p.fx - POSE.fx]])


def refine(p, taps):
    """Reprojection-error least squares over pose and focal length, started from the app's pose.
    Returns the error in the same coordinates as pose_error."""
    X = tap_points()

    def res(z):
        R = Rotation.from_rotvec(z[:3]).as_matrix() @ p.R
        pc = X @ R.T + p.t + z[3:6]
        f = p.fx + z[6]
        return np.concatenate([f * pc[:, 0] / pc[:, 2] + p.cx, f * pc[:, 1] / pc[:, 2] + p.cy]) - taps

    z = least_squares(res, np.zeros(7), method="lm", x_scale=[1e-3] * 3 + [1e-2] * 3 + [10.0]).x
    R = Rotation.from_rotvec(z[:3]).as_matrix() @ p.R
    w = Rotation.from_matrix(R @ POSE.R.T).as_rotvec()
    return np.concatenate([w, p.t + z[3:6] - POSE.t, [p.fx + z[6] - POSE.fx]])


def main():
    rng = np.random.default_rng(SEED)
    errs_un, errs, errs_lm, corners, kept, fails = [], [], [], 0, 0, 0
    for _ in range(N):
        try:
            p, st, co = calibration_taps(POSE, noise_px=SIG_TAP, rng=rng)
            p0 = solve_camera_pose(image_size=(int(POSE.cx * 2), int(POSE.cy * 2)), stump_quads_px=st,
                                   pitch_corners_px=co, pitch_length_m=p.pitch_length_m, refine=False)
        except CalibrationError:
            fails += 1
            continue
        errs_un.append(pose_error(p0))
        errs.append(pose_error(p))
        uv = np.array(st + co)
        errs_lm.append(refine(p0, np.concatenate([uv[:, 0], uv[:, 1]])))
        corners += bool(p.used_corners)
        kept += bool(p.refined)
    Eun, E, Elm = np.array(errs_un), np.array(errs), np.array(errs_lm)
    lines = [f"draws {len(E)} of {N}, failures {fails}, used the pitch corners {corners}, "
             f"app refine kept {kept}, focal {POSE.fx:.1f} px",
             f"unrefined: mean error (w rad x3, t m x3, f px) {np.array2string(Eun.mean(0), precision=5)}",
             f"unrefined: sd {np.array2string(Eun.std(0, ddof=1), precision=5)}",
             f"app pose: mean error {np.array2string(E.mean(0), precision=5)}",
             f"app pose: sd {np.array2string(E.std(0, ddof=1), precision=5)}",
             f"refined:  mean error {np.array2string(Elm.mean(0), precision=5)}"]
    th0 = truth_theta(Delivery(speed_kmh=120, length_m=8.0, line_m=0.2))
    S0 = setup(th0, POSE, frame_times(th0, POSE, 60.0))
    Jt = S0["Jtapf"] / SIG_TAP
    Ccr = np.linalg.inv(Jt.T @ Jt)
    Cun, Cem, Clm = np.cov(Eun.T), np.cov(E.T), np.cov(Elm.T)
    lines.append("CRLB sd per pose coordinate: " + np.array2string(np.sqrt(np.diag(Ccr)), precision=5))
    for tag, C in (("unrefined", Cun), ("app pose", Cem), ("refined ", Clm)):
        lines.append(f"{tag}: sd empirical / sd CRLB per coordinate " + " ".join(
            f"{a:.2f}" for a in np.sqrt(np.diag(C) / np.diag(Ccr))))
        ev = np.linalg.eigvals(np.linalg.solve(Ccr, C)).real
        lines.append(f"{tag}: generalised eigenvalues of Cemp vs CRLB min {ev.min():.2f} max {ev.max():.2f} "
                     f"(1 means efficient, >1 means information is lost)")
    for s, L in ((90, 8.0), (120, 8.0), (145, 8.0), (120, 6.0), (90, 6.0)):
        th = truth_theta(Delivery(speed_kmh=s, length_m=L, line_m=0.2, friction=0.10))
        S = setup(th, POSE, frame_times(th, POSE, 60.0))
        _, _, _, M = lin_bound(S["J"], S["G"], want_M=True)
        MJ = M @ S["Jphif"]                                   # crossing error = -MJ dphi to first order
        sd_cr = np.sqrt(np.diag(MJ @ Ccr @ MJ.T))
        sd_un = np.sqrt(np.diag(MJ @ Cun @ MJ.T))
        sd_em = np.sqrt(np.diag(MJ @ Cem @ MJ.T))
        sd_lm = np.sqrt(np.diag(MJ @ Clm @ MJ.T))
        b_un, bias = -(MJ @ Eun.mean(0)), -(MJ @ E.mean(0))
        lines.append(f"s{s}_L{L:g}: crossing sd from calibration alone, CRLB-optimal pose {100 * sd_cr[0]:.2f}/"
                     f"{100 * sd_cr[1]:.2f} cm, unrefined {100 * sd_un[0]:.2f}/{100 * sd_un[1]:.2f} cm, "
                     f"app pose {100 * sd_em[0]:.2f}/{100 * sd_em[1]:.2f} cm, "
                     f"refined {100 * sd_lm[0]:.2f}/{100 * sd_lm[1]:.2f} cm, "
                     f"unrefined bias {100 * b_un[0]:+.2f}/{100 * b_un[1]:+.2f} cm, "
                     f"app bias {100 * bias[0]:+.2f}/{100 * bias[1]:+.2f} cm")
    txt = "\n".join(lines)
    print(txt)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "calib_check.txt"), "w") as f:
        f.write(txt + "\n")


if __name__ == "__main__":
    main()
