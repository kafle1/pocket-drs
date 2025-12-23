import 'dart:ui';

/// Tiny constant-velocity Kalman filter for (x, y).
///
/// State = [x, y, vx, vy]
class Kalman2D {
  Kalman2D({required Offset initialPosition}) {
    _x = [initialPosition.dx, initialPosition.dy, 0.0, 0.0];
    // Covariance: start uncertain about velocity.
    _p = [
      [25, 0, 0, 0],
      [0, 25, 0, 0],
      [0, 0, 1000, 0],
      [0, 0, 0, 1000],
    ];
  }

  late List<double> _x;
  late List<List<double>> _p;

  // Tunables.
  double processNoisePos = 25.0;
  double processNoiseVel = 250.0;
  double measurementNoise = 64.0;

  Offset get position => Offset(_x[0], _x[1]);

  void predict(double dt) {
    // x = F x
    final x0 = _x[0] + dt * _x[2];
    final y0 = _x[1] + dt * _x[3];
    final vx = _x[2];
    final vy = _x[3];
    _x = [x0, y0, vx, vy];

    // P = F P F^T + Q, where F = [[1,0,dt,0],[0,1,0,dt],[0,0,1,0],[0,0,0,1]]
    final f = [
      [1.0, 0.0, dt, 0.0],
      [0.0, 1.0, 0.0, dt],
      [0.0, 0.0, 1.0, 0.0],
      [0.0, 0.0, 0.0, 1.0],
    ];
    _p = _matAdd(_matMul(_matMul(f, _p), _transpose(f)), [
      [processNoisePos, 0, 0, 0],
      [0, processNoisePos, 0, 0],
      [0, 0, processNoiseVel, 0],
      [0, 0, 0, processNoiseVel],
    ]);
  }

  void update(Offset z) {
    // H = [[1,0,0,0],[0,1,0,0]]
    const h = [
      [1.0, 0.0, 0.0, 0.0],
      [0.0, 1.0, 0.0, 0.0],
    ];
    final r = [
      [measurementNoise, 0.0],
      [0.0, measurementNoise],
    ];

    final zVec = [z.dx, z.dy];
    final y = _vecSub(zVec, _matVecMul(h, _x));
    final s = _matAdd(_matMul(_matMul(h, _p), _transpose(h)), r);
    final k = _matMul(_matMul(_p, _transpose(h)), _inverse2x2(s));

    final xNew = _vecAdd(_x, _matVecMul(k, y));
    final i = [
      [1.0, 0.0, 0.0, 0.0],
      [0.0, 1.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 0.0],
      [0.0, 0.0, 0.0, 1.0],
    ];
    final pNew = _matMul(_matSub(i, _matMul(k, h)), _p);

    _x = xNew;
    _p = pNew;
  }

  // --- minimal linear algebra (small matrices only) ---

  static List<double> _matVecMul(List<List<double>> a, List<double> x) {
    final out = List<double>.filled(a.length, 0);
    for (var r = 0; r < a.length; r++) {
      double s = 0;
      for (var c = 0; c < x.length; c++) {
        s += a[r][c] * x[c];
      }
      out[r] = s;
    }
    return out;
  }

  static List<List<double>> _matMul(List<List<double>> a, List<List<double>> b) {
    final out = List.generate(a.length, (_) => List<double>.filled(b[0].length, 0));
    for (var r = 0; r < a.length; r++) {
      for (var c = 0; c < b[0].length; c++) {
        double s = 0;
        for (var k = 0; k < b.length; k++) {
          s += a[r][k] * b[k][c];
        }
        out[r][c] = s;
      }
    }
    return out;
  }

  static List<List<double>> _transpose(List<List<double>> a) {
    final out = List.generate(a[0].length, (_) => List<double>.filled(a.length, 0));
    for (var r = 0; r < a.length; r++) {
      for (var c = 0; c < a[0].length; c++) {
        out[c][r] = a[r][c];
      }
    }
    return out;
  }

  static List<List<double>> _matAdd(List<List<double>> a, List<List<double>> b) {
    final out = List.generate(a.length, (r) => List<double>.filled(a[0].length, 0));
    for (var r = 0; r < a.length; r++) {
      for (var c = 0; c < a[0].length; c++) {
        out[r][c] = a[r][c] + b[r][c];
      }
    }
    return out;
  }

  static List<List<double>> _matSub(List<List<double>> a, List<List<double>> b) {
    final out = List.generate(a.length, (r) => List<double>.filled(a[0].length, 0));
    for (var r = 0; r < a.length; r++) {
      for (var c = 0; c < a[0].length; c++) {
        out[r][c] = a[r][c] - b[r][c];
      }
    }
    return out;
  }

  static List<double> _vecAdd(List<double> a, List<double> b) {
    final out = List<double>.filled(a.length, 0);
    for (var i = 0; i < a.length; i++) {
      out[i] = a[i] + b[i];
    }
    return out;
  }

  static List<double> _vecSub(List<double> a, List<double> b) {
    final out = List<double>.filled(a.length, 0);
    for (var i = 0; i < a.length; i++) {
      out[i] = a[i] - b[i];
    }
    return out;
  }

  static List<List<double>> _inverse2x2(List<List<double>> a) {
    final det = a[0][0] * a[1][1] - a[0][1] * a[1][0];
    if (det.abs() < 1e-9) {
      // Fallback to identity-ish to avoid crashing; upstream logic should handle low confidence.
      return [
        [1.0, 0.0],
        [0.0, 1.0],
      ];
    }
    final invDet = 1.0 / det;
    return [
      [a[1][1] * invDet, -a[0][1] * invDet],
      [-a[1][0] * invDet, a[0][0] * invDet],
    ];
  }
}
