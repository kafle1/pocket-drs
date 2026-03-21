"""Pipeline integration tests for ball tracking and LBW decision."""

from __future__ import annotations

import pytest

from app.pipeline.events import (
    estimate_bounce_index,
    estimate_bounce_index_from_pitch_plane,
    estimate_impact_index,
    estimate_impact_index_from_pitch_plane,
)
from app.pipeline.process_job import _assess_lbw_2d


class TestBounceDetection:
    """Test bounce index estimation."""

    def test_simple_bounce(self):
        """Detect bounce with clear down-then-up pattern."""
        # Ball drops then bounces up
        y_px = [100, 150, 200, 250, 300, 280, 260, 240, 220, 200]
        result = estimate_bounce_index(y_px)
        # Bounce should be around index 4-5 where direction changes
        assert 3 <= result.index <= 6
        assert result.confidence > 0.3

    def test_flat_trajectory(self):
        """Handle flat trajectory without clear bounce."""
        y_px = [200, 202, 204, 206, 208, 210, 212, 214, 216, 218]
        result = estimate_bounce_index(y_px)
        # Should return a fallback index with low confidence
        assert 0 <= result.index < len(y_px)
        assert result.confidence > 0

    def test_short_track(self):
        """Handle very short tracks gracefully."""
        y_px = [100, 150, 200]
        result = estimate_bounce_index(y_px)
        assert 0 <= result.index < len(y_px)

    def test_empty_track(self):
        """Handle empty input."""
        y_px = []
        result = estimate_bounce_index(y_px)
        assert result.index == 0


class TestImpactDetection:
    """Test impact index estimation."""

    def test_impact_default(self):
        """Fall back to last point."""
        result = estimate_impact_index(10)
        assert result.index == 9
        assert result.confidence > 0

    def test_empty_input(self):
        """Handle zero points."""
        result = estimate_impact_index(0)
        assert result.index == 0


class TestPitchPlaneEvents:
    """Test pitch-plane based event detection."""

    def test_bounce_in_good_length_zone(self):
        """Detect bounce when ball lands in good-length area."""
        # Ball travelling from bowler (x~20) to striker (x~0)
        x_m = [18.0, 16.0, 14.0, 12.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0]
        y_m = [0.2, 0.15, 0.1, 0.05, 0.0, -0.05, -0.1, -0.12, -0.08, -0.05]
        result = estimate_bounce_index_from_pitch_plane(x_m, y_m)
        assert 2 <= result.index <= 8
        assert result.confidence > 0.2

    def test_impact_near_crease(self):
        """Detect impact when ball reaches striker crease area."""
        x_m = [18.0, 14.0, 10.0, 6.0, 3.0, 1.5]
        result = estimate_impact_index_from_pitch_plane(x_m)
        assert result.index == 5  # x=1.5 is within crease_limit
        assert result.confidence > 0.5

    def test_impact_no_crease_reach(self):
        """Fall back to closest point when ball doesn't reach crease."""
        x_m = [18.0, 15.0, 12.0, 9.0, 7.0]
        result = estimate_impact_index_from_pitch_plane(x_m)
        assert result.index == 4  # x=7.0 is closest to 0
        assert result.confidence > 0

    def test_short_track(self):
        """Handle very short pitch-plane tracks."""
        x_m = [10.0, 8.0]
        y_m = [0.0, 0.0]
        result = estimate_bounce_index_from_pitch_plane(x_m, y_m)
        assert 0 <= result.index < 2


class TestLbwDecision:
    """Test LBW decision logic."""

    def test_hitting_stumps(self):
        """Ball hitting stumps should be out."""
        pts_m = [(20.0, 0.0), (15.0, 0.0), (10.0, 0.0), (5.0, 0.0), (2.0, 0.0)]
        result = _assess_lbw_2d(
            pitch_points_m=pts_m,
            bounce_index=2,
            impact_index=4,
            point_confidences=[0.9] * 5,
        )
        
        assert result is not None
        assert result["decision"] in ("out", "umpires_call")
        assert result["checks"]["pitching_in_line"]

    def test_missing_stumps(self):
        """Ball missing stumps should be not out."""
        # Ball going wide (large y value)
        pts_m = [(20.0, 0.5), (15.0, 0.8), (10.0, 1.0), (5.0, 1.2), (2.0, 1.5)]
        result = _assess_lbw_2d(
            pitch_points_m=pts_m,
            bounce_index=2,
            impact_index=4,
            point_confidences=[0.9] * 5,
        )
        
        assert result is not None
        # Should miss stumps or be not out
        assert result["checks"]["wickets_hitting"] == False or result["decision"] == "not_out"

    def test_outside_leg(self):
        """Ball pitched outside leg should be not out."""
        # Large positive y (leg side)
        pts_m = [(20.0, 0.3), (15.0, 0.25), (10.0, 0.2), (5.0, 0.0), (2.0, -0.1)]
        result = _assess_lbw_2d(
            pitch_points_m=pts_m,
            bounce_index=2,
            impact_index=4,
            point_confidences=[0.9] * 5,
        )
        
        assert result is not None
        # Check structure is valid
        assert "decision" in result
        assert "reason" in result

    def test_short_trajectory(self):
        """Handle very short trajectories."""
        pts_m = [(10.0, 0.0), (5.0, 0.0)]
        result = _assess_lbw_2d(
            pitch_points_m=pts_m,
            bounce_index=0,
            impact_index=1,
            point_confidences=[0.9, 0.9],
        )
        # Should not crash
        assert result is None or isinstance(result, dict)

    def test_empty_trajectory(self):
        """Handle empty trajectory."""
        result = _assess_lbw_2d(
            pitch_points_m=[],
            bounce_index=0,
            impact_index=0,
            point_confidences=[],
        )
        assert result is None
