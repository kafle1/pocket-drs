// PocketDRS website: same review flow and account rules as the Android app, for iPhone and other phones.
const FB = "https://www.gstatic.com/firebasejs/11.0.2/";
const $ = (id) => document.getElementById(id);
const show = (el, on) => { (typeof el === "string" ? $(el) : el).hidden = !on; };
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
const JOB_ERRORS = {
  JOB_TIMEOUT: "Checking this ball took too long. Trim the clip closer to the delivery and try again.",
  INVALID_VIDEO: "The server couldn't read this video. Try another clip.",
  VIDEO_DECODE_FAILED: "The server couldn't read this video. Try another clip.",
  CALIBRATION_DEGENERATE: "The stump marks don't line up. Mark the tops and bottoms of both sets of stumps again.",
  INTERNAL_ERROR: "Something went wrong checking this ball. Try again, or try another clip.",
};

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode: keep it for this visit only */ } },
};

const randomId = () => "web-" + Array.from(crypto.getRandomValues(new Uint8Array(16)), (x) => x.toString(16).padStart(2, "0")).join("");

function deviceId() {
  let id = store.get("pdrs_device");
  if (!id || !/^[A-Za-z0-9_-]{8,128}$/.test(id)) {
    id = randomId();
    store.set("pdrs_device", id);
  }
  return id;
}
const DEVICE = deviceId();
// google refuses sign-in inside instagram, facebook, messenger and other app browsers
const UA = navigator.userAgent;
// an iphone browser without "Safari/" in its name is a chat app's built-in view (gmail, viber, telegram)
const IN_APP = /FBAN|FBAV|FB_IAB|Instagram|Messenger|Line\/|; wv\)/.test(UA) || (/iPhone|iPad|iPod/.test(UA) && !/Safari\//.test(UA));
const OPEN_IN_BROWSER = "Open this page in Safari or Chrome to sign in.";

let auth, fbAuth, track = () => {}, me = null;

async function boot() {
  let cfg;
  try {
    const r = await fetch("/config.json", { cache: "no-store" });
    if (!r.ok) throw new Error("config " + r.status);
    cfg = await r.json();
  } catch {
    $("boot").textContent = "Sign-in isn't set up on this server yet. Try again later.";
    return;
  }
  const appMod = await import(FB + "firebase-app.js");
  fbAuth = await import(FB + "firebase-auth.js");
  const fbApp = appMod.initializeApp(cfg);
  auth = fbAuth.getAuth(fbApp);
  if (cfg.measurementId) {
    // analytics is optional, so a blocker or an old browser must not break the page
    try {
      const an = await import(FB + "firebase-analytics.js");
      if (await an.isSupported()) {
        const a = an.getAnalytics(fbApp);
        track = (name, params) => { try { an.logEvent(a, name, params); } catch { /* ignore */ } };
      }
    } catch { /* ignore */ }
  }
  let wasIn = false;
  fbAuth.onAuthStateChanged(auth, (user) => {
    // a fresh page is the only sure way to drop the last person's clip, result and admin lists
    if (!user && wasIn) { location.reload(); return; }
    wasIn = !!user;
    show("boot", false);
    if (user) { show("signin", false); show("app", true); loadMe(); }
    else {
      me = null; show("app", false); show("signin", true);
      if (IN_APP) { $("signin-error").textContent = OPEN_IN_BROWSER; show("signin-error", true); }
    }
  });
}

$("google").addEventListener("click", async () => {
  // started straight from the tap, so iOS Safari lets the popup open
  if (!auth) return;
  show("signin-error", false);
  const provider = new fbAuth.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    await fbAuth.signInWithPopup(auth, provider);
    track("login", { method: "google" });
  } catch (e) {
    const code = e && e.code;
    if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return;
    $("signin-error").textContent = ["auth/popup-blocked", "auth/operation-not-supported-in-this-environment", "auth/web-storage-unsupported"].includes(code)
      ? OPEN_IN_BROWSER
      : code === "auth/network-request-failed"
        ? "Can't reach Google. Check your internet and try again."
        : "Sign-in didn't work. Try again.";
    show("signin-error", true);
  }
});
$("signout").addEventListener("click", () => fbAuth.signOut(auth));

async function headers() {
  const user = auth.currentUser;
  if (!user) throw new Error("Sign in again to continue.");
  return { Authorization: "Bearer " + (await user.getIdToken()), "X-Device-Id": DEVICE };
}

// one fetch wrapper: plain sentences out, never status codes
async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, { ...opts, headers: { ...(opts.headers || {}), ...(await headers()) } });
  } catch (e) {
    throw new Error(e.message && e.message.startsWith("Sign in") ? e.message : "Can't reach the server. Check your internet and try again.");
  }
  let body = null;
  try { body = await r.json(); } catch { /* not json */ }
  if (r.ok) return body;
  if (r.status === 401) { fbAuth.signOut(auth); throw new Error("Please sign in again."); }
  if (r.status === 402) { usedUp(); throw new Error(""); }
  throw new Error(statusText(r.status, body));
}

function statusText(code, body) {
  if (code === 413) return "This clip is too big to send. Trim it shorter and try again.";
  if (code === 408) return "The upload took too long. Try again on a better connection.";
  if (code === 503) return "The server is busy. Try this ball again in a minute.";
  if (code === 404) return "This ball is no longer on the server. Send it again.";
  if (code === 403) return "Only the admin can do that.";
  if (code === 400 && body && typeof body.detail === "string") return body.detail;
  if (code === 400 && body && body.error === "device_id_required") return "This browser can't be recognised. Reload the page and try again.";
  return "Something went wrong on the server. Try again.";
}

async function loadMe() {
  try {
    me = await api("/v1/me");
  } catch (e) {
    if (e.message) showError(e.message);
    return;
  }
  $("who").textContent = "Signed in as " + me.email;
  show("admin-link", me.is_admin);
  const adminPage = location.pathname.replace(/\/+$/, "") === "/admin";
  show("review", !adminPage);
  show("admin", adminPage && me.is_admin);
  show("not-admin", adminPage && !me.is_admin);
  if (adminPage && me.is_admin) loadAdmin();
  renderQuota();
}

function freeLeft() {
  if (!me || me.plan !== "free") return null;
  return Math.max(0, Math.min(me.remaining ?? 0, me.device_remaining ?? 0));
}

function renderQuota() {
  const left = freeLeft();
  const q = $("quota");
  if (!me) { q.textContent = ""; return; }
  if (me.plan === "admin") q.textContent = "Admin, unlimited reviews";
  else if (me.plan === "premium") q.textContent = "Premium, unlimited reviews";
  else q.textContent = `${left} of ${me.free_limit} free reviews left`;
  const out = left === 0;
  show("used-up", out);
  $("used-up").querySelector("p").textContent =
    "No free reviews left on this account or this phone. Contact the admin for premium access.";
  $("contact").href = `mailto:${me.contact_email}?subject=PocketDRS%20premium`;
  $("go").disabled = out || marks.length !== 8 || !!checkMarks();
}

function usedUp() {
  track("trials_used_up");
  if (me && me.plan === "free") { me.remaining = 0; renderQuota(); }
  show("used-up", true);
  $("used-up").scrollIntoView({ behavior: "smooth", block: "center" });
}
$("contact").addEventListener("click", () => track("contact_admin_tapped"));

function showError(msg) { $("error").textContent = msg; show("error", !!msg); }

// review flow

// one retry key per clip and request, so sending the same ball again never costs a second free review
let sent = { body: null, key: null };
let hand = "right", file = null, videoUrl = null, startMs = null, endMs = null, marks = [], zoom = 1;
const video = $("video");

document.querySelectorAll("[data-hand]").forEach((b) => b.addEventListener("click", () => {
  hand = b.dataset.hand;
  document.querySelectorAll("[data-hand]").forEach((x) => x.classList.toggle("on", x === b));
}));
const savedPitch = parseFloat(store.get("pdrs_pitch"));
if (savedPitch >= 10 && savedPitch <= 25) $("pitch").value = savedPitch;
$("pitch").addEventListener("change", () => store.set("pdrs_pitch", $("pitch").value));

function step(name) {
  for (const s of ["pick", "mark", "run", "result"]) show("step-" + s, s === name);
}

for (const id of ["rec", "pick"]) {
  $(id).addEventListener("change", (ev) => {
    const f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    showError("");
    if (f.size > MAX_BYTES) { showError("This video is over 200 MB. Trim it on your phone first, then pick it again."); return; }
    file = f;
    sent = { body: null, key: null };
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    videoUrl = URL.createObjectURL(f);
    startMs = endMs = null; marks = [];
    video.src = videoUrl;
    video.load();
    setZoom(1);
    renderMarks(); renderSegment();
    step("mark");
  });
}

function duration() { return isFinite(video.duration) && video.duration > 0 ? video.duration : 0; }

video.addEventListener("loadedmetadata", () => {
  $("scrub").max = String(Math.max(1, Math.round(duration() * 1000)));
  // ios shows a black box until the video is seeked once
  try { video.currentTime = 0.001; } catch { /* ignore */ }
});
video.addEventListener("error", () => {
  if (file) showError("This browser can't play this video. Try another clip, or record a new one.");
});
video.addEventListener("timeupdate", () => {
  $("time").textContent = video.currentTime.toFixed(2) + " s";
  $("scrub").value = String(Math.round(video.currentTime * 1000));
});
$("scrub").addEventListener("input", () => { video.currentTime = Number($("scrub").value) / 1000; });
$("back").addEventListener("click", () => { video.currentTime = Math.max(0, video.currentTime - 1 / 30); });
$("fwd").addEventListener("click", () => { video.currentTime = Math.min(duration() || 1e9, video.currentTime + 1 / 30); });
$("set-start").addEventListener("click", () => { startMs = Math.round(video.currentTime * 1000); renderSegment(); });
$("set-end").addEventListener("click", () => { endMs = Math.round(video.currentTime * 1000); renderSegment(); });

function renderSegment() {
  const s = startMs ?? 0, e = endMs;
  const bad = e != null && e <= s;
  $("segment").textContent = startMs == null && endMs == null ? "Whole clip"
    : `From ${(s / 1000).toFixed(2)} s to ${e == null ? "the end" : (e / 1000).toFixed(2) + " s"}`
      + (bad ? ". The end must come after the start." : "");
  $("segment").classList.toggle("error", bad);
}

function setZoom(z) {
  zoom = z;
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
$("change").addEventListener("click", () => step("pick"));

function renderMarks() {
  const box = $("marks");
  box.replaceChildren(...marks.map((m, i) => {
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
  $("go").disabled = marks.length !== 8 || !!err || freeLeft() === 0;
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

$("go").addEventListener("click", run);
$("again").addEventListener("click", () => { marks = []; renderMarks(); step("pick"); });

function runText(title, text, pct) {
  $("run-title").textContent = title;
  $("run-text").textContent = text;
  $("bar").style.width = Math.max(0, Math.min(100, pct)) + "%";
}

async function run() {
  showError("");
  const s = startMs ?? 0, e = endMs ?? 600000;
  if (e <= s) { showError("The end of the clip must come after the start."); return; }
  const pitch = parseFloat($("pitch").value);
  if (!(pitch >= 10 && pitch <= 25)) { showError("Pitch length must be between 10 and 25 metres."); return; }
  const req = {
    segment: { start_ms: s, end_ms: e },
    calibration: { stump_quads_norm: marks, pitch_dimensions_m: { width: 3.05, length: pitch } },
    tracking: { sample_fps: 60, max_frames: 240 },
    batsman_handedness: hand,
  };
  step("run");
  runText("Sending the clip", "0%", 0);
  let jobId;
  try {
    jobId = await upload(req);
    track("analysis_started");
    const result = await poll(jobId);
    showResult(jobId, result);
  } catch (err) {
    if (err.jobFailed) track("analysis_failed");
    step("mark");
    if (err.message) showError(err.message);
  } finally {
    loadMeQuiet();
  }
}

async function loadMeQuiet() {
  try { me = await api("/v1/me"); renderQuota(); } catch { /* the next action shows any problem */ }
}

async function upload(req) {
  let h;
  try {
    h = await headers();
  } catch (e) {
    throw new Error(e.message && e.message.startsWith("Sign in") ? e.message : "Can't reach the server. Check your internet and try again.");
  }
  const body = JSON.stringify(req);
  if (sent.body !== body) sent = { body, key: randomId() };
  h["Idempotency-Key"] = sent.key;
  const form = new FormData();
  form.append("request_json", body);
  form.append("video_file", file, file.name || "video.mp4");
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/v1/jobs");
    for (const [k, v] of Object.entries(h)) x.setRequestHeader(k, v);
    x.timeout = 600000;
    x.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        const p = Math.round((ev.loaded / ev.total) * 100);
        runText("Sending the clip", p + "%", p);
      }
    };
    x.onload = () => {
      let body = null;
      try { body = JSON.parse(x.responseText); } catch { /* not json */ }
      if (x.status === 200 && body && body.job_id) return resolve(body.job_id);
      if (x.status === 401) { fbAuth.signOut(auth); return reject(new Error("Please sign in again.")); }
      if (x.status === 402) { usedUp(); return reject(new Error("")); }
      reject(new Error(statusText(x.status, body)));
    };
    x.onerror = () => reject(new Error("Can't reach the server. Check your internet and try again."));
    x.ontimeout = () => reject(new Error("The upload took too long. Try again on a better connection."));
    x.send(form);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function poll(jobId) {
  let misses = 0;
  for (;;) {
    let st;
    try {
      st = await api(`/v1/jobs/${jobId}`);
      misses = 0;
    } catch (e) {
      // a phone that drops signal for a moment should not lose the ball
      if (++misses > 5) throw e;
      await sleep(3000);
      continue;
    }
    const pct = (st.progress && st.progress.pct) || 0;
    const stage = (st.progress && st.progress.stage) || st.status;
    runText("Checking the ball", `${STAGES[stage] || "Working on your delivery"} (${pct}%)`, pct);
    if (st.status === "succeeded") return (await api(`/v1/jobs/${jobId}/result`)).result;
    if (st.status === "failed") {
      const err = st.error || {};
      const e = new Error(JOB_ERRORS[err.code] || (err.message && err.message.trim()) || "Could not check this ball. Try again.");
      e.jobFailed = true;
      throw e;
    }
    await sleep(2000);
  }
}

function showResult(jobId, result) {
  const lbw = (result && result.lbw) || null;
  const d = lbw && ["out", "not_out", "umpires_call"].includes(lbw.decision) ? lbw.decision : null;
  track("analysis_completed", { decision: d || "none" });
  $("verdict").className = "verdict " + (d || "");
  $("verdict").textContent = { out: "Out", not_out: "Not out", umpires_call: "Umpire's call" }[d] || "No decision";
  $("verdict-note").textContent = d === "umpires_call" ? "Too close to call, so the on-field umpire's decision stands."
    : d ? "" : "The app couldn't make a call on this ball. This is not a not out.";
  // like the app: with no call the server's first warning is the reason, with a call they follow it
  const warn = (result && result.diagnostics && result.diagnostics.warnings) || [];
  const lines = (d ? [lbw.reason, ...warn] : [warn[0] || "The ball's path couldn't be worked out well enough to make a call."])
    .filter(Boolean).map((l) => l[0].toUpperCase() + l.slice(1));
  $("reason").textContent = lines.join(". ");
  const c = (lbw && lbw.checks) || null;
  $("checks").replaceChildren(...(c ? [
    ["Pitched in line", c.pitching_in_line], ["Hit the pad in line", c.impact_in_line], ["Going on to hit the stumps", c.wickets_hitting],
  ].map(([t, ok]) => {
    const li = document.createElement("li");
    li.textContent = `${t}: ${ok ? "yes" : "no"}`;
    return li;
  }) : []));
  const has3d = !!(result && result.world_trajectory && (result.world_trajectory.points_m || []).length);
  show("three-d", has3d);
  $("three-d").href = `/v1/jobs/${jobId}/three-d`;
  step("result");
}

// admin

let searchTimer = null;
$("q").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadAdmin, 300); });
$("add").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const email = $("add-email").value.trim().toLowerCase();
  if (!email) return;
  if (await setUser(email, { plan: "premium" }, "grant_premium")) $("add-email").value = "";
});

function adminMsg(text) { $("admin-msg").textContent = text; show("admin-msg", !!text); }

async function setUser(email, body, action) {
  try {
    await api(`/v1/admin/users/${encodeURIComponent(email)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    track("admin_action", { action });
    adminMsg("Saved for " + email + ".");
    loadAdmin();
    return true;
  } catch (e) {
    adminMsg(e.message === "Something went wrong on the server. Try again." ? "That didn't save. Check the email and try again." : e.message);
    return false;
  }
}

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function btn(text, onClick, primary) {
  const b = el("button", text, primary ? "primary" : "");
  b.addEventListener("click", onClick);
  return b;
}
const day = (s) => (s ? new Date(s * 1000).toLocaleDateString() : "never");

async function loadAdmin() {
  const q = encodeURIComponent($("q").value.trim());
  let stats, users, devices;
  try {
    [stats, users, devices] = await Promise.all([
      api("/v1/admin/stats"), api(`/v1/admin/users?q=${q}`), api(`/v1/admin/devices?q=${q}`),
    ]);
  } catch (e) {
    adminMsg(e.message || "Couldn't load the admin data. Try again.");
    return;
  }
  $("stats").textContent = `${stats.users} people, ${stats.premium} premium. Reviews today ${stats.jobs_today}, `
    + `failed today ${stats.failed_today}, all time ${stats.jobs_total}.`;
  const limit = (me && me.free_limit) || 5;
  $("users").replaceChildren(...(users.users.length ? users.users.map((u) => {
    const li = el("li");
    li.append(el("strong", u.email), el("div", (u.name ? u.name + ". " : "")
      + (u.plan === "free" ? `Free, ${u.used} of ${limit} used` : u.plan === "premium" ? "Premium" : "Admin")
      + `. ${u.jobs} reviews. Last seen ${day(u.last_seen)}.`, "muted small"));
    if (u.plan !== "admin") {
      const row = el("div", null, "row");
      row.append(u.plan === "premium"
        ? btn("Make free", () => setUser(u.email, { plan: "free" }, "make_free"))
        : btn("Make premium", () => setUser(u.email, { plan: "premium" }, "make_premium"), true));
      row.append(btn("Reset free reviews", () => setUser(u.email, { reset_used: true }, "reset_user")));
      li.append(row);
    }
    return li;
  }) : [el("li", "Nobody matches.", "muted")]));
  $("devices").replaceChildren(...(devices.devices.length ? devices.devices.map((d) => {
    const li = el("li");
    li.append(el("strong", d.device_id.length > 20 ? d.device_id.slice(0, 20) + "..." : d.device_id),
      el("div", `${d.used} of ${limit} free used. Last used by ${d.last_email || "nobody"}, ${day(d.last_seen)}.`, "muted small"));
    const row = el("div", null, "row");
    row.append(btn("Reset", async () => {
      try {
        await api(`/v1/admin/devices/${encodeURIComponent(d.device_id)}/reset`, { method: "POST" });
        track("admin_action", { action: "reset_device" });
        adminMsg("Phone reset.");
        loadAdmin();
      } catch (e) { adminMsg(e.message); }
    }));
    li.append(row);
    return li;
  }) : [el("li", "No phones yet.", "muted")]));
}

boot().catch(() => { $("boot").textContent = "The page didn't load. Check your internet and reload."; });
