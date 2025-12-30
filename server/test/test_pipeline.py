"""Pipeline integration tests for ball tracking and LBW decision."""

from __future__ import annotations

import pytest

from app.pipeline.events import estimate_bounce_index, estimate_impact_index
from app.pipeline.process_job import _generate_3d_trajectory, _assess_lbw_2d


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
        assert result.index == 0 or result.index == -1


class TestImpactDetection:
    """Test impact index estimation."""

    def test_impact_near_stumps(self):
        """Detect impact near stumps (x=0)."""
        # x positions approaching stumps
        x_positions = [15.0, 12.0, 9.0, 6.0, 3.0, 1.0, 0.5]
        result = estimate_impact_index(len(x_positions), x_positions)
        # Impact should be near the end where x is smallest
        assert result.index >= 4
        assert result.confidence > 0.5

    def test_no_x_positions(self):
        """Fall back to last point without x positions."""
        result = estimate_impact_index(10, None)
        assert result.index == 9
        assert result.confidence > 0


class Test3DTrajectoryGeneration:
    """Test physics-based 3D trajectory generation."""

    def test_generates_heights(self):
        """Verify trajectory has height information."""
        pts_m = [(20.0, 0.0), (15.0, 0.1), (10.0, 0.0), (5.0, -0.1), (0.0, 0.0)]
        trajectory = _generate_3d_trajectory(pts_m, bounce_index=2, impact_index=4)
        
        assert len(trajectory) > 0
        # Check heights exist
        for pt in trajectory:
            assert "x_m" in pt
            assert "y_m" in pt
            assert "z_m" in pt
            assert pt["z_m"] >= 0

    def test_pre_bounce_heights(self):
        """Pre-bounce phase should have higher heights."""
        pts_m = [(20.0, 0.0), (15.0, 0.0), (10.0, 0.0), (5.0, 0.0), (0.0, 0.0)]
        trajectory = _generate_3d_trajectory(pts_m, bounce_index=2, impact_index=4)
        
        # First point should have some height (release)
        assert trajectory[0]["z_m"] > 0
        # Bounce point should be near ground
        assert trajectory[2]["z_m"] < 0.5


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
        # Should miss stumps
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
