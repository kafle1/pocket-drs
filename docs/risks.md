# Risk register (so you don’t get surprised later)

## High risk
1. **Ball detection reliability** (small object, motion blur, clutter)
   - Mitigation: tripod + high FPS if available; start with controlled dataset; fallback to ML.
2. **Calibration accuracy** (pose error breaks 3D)
   - Mitigation: printed markers; tap-based manual correction.
3. **Monocular 3D ambiguity**
   - Mitigation: delivery-plane assumption; use optimization + priors.

## Medium risk
4. **Performance on-device**
   - Mitigation: do offline processing after recording; keep models small.
5. **Edge detection over two phones**
   - Mitigation: make it a stretch goal; ship single-device audio first.

## Low risk
6. **UI**
   - Mitigation: simple screens, iterative.
