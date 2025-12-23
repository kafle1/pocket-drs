# Research notes (curated, practical)

This is a “what should I read / implement” list, tuned for a student prototype.

## 1) Calibration / pose estimation
- OpenCV `solvePnP` (camera pose from known 3D points)
- Use markers for reliability:
  - ArUco markers (OpenCV module)
  - AprilTag (separate libs; often more robust)

Key idea: **calibration must be easier than tracking**. If calibration is shaky, everything downstream breaks.

## 2) Ball detection & tracking
Two viable approaches:
1. Classical CV (fastest to prototype):
   - background subtraction / frame differencing
   - blob detection + size filtering
   - circle detection (Hough) (sometimes works)
   - track linking + Kalman filter
2. ML detector (more robust, more work):
   - train or fine-tune a small model (e.g., YOLO-style) and run with TFLite

Practical tip: early prototypes can constrain the environment:
- tripod, stable camera
- daylight
- consistent ball color

## 3) Monocular 3D trajectory reconstruction
Monocular ambiguity means you must add constraints:
- known pitch geometry + stumps
- assume trajectory lies in a vertical delivery plane (reasonable approximation)
- fit a physics model and solve for parameters that best explain the 2D track

Recommended prototype approach:
- reconstruct 3D points by intersecting each pixel-ray with an estimated delivery plane
- refine plane/parameters by minimizing reprojection error

## 4) Physics model
Start simple, then add complexity:
1. Gravity-only ballistic model
2. Add drag
3. Add Magnus (spin) if you have time and enough data to fit it

## 5) Audio-video sync (stretch)
Start with single-device audio events aligned to video timestamps.
Dual-device sync requires:
- a clock offset estimate (NTP-like ping/pong over UDP)
- drift handling (short recordings reduce drift impact)
- mapping audio timestamp -> nearest video frame
