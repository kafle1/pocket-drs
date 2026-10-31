// pocket drs website: the same review flow and account rules as the android app, for iphone and any other phone
import { drawReplay } from "./replay.js";

const FB = "https://www.gstatic.com/firebasejs/11.0.2/";
const $ = (id) => document.getElementById(id);
const show = (id, on) => { $(id).hidden = !on; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MAX_BYTES = 200 * 1024 * 1024;
const LABELS = [
  "Batter's stumps, top left", "Batter's stumps, top right", "Batter's stumps, bottom right", "Batter's stumps, bottom left",
  "Bowler's stumps, top left", "Bowler's stumps, top right", "Bowler's stumps, bottom right", "Bowler's stumps, bottom left",
];
const STAGES = {
  queued: "Waiting in line", starting: "Loading the video", decode: "Reading frames from your clip",
  calibration: "Reading your stump marks", tracking: "Finding the ball in every frame",
  reconstruction: "Working out the ball's path", lbw: "Making the LBW call", finalize: "Finishing up",
};
const DECISIONS = { out: "Out", not_out: "Not out", umpires_call: "Umpire's call" };
// same sentences as the android app (pocket_drs_api.dart)
const OFFLINE = "Can't reach the server. Check your internet, or try again later.";
const SIGN_IN_AGAIN = "Please sign in again to keep going.";
// the server gives back the free review of a failed check or one with no call
const NOT_COUNTED = "This one didn't use up a free review.";
const JOB_ERRORS = {
  VIDEO_DECODE_FAILED: "The server couldn't read this video. Try another clip.",
  CALIBRATION_DEGENERATE: "The stump marks don't line up. Mark the tops and bottoms of both sets of stumps again.",
  INTERNAL_ERROR: "Something went wrong checking this ball. Try again, or try another clip.",
};
const ERRORS = {
  device_id_required: "This browser can't be recognised. Reload the page and try again.",
  bad_email: "That does not look like an email.",
  admin_plan_locked: "The admin's plan can't be changed.",
  not_found: "That phone is not on the list any more.",
};
const STATUS = {
  400: "The clip couldn't be sent. Pick it again and retry.",
  403: "Only the admin can do this.",
  404: "This ball is no longer on the server. Results are kept for 24 hours. Send it again.",
  408: "The upload took too long. Try again on a better connection.",
  413: "This clip is too big to send. Trim it shorter and try again.",
  502: "The server is off right now. Try again later.",
  503: "The server is busy. Try this ball again in a minute.",
  504: "No reply in time. Check your internet, or try again later.",
};

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode keeps it for this visit only */ } },
  del(k) { try { localStorage.removeItem(k); } catch { /* same */ } },
};
const randomId = () => "web-" + Array.from(crypto.getRandomValues(new Uint8Array(16)), (x) => x.toString(16).padStart(2, "0")).join("");
const DEVICE = /^[A-Za-z0-9_-]{8,128}$/.test(store.get("pdrs_device") || "") ? store.get("pdrs_device") : randomId();
store.set("pdrs_device", DEVICE);

// google refuses sign-in inside instagram, facebook and other app browsers; an iphone browser without "Safari/" is one too
const UA = navigator.userAgent;
const IN_APP = /FBAN|FBAV|FB_IAB|Instagram|Messenger|Line\/|; wv\)/.test(UA) || (/iPhone|iPad|iPod/.test(UA) && !/Safari\//.test(UA));

let auth, fa, me = null, track = () => {};

async function boot() {
  const r = await fetch("/config.json", { cache: "no-store" });
  if (!r.ok) { $("boot").textContent = "Sign-in isn't set up on this server yet. Try again later."; return; }
  const cfg = await r.json();
  const [fbApp, fbAuth] = await Promise.all([import(FB + "firebase-app.js"), import(FB + "firebase-auth.js")]);
  const app = fbApp.initializeApp(cfg);
  fa = fbAuth;
  auth = fa.getAuth(app);
  // a blocker or an old browser stopping analytics must not stop the page
  if (cfg.measurementId) import(FB + "firebase-analytics.js").then(async (an) => {
    if (!(await an.isSupported())) return;
    const a = an.getAnalytics(app);
    track = (name, params) => an.logEvent(a, name, params);
  }).catch(() => {});
  let wasIn = false;
  fa.onAuthStateChanged(auth, (user) => {
    // a fresh page is the only sure way to drop the last person's clip, result and admin lists
    if (!user && wasIn) { location.reload(); return; }
    wasIn = !!user;
    show("boot", false);
    show("signin", !user);
    show("app", !!user);
    if (user) loadMe();
  });
}
boot().catch(() => { $("boot").textContent = "The page didn't load. Check your internet and reload."; });

show("in-app", IN_APP);
$("copy-link").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(location.href);
    $("copy-link").textContent = "Link copied";
  } catch {
    $("copy-link").textContent = "Use the menu to open this page in a browser";
  }
});

$("google").addEventListener("click", async () => {
  // started straight from the tap with nothing awaited first, so ios safari lets the popup open
  show("signin-error", false);
  const provider = new fa.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    await fa.signInWithPopup(auth, provider);
    track("login", { method: "google" });
  } catch (e) {
    const code = e && e.code;
    if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return;
    $("signin-error").textContent = IN_APP || code === "auth/operation-not-supported-in-this-environment" || code === "auth/web-storage-unsupported"
      ? "Open this page in Safari or Chrome to sign in."
      : code === "auth/popup-blocked" ? "Your browser blocked the Google window. Allow pop-ups for this page and try again."
      : code === "auth/network-request-failed" ? "Can't reach Google. Check your internet and try again."
      : "Sign-in didn't work. Try again.";
    show("signin-error", true);
  }
});
$("signout").addEventListener("click", () => { store.del("pdrs_job"); fa.signOut(auth); });

// every request: plain sentences out, never status codes; e.transient marks the ones worth retrying
const offline = () => Object.assign(new Error(OFFLINE), { transient: true });

async function authHeaders() {
  const user = auth.currentUser;
  if (!user) throw new Error(SIGN_IN_AGAIN);
  // getIdToken refreshes an expired token, which needs the internet
  try { return { Authorization: "Bearer " + (await user.getIdToken()), "X-Device-Id": DEVICE }; } catch { throw offline(); }
}

function refuse(status, body) {
  if (status === 401) { fa.signOut(auth); throw new Error(SIGN_IN_AGAIN); }
  if (status === 402) { usedUp(); throw new Error(""); }
  const msg = ERRORS[body && body.error] || STATUS[status] || (status >= 500 ? "Something went wrong on the server. Try again." : "Got an unexpected reply from the server. Try again in a minute.");
  throw Object.assign(new Error(msg), { status, transient: status >= 502 && status <= 504 });
}

async function api(path, opts = {}) {
  const h = await authHeaders();
  let r;
  try { r = await fetch(path, { ...opts, headers: { ...opts.headers, ...h } }); } catch { throw offline(); }
  const body = await r.json().catch(() => null);
  if (r.ok) return body;
  refuse(r.status, body);
}

function showError(msg) {
  $("error").textContent = msg;
  show("error", !!msg);
  if (msg) $("error").scrollIntoView({ block: "center", behavior: "smooth" });
}

async function loadMe() {
  show("retry", false);
  try {
    me = await api("/v1/me");
  } catch (e) {
    showError(e.message);
    show("retry", !!e.message);
    return;
  }
  showError("");
  const adminPage = location.pathname.replace(/\/+$/, "") === "/admin";
  $("who").textContent = "Signed in as " + me.email;
  show("admin-link", me.is_admin && !adminPage);
  show("review", !adminPage);
  show("admin", adminPage && me.is_admin);
  show("not-admin", adminPage && !me.is_admin);
  renderQuota();
  if (adminPage && me.is_admin) { loadAdmin(); setInterval(() => document.hidden || loadJobs(), 20000); }
  if (!adminPage) resume();
}
$("retry").addEventListener("click", loadMe);

async function refreshMe() {
  try { me = await api("/v1/me"); renderQuota(); } catch { /* the next tap shows any problem */ }
}

const freeLeft = () => (me && !me.is_admin && me.remaining != null ? Math.max(0, Math.min(me.remaining, me.device_remaining)) : null);
let toldUsedUp = false;

function renderQuota() {
  const left = freeLeft();
  $("quota").textContent = me.is_admin ? "Admin, unlimited reviews"
    : left == null ? "Premium, unlimited reviews" : `${Math.min(left, me.free_limit)} of ${me.free_limit} free reviews left`;
  show("used-up", left === 0);
  if (left === 0 && !toldUsedUp) { toldUsedUp = true; track("trials_used_up"); }
  $("contact").href = `mailto:${me.contact_email}?subject=PocketDRS%20premium`;
  $("contact-email").textContent = me.contact_email;
  renderGo();
}

function usedUp() {
  if (!me) return;
  me.remaining = 0;
  renderQuota();
  $("used-up").scrollIntoView({ behavior: "smooth", block: "center" });
}
$("contact").addEventListener("click", () => track("contact_admin_tapped"));

// review flow

let hand = "right", file = null, videoUrl = null, replay = null, startMs = null, endMs = null, marks = [], busy = false;
// one retry key per clip and request, so sending the same ball again never costs a second free review
let sent = { body: null, file: null, key: null };
const video = $("video");

document.querySelectorAll("[data-hand]").forEach((b) => b.addEventListener("click", () => {
  hand = b.dataset.hand;
  document.querySelectorAll("[data-hand]").forEach((x) => x.classList.toggle("on", x === b));
}));
const savedPitch = parseFloat(store.get("pdrs_pitch"));
if (savedPitch >= 10 && savedPitch <= 25) $("pitch").value = savedPitch;
$("pitch").addEventListener("change", () => store.set("pdrs_pitch", $("pitch").value));

// the phone's back button steps back to picking a clip instead of leaving the page
function step(name) {
  for (const s of ["pick", "mark", "run", "result"]) show("step-" + s, s === name);
  if (name !== "result") $("replay-video").pause();
  if (name !== "pick" && !history.state) history.pushState({ review: true }, "");
}
const toPick = () => (history.state ? history.back() : step("pick"));
addEventListener("popstate", () => (busy ? history.pushState({ review: true }, "") : step("pick")));

for (const id of ["rec", "pick"]) {
  $(id).addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    showError("");
    if (f.type && !f.type.startsWith("video/")) { showError("That isn't a video. Pick a video clip."); return; }
    if (f.size > MAX_BYTES) { showError("This video is over 200 MB. Trim it on your phone first, then pick it again."); return; }
    file = f;
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    videoUrl = URL.createObjectURL(f);
    startMs = endMs = null;
    marks = [];
    video.src = videoUrl;
    video.load();
    setZoom(1);
    renderMarks();
    renderSegment();
    step("mark");
  });
}

const duration = () => (isFinite(video.duration) && video.duration > 0 ? video.duration : 0);
video.addEventListener("loadedmetadata", () => {
  $("scrub").max = String(Math.max(1, Math.round(duration() * 1000)));
  // ios shows a black box until the video is seeked once
  video.currentTime = 0.001;
});
video.addEventListener("error", () => file && showError("This browser can't play this video. Try another clip, or record a new one."));
video.addEventListener("timeupdate", () => {
  $("time").textContent = video.currentTime.toFixed(2) + " s";
  $("scrub").value = String(Math.round(video.currentTime * 1000));
});
$("scrub").addEventListener("input", () => { video.currentTime = Number($("scrub").value) / 1000; });
// one frame of the 60 fps clip people are asked to film
$("back").addEventListener("click", () => { video.currentTime = Math.max(0, video.currentTime - 1 / 60); });
$("fwd").addEventListener("click", () => { video.currentTime = Math.min(duration() || Infinity, video.currentTime + 1 / 60); });
$("set-start").addEventListener("click", () => { startMs = Math.round(video.currentTime * 1000); renderSegment(); });
$("set-end").addEventListener("click", () => { endMs = Math.round(video.currentTime * 1000); renderSegment(); });

function renderSegment() {
  const s = startMs ?? 0, e = endMs;
  const bad = e != null && e <= s;
  $("segment").textContent = startMs == null && endMs == null ? "Whole clip"
    : `From ${(s / 1000).toFixed(2)} s to ${e == null ? "the end" : (e / 1000).toFixed(2) + " s"}`
      + (bad ? ". The end must come after the start." : "");
  $("segment").classList.toggle("error", bad);
  renderGo();
}

function setZoom(z) {
  $("stage").style.width = z * 100 + "%";
  document.querySelectorAll("[data-z]").forEach((b) => b.classList.toggle("on", Number(b.dataset.z) === z));
}
document.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => setZoom(Number(b.dataset.z))));

$("marks").addEventListener("click", (ev) => {
  if (marks.length >= 8 || !video.videoWidth) return;
  const r = $("marks").getBoundingClientRect();
  const x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return;
  marks.push({ x: Math.round(x * 10000) / 10000, y: Math.round(y * 10000) / 10000 });
  renderMarks();
});
$("undo").addEventListener("click", () => { marks.pop(); renderMarks(); });
$("clear").addEventListener("click", () => { marks = []; renderMarks(); });
$("change").addEventListener("click", toPick);
$("again").addEventListener("click", toPick);
$("go").addEventListener("click", run);

function renderMarks() {
  $("marks").replaceChildren(...marks.map((m, i) => {
    const d = document.createElement("span");
    d.className = "mark" + (i >= 4 ? " bowler" : "");
    d.style.left = m.x * 100 + "%";
    d.style.top = m.y * 100 + "%";
    d.textContent = String(i + 1);
    return d;
  }));
  $("next-tap").textContent = marks.length < 8 ? `Tap ${marks.length + 1}: ${LABELS[marks.length]}` : "All marks placed";
  const err = checkMarks();
  $("mark-error").textContent = err || "";
  show("mark-error", !!err);
  renderGo();
}

function renderGo() {
  $("go").disabled = busy || marks.length !== 8 || !!checkMarks() || freeLeft() === 0 || (endMs != null && endMs <= (startMs ?? 0));
}

// same shape check as the app: tops above bottoms and lefts left of rights, for both sets
function checkMarks() {
  if (marks.length !== 8) return null;
  for (const [i, end] of [[0, "batter's"], [4, "bowler's"]]) {
    const [tl, tr, br, bl] = marks.slice(i, i + 4);
    if (tl.y + tr.y >= br.y + bl.y || tl.x + bl.x >= tr.x + br.x)
      return `For the ${end} stumps, tap top left, top right, bottom right, then bottom left.`;
  }
  return null;
}

function runText(title, text, pct) {
  $("run-title").textContent = title;
  $("run-text").textContent = text;
  if (pct != null) $("bar").style.transform = `scaleX(${Math.max(0, Math.min(100, pct)) / 100})`;
}

async function run() {
  if (busy) return;
  const pitch = parseFloat($("pitch").value);
  if (!(pitch >= 10 && pitch <= 25)) { showError("Pitch length must be between 10 and 25 metres."); return; }
  showError("");
  const req = {
    segment: { start_ms: startMs ?? 0, end_ms: endMs ?? 600000 },
    calibration: { stump_quads_norm: marks, pitch_dimensions_m: { width: 3.05, length: pitch } },
    tracking: { sample_fps: 60, max_frames: 240 },
    batsman_handedness: hand,
  };
  busy = true;
  step("run");
  runText("Sending the clip", "0%", 0);
  let jobId;
  try {
    jobId = await upload(req);
  } catch (e) {
    busy = false;
    step("mark");
    showError(e.message);
    refreshMe();
    return;
  }
  track("analysis_started");
  // ios safari often reloads a tab left in the background, so the ball must survive a reload
  store.set("pdrs_job", JSON.stringify({ id: jobId, at: Date.now() }));
  watch(jobId);
}

function resume() {
  let saved = null;
  try { saved = JSON.parse(store.get("pdrs_job")); } catch { /* nothing saved */ }
  if (saved && /^[a-f0-9]{32}$/.test(saved.id) && Date.now() - saved.at < 3600000) watch(saved.id);
  else store.del("pdrs_job");
}

async function watch(jobId) {
  busy = true;
  step("run");
  try {
    showResult(jobId, await poll(jobId));
  } catch (e) {
    if (e.jobFailed) track("analysis_failed");
    step(file ? "mark" : "pick");
    showError(e.message);
  } finally {
    busy = false;
    store.del("pdrs_job");
    refreshMe();
  }
}

async function upload(req) {
  const body = JSON.stringify(req);
  if (sent.body !== body || sent.file !== file) sent = { body, file, key: randomId() };
  for (let tries = 1; ; tries++) {
    try {
      return await send(body, sent.key);
    } catch (e) {
      // a full queue only answers once the whole clip is in, so sending it again just burns data
      if (!e.transient || e.status === 503 || tries === 3) throw e;
      runText("Sending the clip", "The connection dropped. Trying again.", 0);
      await sleep(3000);
    }
  }
}

async function send(body, key) {
  const h = { ...(await authHeaders()), "Idempotency-Key": key };
  const form = new FormData();
  form.append("request_json", body);
  form.append("video_file", file, file.name || "clip.mp4");
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/v1/jobs");
    for (const k in h) x.setRequestHeader(k, h[k]);
    x.timeout = 600000;
    x.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      const p = Math.round((ev.loaded / ev.total) * 100);
      runText("Sending the clip", p < 100 ? p + "%" : "Sent. Starting the check.", p);
    };
    x.onload = () => {
      let res = null;
      try { res = JSON.parse(x.responseText); } catch { /* not json */ }
      if (x.status === 200 && res && res.job_id) return resolve(res.job_id);
      try { refuse(x.status, res); } catch (e) { reject(e); }
    };
    x.onerror = () => reject(offline());
    x.ontimeout = () => reject(new Error(STATUS[408]));
    x.send(form);
  });
}

// a phone that loses signal for a few minutes must not lose the ball
async function patient(path) {
  for (let misses = 0; ; misses++) {
    try {
      return await api(path);
    } catch (e) {
      if (!e.transient || misses === 200) throw e;
      runText("Checking the ball", "No connection. Waiting for it to come back.");
      await sleep(3000);
    }
  }
}

async function poll(jobId) {
  for (;;) {
    const st = await patient(`/v1/jobs/${jobId}`);
    const pct = (st.progress && st.progress.pct) || 0;
    const stage = (st.progress && st.progress.stage) || st.status;
    runText("Checking the ball", `${STAGES[stage] || "Working on your delivery"} (${pct}%)`, pct);
    if (st.status === "succeeded") return (await patient(`/v1/jobs/${jobId}/result`)).result;
    if (st.status === "failed") {
      const err = st.error || {};
      throw Object.assign(new Error(`${JOB_ERRORS[err.code] || JOB_ERRORS.INTERNAL_ERROR} ${NOT_COUNTED}`), { jobFailed: true });
    }
    await sleep(2000);
  }
}

function showResult(jobId, result) {
  const lbw = (result && result.lbw) || null;
  const d = lbw && DECISIONS[lbw.decision] ? lbw.decision : null;
  track("analysis_completed", { decision: d || "none" });
  $("verdict").className = "verdict " + (d || "");
  $("verdict").textContent = DECISIONS[d] || "No call";
  $("verdict-note").textContent = d === "umpires_call" ? "Too close to call, so the on-field umpire's decision stands."
    : d ? "" : `The app couldn't make a call on this ball. This is not a not out. ${NOT_COUNTED}`;
  // like the app: with no call the server's first warning is the reason, with a call they follow it
  const warn = (result && result.diagnostics && result.diagnostics.warnings) || [];
  const lines = d ? [lbw.reason, ...warn] : [warn[0] || "The ball's path couldn't be worked out well enough to make a call."];
  $("reason").textContent = lines.filter(Boolean).map((l) => l[0].toUpperCase() + l.slice(1)).join(". ");
  const c = lbw && lbw.checks;
  $("checks").replaceChildren(...(c ? [
    // pitching_in_line means "not outside leg": outside off still counts, as on the 3D page
    ["Pitched outside leg", !c.pitching_in_line], ["Hit the pad in line", c.impact_in_line], ["Going on to hit the stumps", c.wickets_hitting],
  ].map(([t, yes]) => {
    const li = el("li");
    li.append(el("span", t), el("span", yes ? "yes" : "no", "check " + (yes ? "yes" : "no")));
    return li;
  }) : []));
  show("three-d", !!(result && result.world_trajectory && (result.world_trajectory.points_m || []).length));
  $("three-d").href = `/v1/jobs/${jobId}/three-d`;
  // after a reload the clip is gone, so the replay only shows for a ball picked in this tab
  if (replay) replay.destroy();
  const v = $("replay-video"), on = !!(videoUrl && result && result.overlay && (result.overlay.path_px || []).length);
  show("replay", on);
  if (on) v.src = `${videoUrl}#t=${(startMs || 0) / 1000}`;
  replay = on ? drawReplay($("replay-canvas"), v, result) : null;
  step("result");
}

// admin

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function btn(text, onClick, cls) {
  const b = el("button", text, cls);
  b.addEventListener("click", () => onClick(b));
  return b;
}
const plural = (k, one, many = one + "s") => `${k} ${k === 1 ? one : many}`;
function when(s) {
  const d = new Date(s * 1000);
  return d.toDateString() === new Date().toDateString()
    ? "today " + d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}
const phone = (id) => (id.startsWith("web-") ? "Browser " + id.slice(4, 12) : "Phone " + id.slice(0, 8));
function fill(id, items, empty, render) {
  $(id).replaceChildren(...(items.length ? items.map(render) : [el("li", empty, "muted")]));
}

let toastTimer = null;
function toast(text) {
  $("toast").textContent = text;
  show("toast", !!text);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => show("toast", false), 4000);
}

// the button stays off while its request runs, so a double tap can't send it twice
async function act(b, action, call, done) {
  b.disabled = true;
  try {
    await call();
    track("admin_action", { action });
    toast(done);
    loadAdmin();
  } catch (e) {
    toast(e.message);
    b.disabled = false;
  }
}
const setUser = (email, body) => () => api(`/v1/admin/users/${encodeURIComponent(email)}`, {
  method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

let searchTimer = null;
$("q").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadAdmin, 300); });
$("add").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const email = $("add-email").value.trim().toLowerCase();
  act($("add-btn"), "add_premium", async () => { await setUser(email, { plan: "premium" })(); $("add-email").value = ""; },
    `${email} is premium now, and keeps it when they first sign in.`);
});
$("jobs-all").addEventListener("click", () => { jobsEmail = ""; loadJobs(); });

let adminSeq = 0, jobsSeq = 0, jobsEmail = "";

// a slow reply to an older search must not overwrite a newer one
async function loadAdmin() {
  const seq = ++adminSeq, q = encodeURIComponent($("q").value.trim());
  loadJobs();
  let stats, users, devices;
  try {
    [stats, { users }, { devices }] = await Promise.all([
      api("/v1/admin/stats"), api(`/v1/admin/users?q=${q}`), api(`/v1/admin/devices?q=${q}`),
    ]);
  } catch (e) {
    if (seq === adminSeq) toast(e.message);
    return;
  }
  if (seq !== adminSeq) return;
  $("stats").textContent = `${plural(stats.users, "person", "people")}, ${stats.premium} premium. `
    + `${plural(stats.jobs_today, "review")} today (${stats.failed_today} failed), ${stats.jobs_total} in all.`;
  const limit = me.free_limit;
  fill("users", users, "No one found.", (u) => {
    const li = el("li");
    const plan = u.plan === "free" ? `Free, ${u.used} of ${limit} used` : u.plan === "premium" ? "Premium" : "Admin";
    const seen = !u.name && !u.jobs ? "Not signed in yet" : "Last seen " + when(u.last_seen);
    const info = el("div", null, "info");
    info.append(el("strong", u.email), el("div", `${u.name ? u.name + ". " : ""}${plan}. ${plural(u.jobs, "review")}. ${seen}.`, "muted small"));
    li.append(info);
    const row = el("div", null, "row");
    if (u.plan !== "admin") row.append(
      u.plan === "premium"
        ? btn("Make free", (b) => act(b, "make_free", setUser(u.email, { plan: "free" }), `${u.email} is on the free plan now.`))
        : btn("Make premium", (b) => act(b, "make_premium", setUser(u.email, { plan: "premium" }), `${u.email} is premium now.`), "primary"),
      btn("Reset free reviews", (b) => act(b, "reset_used", setUser(u.email, { reset_used: true }), `Free reviews reset for ${u.email}.`)),
    );
    row.append(btn("See reviews", () => {
      jobsEmail = u.email;
      loadJobs();
      $("jobs-title").scrollIntoView({ behavior: "smooth" });
    }));
    li.append(row);
    return li;
  });
  fill("devices", devices, "No phones found.", (d) => {
    const li = el("li");
    const info = el("div", null, "info");
    info.append(el("strong", d.last_email || "Phone not signed in yet"),
      el("div", `${d.used} of ${limit} free used. ${phone(d.device_id)}. Last seen ${when(d.last_seen)}.`, "muted small"));
    li.append(info);
    const row = el("div", null, "row");
    row.append(btn("Reset", (b) => act(b, "reset_device",
      () => api(`/v1/admin/devices/${encodeURIComponent(d.device_id)}/reset`, { method: "POST" }), "Phone reset.")));
    li.append(row);
    return li;
  });
}

function jobWord(j) {
  if (j.status === "failed") return ["Failed", "failed"];
  if (j.status !== "succeeded") return ["Checking", ""];
  return DECISIONS[j.decision] ? [DECISIONS[j.decision], j.decision] : ["No call", ""];
}

async function loadJobs() {
  const seq = ++jobsSeq;
  $("jobs-title").textContent = jobsEmail ? "Reviews by " + jobsEmail : "Recent reviews";
  show("jobs-all", !!jobsEmail);
  let jobs;
  try {
    ({ jobs } = await api(`/v1/admin/jobs?email=${encodeURIComponent(jobsEmail)}`));
  } catch (e) {
    if (seq === jobsSeq) fill("jobs", [], e.message);
    return;
  }
  if (seq !== jobsSeq) return;
  fill("jobs", jobs, "No reviews yet.", (j) => {
    const [word, cls] = jobWord(j);
    const li = el("li");
    li.append(el("span", word, "pill " + cls), el("strong", j.email, "who"),
      el("span", `${j.device_id ? phone(j.device_id) + " · " : ""}${when(j.created_at)}`, "muted small meta"));
    return li;
  });
}
