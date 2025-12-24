import 'dart:ui';

/// Simple 3x3 homography for mapping image pixels -> plane coordinates.
///
/// This uses a minimal 4-point solve (DLT with h33 fixed to 1) and is intended
/// for interactive calibration (not photogrammetry-grade).
class Homography {
  Homography._(this._h);

  final List<double> _h; // row-major length 9

  List<double> get values => List<double>.unmodifiable(_h);

  /// Applies homography to a 2D point.
  Offset transform(Offset p) {
    final x = p.dx;
    final y = p.dy;

    final h11 = _h[0];
    final h12 = _h[1];
    final h13 = _h[2];
    final h21 = _h[3];
    final h22 = _h[4];
    final h23 = _h[5];
    final h31 = _h[6];
    final h32 = _h[7];
    final h33 = _h[8];

    final den = h31 * x + h32 * y + h33;
    if (den == 0) return const Offset(double.nan, double.nan);

    final X = (h11 * x + h12 * y + h13) / den;
    final Y = (h21 * x + h22 * y + h23) / den;
    return Offset(X, Y);
  }

  /// Builds a homography that maps [src] pixels to [dst] plane coordinates.
  ///
  /// Requires exactly 4 point pairs.
  static Homography fromFourPoints({
    required List<Offset> src,
    required List<Offset> dst,
  }) {
    if (src.length != 4 || dst.length != 4) {
      throw ArgumentError('Expected 4 source and 4 destination points');
    }

    // Solve for: [h11 h12 h13 h21 h22 h23 h31 h32] with h33=1.
    final A = List<List<double>>.generate(
      8,
      (_) => List<double>.filled(8, 0),
      growable: false,
    );
    final b = List<double>.filled(8, 0);

    for (var i = 0; i < 4; i++) {
      final x = src[i].dx;
      final y = src[i].dy;
      final X = dst[i].dx;
      final Y = dst[i].dy;

      final r0 = 2 * i;
      final r1 = r0 + 1;

      // h11 x + h12 y + h13 - X h31 x - X h32 y = X
      A[r0][0] = x;
      A[r0][1] = y;
      A[r0][2] = 1;
      A[r0][3] = 0;
      A[r0][4] = 0;
      A[r0][5] = 0;
      A[r0][6] = -X * x;
      A[r0][7] = -X * y;
      b[r0] = X;

      // h21 x + h22 y + h23 - Y h31 x - Y h32 y = Y
      A[r1][0] = 0;
      A[r1][1] = 0;
      A[r1][2] = 0;
      A[r1][3] = x;
      A[r1][4] = y;
      A[r1][5] = 1;
      A[r1][6] = -Y * x;
      A[r1][7] = -Y * y;
      b[r1] = Y;
    }

    final x = _solveLinearSystem(A, b);
    final h = <double>[
      x[0], x[1], x[2],
      x[3], x[4], x[5],
      x[6], x[7], 1.0,
    ];

    return Homography._(h);
  }
}

List<double> _solveLinearSystem(List<List<double>> A, List<double> b) {
  final n = b.length;
  if (A.length != n || A.any((r) => r.length != n)) {
    throw ArgumentError('A must be NxN');
  }

  // Build augmented matrix.
  final m = List<List<double>>.generate(
    n,
    (i) => <double>[...A[i], b[i]],
  );

  for (var col = 0; col < n; col++) {
    // Pivot.
    var pivotRow = col;
    var pivotVal = m[pivotRow][col].abs();
    for (var r = col + 1; r < n; r++) {
      final v = m[r][col].abs();
      if (v > pivotVal) {
        pivotVal = v;
        pivotRow = r;
      }
    }

    if (pivotVal < 1e-10) {
      throw StateError('Singular matrix');
    }

    if (pivotRow != col) {
      final tmp = m[col];
      m[col] = m[pivotRow];
      m[pivotRow] = tmp;
    }

    // Normalize pivot row.
    final piv = m[col][col];
    for (var c = col; c <= n; c++) {
      m[col][c] /= piv;
    }

    // Eliminate.
    for (var r = 0; r < n; r++) {
      if (r == col) continue;
      final factor = m[r][col];
      if (factor == 0) continue;
      for (var c = col; c <= n; c++) {
        m[r][c] -= factor * m[col][c];
      }
    }
  }

  final x = List<double>.filled(n, 0);
  for (var i = 0; i < n; i++) {
    x[i] = m[i][n];
  }
  return x;
}
