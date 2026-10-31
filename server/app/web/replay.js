// Draws the tracked ball over the user's own clip: a glowing trail that builds up with playback,
// the predicted path dashed on to the stumps, pitching and impact marks at their moments, and the
// verdict colours. Everything comes from result.overlay, in source-video pixels.
//
//   const replay = drawReplay(canvas, videoEl, result);   // canvas laid exactly over the <video>
//   replay.destroy();                                      // before dropping the canvas or the result

const COLOR = {
  track: "#ff5252",
  out: "#c9302d",         // oklch(0.55 0.19 27)
  not_out: "#1c8742",     // oklch(0.55 0.14 150)
  umpires_call: "#d0901e", // oklch(0.70 0.14 75)
  none: "#9aa59f",
  ink: "#f7f9f7",
  callInk: "#23190a",
  shade: "rgba(12, 17, 15, 0.78)",
};
const CALL_TEXT = { out: "OUT", not_out: "NOT OUT", umpires_call: "UMPIRE'S CALL" };
const POP_MS = 320;

// no verdict leaves the DRS rows neutral
const NEUTRAL = { pitching: "none", impact: "none", wickets: "none" };

const easeOut = k => 1 - Math.pow(1 - Math.min(1, Math.max(0, k)), 3);

// the points up to time t, ending exactly at the ball's position
function upTo(pts, t) {
  if (!pts.length || t < pts[0].t) return [];
  const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    if (b.t <= t) { out.push(b); continue; }
    const f = (t - a.t) / ((b.t - a.t) || 1);
    out.push({ t, u: a.u + (b.u - a.u) * f, v: a.v + (b.v - a.v) * f });
    break;
  }
  return out;
}

export function drawReplay(canvas, video, result) {
  const ctx = canvas.getContext("2d");
  const ov = (result && result.overlay) || {};
  const size = (result && result.image_size) || {};
  const all = (ov.path_px || []).map(p => ({ t: p.t_ms, u: p.u, v: p.v, predicted: p.phase === "predicted" }))
    .sort((a, b) => a.t - b.t);
  const flight = all.filter(p => !p.predicted);
  let ahead = all.filter(p => p.predicted);
  const bounce = ov.bounce_px ? { t: ov.bounce_px.t_ms, u: ov.bounce_px.u, v: ov.bounce_px.v } : null;
  const impact = ov.impact_px ? { t: ov.impact_px.t_ms, u: ov.impact_px.u, v: ov.impact_px.v } : null;
  // the smoothed trail rounds off the bounce, so route it through the pitching point
  if (bounce && flight.length >= 2 && bounce.t > flight[0].t && bounce.t < flight[flight.length - 1].t) {
    flight.splice(flight.findIndex(p => p.t > bounce.t), 0, bounce);
  }
  // the prediction comes from the fitted path; shift it onto the trail's end so the two join without a jump
  if (flight.length && ahead.length) {
    const end = flight[flight.length - 1], du = end.u - ahead[0].u, dv = end.v - ahead[0].v;
    ahead = [end].concat(ahead.map(p => ({ t: p.t, u: p.u + du, v: p.v + dv })));
  }
  const flightEnd = flight.length ? flight[flight.length - 1].t : -Infinity;
  const aheadEnd = ahead.length ? ahead[ahead.length - 1].t : flightEnd;
  const lbw = result && result.lbw;
  const tone = (lbw && lbw.tones) || NEUTRAL;
  const striker = ov.stumps_px && ov.stumps_px.striker;

  let W = 0, H = 0, dpr = 1, raf = 0, dead = false;
  let map = p => [p.u, p.v], scale = 1;

  // where the picture actually sits inside the <video> box (object-fit, letterboxing), in canvas css px
  function layout() {
    const cr = canvas.getBoundingClientRect(), vr = video.getBoundingClientRect();
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = cr.width; H = cr.height;
    const bw = Math.round(W * dpr), bh = Math.round(H * dpr);
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    const srcW = size.width || video.videoWidth || 1, srcH = size.height || video.videoHeight || 1;
    // the decoder's frame and the element's intrinsic size can differ in resolution, never in aspect
    const natW = video.videoWidth || srcW, natH = video.videoHeight || srcH;
    const fitMode = getComputedStyle(video).objectFit || "contain";
    let sx = vr.width / natW, sy = vr.height / natH;
    if (fitMode === "contain") sx = sy = Math.min(sx, sy);
    else if (fitMode === "scale-down") sx = sy = Math.min(1, sx, sy);
    else if (fitMode === "cover") sx = sy = Math.max(sx, sy);
    else if (fitMode === "none") sx = sy = 1;
    const ox = vr.left - cr.left + (vr.width - natW * sx) / 2, oy = vr.top - cr.top + (vr.height - natH * sy) / 2;
    const kx = sx * natW / srcW, ky = sy * natH / srcH;
    map = p => [ox + p.u * kx, oy + p.v * ky];
    scale = natW * sx / 1080;        // line widths follow the picture, tuned on a 1080-wide frame
    // a cover-fitted picture overflows the box; keep the drawing inside it
    clip = [vr.left - cr.left, vr.top - cr.top, vr.width, vr.height];
  }
  let clip = [0, 0, 0, 0];

  function line(pts, color, width, alpha, dash) {
    if (pts.length < 2) return;
    ctx.beginPath();
    pts.forEach((p, i) => { const [x, y] = map(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.setLineDash(dash || []);
    ctx.stroke();
    ctx.globalAlpha = 1; ctx.setLineDash([]);
  }
  function dot(p, r, color, alpha) {
    const [x, y] = map(p);
    ctx.globalAlpha = alpha; ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
  }
  function ring(p, r, color, width, alpha) {
    const [x, y] = map(p);
    ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineWidth = width;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke(); ctx.globalAlpha = 1;
  }
  function wicket(color, k) {
    if (!striker) return;
    const [bx, by] = map(striker.base), [tx, ty] = map(striker.top);
    const half = Math.min(70, Math.max(4, 0.16 * Math.abs(by - ty)));
    ctx.globalAlpha = 0.25 * k; ctx.fillStyle = color;
    ctx.fillRect(tx - half, ty, half * 2, by - ty);
    ctx.globalAlpha = k; ctx.strokeStyle = color; ctx.lineWidth = Math.max(2, 3 * scale); ctx.lineCap = "round";
    ctx.beginPath();
    for (const d of [-half, 0, half]) { ctx.moveTo(bx + d, by); ctx.lineTo(tx + d, ty); }
    ctx.moveTo(tx - half, ty); ctx.lineTo(tx + half, ty);
    ctx.stroke(); ctx.globalAlpha = 1;
  }
  function badge(k) {
    const text = lbw && CALL_TEXT[lbw.decision] ? CALL_TEXT[lbw.decision] : "NO CALL";
    const fill = lbw && CALL_TEXT[lbw.decision] ? COLOR[lbw.decision] : COLOR.shade;
    const fs = Math.round(Math.min(22, Math.max(14, W / 22)));
    ctx.font = `800 ${fs}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
    const w = ctx.measureText(text).width + fs * 1.4, h = fs * 2;
    const x = clip[0] + 12, y = clip[1] + 12 + (1 - easeOut(k)) * -8;
    ctx.globalAlpha = easeOut(k); ctx.fillStyle = fill;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, 10); else ctx.rect(x, y, w, h);
    ctx.fill();
    ctx.fillStyle = fill === COLOR.umpires_call ? COLOR.callInk : COLOR.ink;
    ctx.textBaseline = "middle"; ctx.fillText(text, x + fs * 0.7, y + h / 2 + 1);
    ctx.globalAlpha = 1;
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!flight.length) return;
    ctx.save();
    ctx.beginPath(); ctx.rect(...clip); ctx.clip();
    ctx.lineJoin = ctx.lineCap = "round";
    const t = video.currentTime * 1000;
    const w = Math.min(7, Math.max(2.5, 6 * scale));

    const trail = upTo(flight, t);
    line(trail, COLOR.track, w * 3.2, 0.22);          // glow
    line(trail, COLOR.track, w, 1);                   // body
    line(trail, COLOR.ink, w * 0.3, 0.55);            // hot centre

    const pred = t >= flightEnd ? upTo(ahead, t) : [];
    line(pred, COLOR.track, w * 2.4, 0.14);
    line(pred, COLOR.track, w * 0.9, 0.75, [w * 1.6, w * 1.4]);

    // markers pop in on the video's clock, so a paused clip holds them still
    const pop = at => (t - at) / POP_MS;
    if (bounce && t >= bounce.t) {
      const k = easeOut(pop(bounce.t)), c = COLOR[tone.pitching];
      dot(bounce, w * 1.8 * (0.4 + 0.6 * k), c, 1);
      ring(bounce, w * 3.4 * (0.6 + 0.4 * k), c, Math.max(1.5, w * 0.5), 0.9);
    }
    if (impact && t >= impact.t) {
      const k = pop(impact.t), c = COLOR[tone.impact];
      ring(impact, w * 2.8, c, Math.max(2, w * 0.6), 1);
      if (k < 1) ring(impact, w * (2.8 + 5 * easeOut(k)), c, Math.max(1.5, w * 0.45), 1 - k);
    }
    if (ahead.length && t >= aheadEnd) wicket(COLOR[tone.wickets], easeOut(pop(aheadEnd)));

    // the ball itself, riding the head of whichever path is being drawn
    const head = pred.length >= 2 ? pred[pred.length - 1] : trail.length ? trail[trail.length - 1] : null;
    if (head && t <= aheadEnd + 400) {
      dot(head, w * 2.2, COLOR.track, 0.35);
      dot(head, w * 1.4, COLOR.ink, 1);
      ring(head, w * 1.4, COLOR.track, Math.max(1.5, w * 0.4), 1);
    }
    if (t >= aheadEnd) badge(Math.min(1, pop(aheadEnd)));
    ctx.restore();
  }

  function frame() {
    raf = 0;
    if (dead) return;
    draw();
    if (!video.paused) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf && !dead) raf = requestAnimationFrame(frame); }
  function relayout() { layout(); kick(); }

  const events = ["play", "seeked", "seeking", "loadedmetadata", "timeupdate"];
  events.forEach(e => video.addEventListener(e, e === "loadedmetadata" ? relayout : kick));
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(relayout) : null;
  if (ro) { ro.observe(video); ro.observe(canvas); } else window.addEventListener("resize", relayout);
  relayout();

  return {
    destroy() {
      dead = true;
      if (raf) cancelAnimationFrame(raf);
      events.forEach(e => video.removeEventListener(e, e === "loadedmetadata" ? relayout : kick));
      if (ro) ro.disconnect(); else window.removeEventListener("resize", relayout);
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
    },
  };
}
