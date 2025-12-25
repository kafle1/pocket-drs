// Hawk-Eye visualization (offline-friendly)
//
// We intentionally avoid external dependencies (e.g., Three.js via CDN) so the
// WebView works without internet access. This renderer draws a clean isometric
// “3D-like” scene on a 2D canvas.
(function () {
  'use strict';

  // Default dimensions (meters)
  const PITCH_LENGTH = 20.12;
  const PITCH_WIDTH = 3.05;
  const STUMP_HEIGHT = 0.71;
  const STUMP_SPACING = 0.057;

  const COLORS = {
    bg: '#0f172a',
    ground: '#12310b',
    pitch: '#2d5016',
    crease: 'rgba(255,255,255,0.9)',
    stumps: '#d4a574',
    preBounce: '#3b82f6',
    postBounce: '#22c55e',
    predicted: '#f59e0b',
    bounce: '#ef4444',
    impact: '#8b5cf6'
  };

  /** @type {HTMLCanvasElement | null} */
  let canvas = null;
  /** @type {CanvasRenderingContext2D | null} */
  let ctx = null;
  let dpr = 1;

  let current = null; // latest trajectory payload from Flutter

  function init() {
    canvas = document.getElementById('canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    if (!ctx) return;

    window.addEventListener('resize', resize, { passive: true });
    resize();
    render();
  }

  function resize() {
    if (!canvas || !ctx) return;

    const container = document.getElementById('container');
    const w = container ? container.clientWidth : window.innerWidth;
    const h = container ? container.clientHeight : window.innerHeight;

    dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    render();
  }

  /**
   * Isometric-ish projection from world (x along pitch, y lateral, z height)
   * to screen (px).
   */
  function project(p, view) {
    const angle = Math.PI / 6; // 30deg
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);

    const x = p.x;
    const y = p.y;
    const z = p.z || 0;

    const isoX = (x - y) * cos;
    const isoY = (x + y) * sin;

    return {
      x: view.originX + isoX * view.scale,
      y: view.originY - isoY * view.scale - z * view.zScale
    };
  }

  function computeView(width, height) {
    // Fit pitch comfortably with a bit of margin.
    const margin = 24;
    const usableW = Math.max(1, width - margin * 2);
    const usableH = Math.max(1, height - margin * 2);

    // Scale tuned for the isometric projection.
    const scaleX = usableW / (PITCH_LENGTH * 1.35);
    const scaleY = usableH / (PITCH_LENGTH * 0.85);
    const scale = Math.max(10, Math.min(scaleX, scaleY) * 1.25);

    return {
      originX: margin + usableW * 0.25,
      originY: margin + usableH * 0.78,
      scale: scale,
      zScale: scale * 0.9
    };
  }

  function clear(width, height) {
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, width, height);
  }

  function drawPolygon(points, fillStyle, strokeStyle, lineWidth) {
    if (!ctx || points.length < 3) return;
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.closePath();
    if (fillStyle) {
      ctx.fillStyle = fillStyle;
      ctx.fill();
    }
    if (strokeStyle) {
      ctx.strokeStyle = strokeStyle;
      ctx.lineWidth = lineWidth || 1;
      ctx.stroke();
    }
  }

  function drawLine(a, b, strokeStyle, lineWidth) {
    if (!ctx) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = lineWidth || 1;
    ctx.lineCap = 'round';
    ctx.stroke();
  }

  function drawCircle(p, radius, fillStyle) {
    if (!ctx) return;
    ctx.beginPath();
    ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = fillStyle;
    ctx.fill();
  }

  function render() {
    if (!canvas || !ctx) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const view = computeView(width, height);

    clear(width, height);

    // Ground (bigger plane under pitch)
    const ground = [
      project({ x: -6, y: -10, z: 0 }, view),
      project({ x: -6, y: 10, z: 0 }, view),
      project({ x: PITCH_LENGTH + 18, y: 10, z: 0 }, view),
      project({ x: PITCH_LENGTH + 18, y: -10, z: 0 }, view)
    ];
    drawPolygon(ground, COLORS.ground, null, 0);

    // Pitch rectangle
    const halfW = PITCH_WIDTH / 2;
    const pitch = [
      project({ x: 0, y: -halfW, z: 0 }, view),
      project({ x: 0, y: halfW, z: 0 }, view),
      project({ x: PITCH_LENGTH, y: halfW, z: 0 }, view),
      project({ x: PITCH_LENGTH, y: -halfW, z: 0 }, view)
    ];
    drawPolygon(pitch, COLORS.pitch, 'rgba(255,255,255,0.12)', 1);

    // Crease lines
    drawLine(project({ x: 0, y: -halfW, z: 0.002 }, view), project({ x: 0, y: halfW, z: 0.002 }, view), COLORS.crease, 2);
    drawLine(project({ x: PITCH_LENGTH, y: -halfW, z: 0.002 }, view), project({ x: PITCH_LENGTH, y: halfW, z: 0.002 }, view), COLORS.crease, 2);

    // Stumps at x=0
    for (let i = -1; i <= 1; i++) {
      const y = i * STUMP_SPACING;
      const base = project({ x: 0, y: y, z: 0 }, view);
      const top = project({ x: 0, y: y, z: STUMP_HEIGHT }, view);
      drawLine(base, top, COLORS.stumps, 4);
    }

    // Bail (simple line)
    const bailL = project({ x: 0, y: -STUMP_SPACING, z: STUMP_HEIGHT + 0.02 }, view);
    const bailR = project({ x: 0, y: STUMP_SPACING, z: STUMP_HEIGHT + 0.02 }, view);
    drawLine(bailL, bailR, COLORS.stumps, 3);

    // Trajectory (if present)
    if (!current || !current.points || current.points.length < 2) return;

    const pts = current.points
      .filter(p => p && isFinite(p.x) && isFinite(p.y) && isFinite(p.z))
      .map(p => ({ x: Number(p.x), y: Number(p.y), z: Number(p.z) }));
    if (pts.length < 2) return;

    const bounceIndex = clampInt(current.bounceIndex, 0, pts.length - 1);
    const impactIndex = clampInt(current.impactIndex, 0, pts.length - 1);

    // Segments
    drawTrackSegment(pts, 0, Math.min(bounceIndex, pts.length - 1), COLORS.preBounce, view);
    drawTrackSegment(pts, Math.max(0, bounceIndex), Math.min(impactIndex, pts.length - 1), COLORS.postBounce, view);
    if (impactIndex < pts.length - 1) {
      drawTrackSegment(pts, impactIndex, pts.length - 1, COLORS.predicted, view);
    }

    // Markers
    drawCircle(project(pts[bounceIndex], view), 6, COLORS.bounce);
    drawCircle(project(pts[impactIndex], view), 6, COLORS.impact);

    // If the predicted tail reaches close to stumps, highlight last point.
    const last = pts[pts.length - 1];
    if (last.x <= 0.5) {
      drawCircle(project(last, view), 6, COLORS.predicted);
    }

    updateDecision(current.decision);
  }

  function drawTrackSegment(points, startIdx, endIdx, color, view) {
    if (!ctx) return;
    if (endIdx - startIdx < 1) return;
    ctx.beginPath();
    const p0 = project(points[startIdx], view);
    ctx.moveTo(p0.x, p0.y);
    for (let i = startIdx + 1; i <= endIdx; i++) {
      const p = project(points[i], view);
      ctx.lineTo(p.x, p.y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();
  }

  function clampInt(v, lo, hi) {
    const n = Number(v);
    if (!isFinite(n)) return lo;
    return Math.max(lo, Math.min(hi, Math.round(n)));
  }

  function updateDecision(decision) {
    const el = document.getElementById('decision');
    if (!el) return;
    el.className = '';
    el.style.display = 'none';

    if (decision === 'out') {
      el.textContent = 'OUT';
      el.className = 'out';
    } else if (decision === 'not_out') {
      el.textContent = 'NOT OUT';
      el.className = 'not-out';
    } else if (decision === 'umpires_call') {
      el.textContent = "UMPIRE'S CALL";
      el.className = 'umpires-call';
    }
  }

  function updateTrajectory(data) {
    current = data || null;
    updateDecision(current && current.decision);
    render();
  }

  // Expose API to Flutter
  window.hawkeye = { updateTrajectory: updateTrajectory };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
