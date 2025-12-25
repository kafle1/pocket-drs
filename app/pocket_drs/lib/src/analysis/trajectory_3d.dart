import 'dart:math' as math;
import 'package:flutter/material.dart';

/// Cricket ball physics constants
class BallPhysics {
  static const double stumpHeightM = 0.71;
  static const double ballRadiusM = 0.036;
}

/// A point in 3D space on the pitch
class TrajectoryPoint3D {
  final double x; // meters along pitch (0 = stumps)
  final double y; // meters across pitch (0 = center)
  final double z; // meters height above ground
  final int tMs;

  const TrajectoryPoint3D({
    required this.x,
    required this.y,
    required this.z,
    required this.tMs,
  });
}

/// Estimates 3D trajectory from 2D pitch plane points
class Trajectory3DEstimator {
  /// Estimate Z (height) for each point based on bounce and impact positions
  List<TrajectoryPoint3D> estimate({
    required List<Offset> points,
    required List<int> timesMs,
    required int bounceIndex,
    required int impactIndex,
    double releaseHeight = 2.0,
    double impactHeight = 0.5,
  }) {
    if (points.isEmpty || points.length != timesMs.length) {
      return [];
    }

    final n = points.length;
    final bounce = bounceIndex.clamp(0, n - 1);
    final impact = impactIndex.clamp(bounce, n - 1);
    final result = <TrajectoryPoint3D>[];

    for (int i = 0; i < n; i++) {
      final p = points[i];
      final z = _estimateHeight(i, bounce, impact, n, releaseHeight, impactHeight);
      result.add(TrajectoryPoint3D(x: p.dx, y: p.dy, z: z, tMs: timesMs[i]));
    }

    return result;
  }

  double _estimateHeight(int i, int bounce, int impact, int n, double release, double impactH) {
    if (i <= bounce) {
      // Descending from release to ground
      final t = bounce > 0 ? i / bounce : 1.0;
      return release * (1 - t) + BallPhysics.ballRadiusM * t;
    } else if (i <= impact) {
      // Post-bounce parabola
      final span = math.max(1, impact - bounce);
      final t = (i - bounce) / span;
      final peak = impactH * 1.3;
      return 4 * (peak - BallPhysics.ballRadiusM) * t * (1 - t) +
          BallPhysics.ballRadiusM +
          (impactH - BallPhysics.ballRadiusM) * t;
    } else {
      // After impact: descending
      final span = math.max(1, n - 1 - impact);
      final t = (i - impact) / span;
      return (impactH * (1 - t)).clamp(0, 3.0);
    }
  }

  /// Extend trajectory from impact point to stumps (x = 0)
  List<TrajectoryPoint3D> extendToStumps({
    required List<TrajectoryPoint3D> track,
    required int impactIndex,
    int steps = 10,
  }) {
    if (track.isEmpty || impactIndex < 0 || impactIndex >= track.length) {
      return track;
    }

    final impact = track[impactIndex];
    if (impact.x <= 0) return track;

    // Linear fit using tail points
    final tailStart = math.max(0, impactIndex - 5);
    final tail = track.sublist(tailStart, impactIndex + 1);
    if (tail.length < 2) return track;

    final yAtStumps = _linearFitY(tail);
    if (yAtStumps == null) return track;

    final result = List<TrajectoryPoint3D>.from(track);
    final xStep = impact.x / steps;

    for (int i = 1; i <= steps; i++) {
      final t = i / steps;
      result.add(TrajectoryPoint3D(
        x: impact.x - xStep * i,
        y: impact.y + (yAtStumps - impact.y) * t,
        z: (impact.z * (1 - t * 0.3)).clamp(0.0, BallPhysics.stumpHeightM + 0.2),
        tMs: impact.tMs + i * 10,
      ));
    }

    return result;
  }

  double? _linearFitY(List<TrajectoryPoint3D> points) {
    double sumX = 0, sumY = 0, sumXX = 0, sumXY = 0;
    for (final p in points) {
      sumX += p.x;
      sumY += p.y;
      sumXX += p.x * p.x;
      sumXY += p.x * p.y;
    }
    final n = points.length.toDouble();
    final denom = n * sumXX - sumX * sumX;
    if (denom.abs() < 1e-9) return null;

    final slope = (n * sumXY - sumX * sumY) / denom;
    final intercept = (sumY - slope * sumX) / n;
    return intercept; // y at x=0
  }
}
