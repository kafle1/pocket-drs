# PocketDRS — Quick questions (answer these first)

These decide the architecture and what we can realistically finish on time.

## Project constraints
1. **Platform**: Android only, or Android + iOS?
2. **Deadline**: what date is your demo and what date is final submission?
3. **Minimum deliverable** required by your college: APK demo only, or also thesis/report + evaluation?
4. **Where will testing happen**: indoor hallway, local ground, or actual matches?

## Video capture
5. What phones do you have access to for testing (models + max FPS: 60/120/240)?
6. Are you okay requiring a **tripod** and fixed camera position?
7. Typical camera placement: behind bowler, side-on, behind wicketkeeper, or flexible?

## Calibration (most important)
8. Are you willing to place **printed markers** (ArUco/AprilTag) near the stumps/crease during recording? (This massively reduces errors.)
9. If no markers: are you okay with a **tap-to-mark** calibration UI (user taps stump tops/crease points)?

## Ball tracking
10. What ball type do you mainly target: tennis ball, tape ball, leather (red/white)?
11. Are you okay limiting to daylight / decent lighting to improve tracking?

## LBW logic
12. Are you okay with user selecting the **impact frame** (pad contact) manually for the prototype?

## Edge detection
13. Is the second phone mandatory in your project scope, or a stretch goal?
14. Is “good-enough” edge support acceptable (single-phone audio), or must it be dual-device sync?

## Success criteria
15. How will you measure success: qualitative demo, or quantitative error (cm) on bounce/stump crossing?
