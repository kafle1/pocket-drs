"""Shared calibration error type.

The camera solve itself lives in ``reconstruction.solve_camera_pose_from_stumps``
(stump-anchored PnP with joint FOV/length fitting). This module keeps only the
exception both it and ``process_job`` raise on an unusable calibration.
"""

from __future__ import annotations


class CalibrationError(RuntimeError):
    pass
