// The retro broadcast, live: the same picture as the replay videos (games/afl8/render/replay.py), drawn in the browser
// at 60 frames a second. A scoreboard across the top, a coach panel each side (pixel portrait that talks when a new
// plan comes in, the plan, the energy bars), the oval in the tilted 16-bit perspective with its pixel crowd, sprite
// players that scale with depth, labelled (1m, 5d...), the red ball spinning on its arc, the dashed line of a kick,
// the ticker and possession chain underneath. A goal freezes the picture for the celebration, as in the videos.
// The data and the sprites come from the server (/api/analysis/{match}/broadcast), made by the replay's own code.
// "🎬 Make video" renders frame by frame at 30 fps, 1280x720, through the 3D view's encoder.
import { get, post } from "../api.js";
import { h, toast } from "../ui.js";

const FW = 1280, FH = 720, PT = 100 / 72;                                   // the videos are 12.8 x 7.2 in at 100 dpi
const MONO = '"DejaVu Sans Mono", Consolas, "Courier New", monospace';
const LED = "#ffd600", BG = "#101018";
const box = (x0, y0, x1, y1) => ({ x0, y0, x1, y1 });
const GROUND = box(0.19 * FW, FH * 0.13, 0.81 * FW, FH * (1 - 0.075));     // matplotlib's axes, in canvas pixels
const LEFT = box(0, GROUND.y0, 0.19 * FW, GROUND.y1), RIGHT = box(0.81 * FW, GROUND.y0, FW, GROUND.y1);
const TOP = box(0, 0, FW, FH * 0.13), BOTTOM = box(0.19 * FW, GROUND.y1, 0.81 * FW, FH);
const at = (b, u, v) => [b.x0 + u * (b.x1 - b.x0), b.y1 - v * (b.y1 - b.y0)];   // axes fractions -> canvas
const HOLD = { goal: 2.5, behind: 1.0, fulltime: 3.0 };                       // seconds the picture freezes (as the videos)
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const fmtScore = (gb) => `${gb[0]}.${gb[1]} (${6 * gb[0] + gb[1]})`;
const fmtClock = (t) => `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;

function wrap(text, width) {                                                // textwrap.fill
  const out = []; let line = "";
  for (const w of String(text || "").split(/\s+/).filter(Boolean)) {
    if ((line + " " + w).trim().length > width && line) { out.push(line); line = w; } else line = (line + " " + w).trim();
  }
  if (line) out.push(line);
  return out;
}

// ------------------------------------------------------------------ the 16-bit camera (replay.Camera, framed as animate() frames it)
class Camera {
  constructor(g, view = 60) {
    this.k = 0.6; this.cx = g.length / 2; this.w = g.width + 6; this.L = g.length; this.V = view;
    const pw = GROUND.x1 - GROUND.x0, ph = GROUND.y1 - GROUND.y0, yrange = (view * ph) / pw;
    this.H = 0.8 * yrange; this.ylo = -this.H / 2 - 2; this.ppm = pw / view; this.pan = this.cx;
  }
  depth(y) { return clamp((y + this.w / 2) / this.w, 0, 1); }
  scale(y) { return 1 / (1 + this.k * this.depth(y)); }
  proj(x, y) {
    const s = this.scale(y), d = this.depth(y);
    return [this.cx + (x - this.cx) * s, -this.H / 2 + (this.H * (1 - 1 / (1 + this.k * d))) / (1 - 1 / (1 + this.k))];
  }
  sx(X) { return GROUND.x0 + (X - (this.pan - this.V / 2)) * this.ppm; }
  sy(Y) { return GROUND.y1 - (Y - this.ylo) * this.ppm; }
  screen(x, y) { const [X, Y] = this.proj(x, y); return [this.sx(X), this.sy(Y)]; }
  target(bx, by) { return clamp(this.proj(bx, by)[0], this.V / 2 - 14, this.L - this.V / 2 + 14); }
}

// ------------------------------------------------------------------ chiptune sound (WebAudio, no files)
class Chip {
  constructor() { this.on = true; this.ctx = null; }
  init() {
    if (this.ctx) return;
    try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch { this.ctx = null; return; }
    this.master = this.ctx.createGain(); this.master.gain.value = 0.35; this.master.connect(this.ctx.destination);
    const len = this.ctx.sampleRate * 2, buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate), ch = buf.getChannelData(0);
    for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
    this.noise = buf;
  }
  tone(freq, dur, type = "square", vol = 0.25, slide = 0) {
    if (!this.on || !this.ctx) return;
    const t = this.ctx.currentTime, o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t); if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), t + dur);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(this.master); o.start(t); o.stop(t + dur + 0.02);
  }
  burst(dur, vol, freq) {
    if (!this.on || !this.ctx) return;
    const t = this.ctx.currentTime, s = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    s.buffer = this.noise; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = 0.6;
    g.gain.setValueAtTime(0.001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.25); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f); f.connect(g); g.connect(this.master); s.start(t); s.stop(t + dur + 0.05);
  }
  play(kind) {
    if (kind === "kick") { this.tone(160, 0.12, "triangle", 0.45, -100); this.tone(900, 0.03, "square", 0.08); }
    else if (kind === "handball") this.tone(520, 0.06, "square", 0.15, -200);
    else if (kind === "mark") { this.tone(330, 0.07, "square", 0.18); setTimeout(() => this.tone(495, 0.1, "square", 0.18), 70); }
    else if (kind === "spoil") this.tone(220, 0.08, "sawtooth", 0.16, -120);
    else if (kind === "tackle") this.tone(110, 0.15, "sawtooth", 0.2, -60);
    else if (kind === "goal") { this.burst(2.2, 0.5, 900); [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => this.tone(f, 0.16, "square", 0.2), i * 110)); }
    else if (kind === "behind") { this.burst(1.0, 0.2, 700); this.tone(392, 0.2, "square", 0.15); }
    else if (kind === "siren") this.tone(620, 1.6, "square", 0.22, 40);
  }
}

// ------------------------------------------------------------------ adapters: a stored match, or a sandbox play-out
export async function openMatch(matchId, opts = {}) {
  const d = await get(`/api/analysis/${matchId}/broadcast`);
  return new ViewSNES(d, { recordName: String(matchId), ...opts });
}

export async function openPlayout(frames, players, ground, events, opts = {}) {
  const sp = await get("/api/analysis/sprites");
  const pids = Object.keys(players).sort((a, b) => a[0].localeCompare(b[0]) || +a.slice(1) - +b.slice(1));
  const L = ground.length, cs = ground.centre_square, gh = ground.goal_half_width, gd = ground.goal_square_depth;
  const fr = frames.map((f) => {
    const b = f.ball || {};
    return { t: f.t, p: pids.flatMap((pid) => (f.players[pid] ? f.players[pid].pos : [0, 0])), b: [b.pos[0], b.pos[1]], h: b.height || 0,
      s: (b.height || 0) > 0.3 ? "flight" : (b.holder ? "held" : "loose"), ho: b.holder || null, l: null, pr: 0, mm: null,
      e: f.players[pids[0]] && f.players[pids[0]].energy !== undefined ? pids.map((pid) => f.players[pid].energy) : null, sc: f.score ? [f.score.A, f.score.B] : [0, 0] };
  });
  const scores = [[-1, { A: [0, 0], B: [0, 0] }]], scoring = []; const tally = { A: [0, 0], B: [0, 0] }; let prev = fr.length ? fr[0].sc : [0, 0];
  for (const f of fr) {
    ["A", "B"].forEach((tm, k) => { let dl = f.sc[k] - prev[k];
      while (dl >= 6) { tally[tm][0]++; dl -= 6; scoring.push([f.t, tm, "goal"]); scores.push([f.t, { A: [...tally.A], B: [...tally.B] }]); }
      while (dl >= 1) { tally[tm][1]++; dl -= 1; scoring.push([f.t, tm, "behind"]); scores.push([f.t, { A: [...tally.A], B: [...tally.B] }]); } });
    prev = f.sc;
  }
  const roles = Object.fromEntries(pids.map((p) => [p, players[p].role || ""]));
  const d = { names: { A: "RED", B: "BLUE" }, pids, roles, tags: Object.fromEntries(pids.map((p) => [p, p.slice(1) + (roles[p] || "").slice(0, 1)])),
    ground: { length: L, width: ground.width, outline: ground.outline, centre_circle: [L / 2, 0, ground.centre_circle_radius], centre_square: [L / 2 - cs / 2, -cs / 2, cs, cs],
      goal_squares: [[0, -gh, gd, 2 * gh], [L - gd, -gh, gd, 2 * gh]], arc_radius: ground.arc_radius, goal_half_width: gh, behind_half_width: ground.behind_half_width },
    frames: fr, scores, scoring, plans: { A: [], B: [] }, chains: [[-1, null, ""]], ticker: (events || []).filter((e) => e.text).map((e) => [e.t, e.text]),
    actions: (events || []).filter((e) => ["kick", "handball", "mark", "spoil", "tackle"].includes(e.type)).map((e) => [e.t, e.type, e.by]),
    sprites: sp, duration: fr.length ? fr[fr.length - 1].t : 0 };
  return new ViewSNES(d, opts);
}

// a game you play yourself: the server runs it in real time, the browser ticks it 20 times a second
export async function openLive(params, opts = {}) {
  const s = await post("/api/live/start", params);
  const d = { names: s.names, pids: s.pids, roles: s.roles, tags: s.tags, ground: s.ground, sprites: s.sprites, frames: [],
    scores: [[-1, { A: [0, 0], B: [0, 0] }]], scoring: [], plans: { A: [], B: [] }, chains: [[-1, null, ""]], ticker: [], actions: [], duration: s.seconds };
  return new ViewSNES(d, { ...opts, live: { sid: s.sid, window: s.window, human: s.human, params }, recordName: "live_v_" + String(s.opponent).split("/").pop().replace("zoo:", "") });
}

// ------------------------------------------------------------------ the viewer
export class ViewSNES {
  // opts: { t, recordName, onClose(t), view }
  constructor(d, opts = {}) {
    this.d = d; this.opts = opts; this.g = d.ground; this.cam = new Camera(this.g, opts.view || 60);
    this.t0 = d.frames.length ? d.frames[0].t : 0; this.t1 = d.frames.length ? d.frames[d.frames.length - 1].t : 0;
    this.t = clamp(opts.t ?? this.t0, this.t0, this.t1); this.lastT = this.t;
    this.playing = false; this.speed = 1; this.hold = null; this.chip = new Chip();
    this.img = {}; this.loaded = this.loadSprites();
    this.idx = Object.fromEntries(d.pids.map((p, i) => [p, i]));
    const f = this.frameAt(this.t); if (f) this.cam.pan = this.cam.target(f.b[0], f.b[1]);
    this.live = opts.live || null;
    if (this.live) {
      this.keys = new Set(); this.presses = []; this.control = {}; this.notes = []; this.seq = -1; this.ev = 0; this.charge = null; this.finished = false;
    }
    this.build(); this.alive = true; this.last = performance.now();
    window.aflSnes = this;
    this.loaded.then(() => { requestAnimationFrame((n) => this.loop(n)); if (this.live) this.pollTimer = setInterval(() => this.poll(), 33); });
  }

  loadSprites() {
    const s = this.d.sprites, jobs = [];
    const load = (key, src) => jobs.push(new Promise((ok) => { const im = new Image(); im.onload = () => ok(); im.onerror = () => ok(); im.src = src; this.img[key] = im; }));
    for (const t of ["A", "B"]) for (const [k, src] of Object.entries(s.players[t])) load(`p${t}_${k}`, src);
    s.ball.forEach((src, i) => load(`ball${i}`, src));
    for (const t of ["A", "B"]) s.coach[t].forEach((src, i) => load(`coach${t}${i}`, src));
    load("crowd", s.crowd); load("crowdBright", s.crowd_bright);
    return Promise.all(jobs);
  }

  build() {
    this.canvas = h("canvas.snes-canvas", { width: FW, height: FH });
    this.x = this.canvas.getContext("2d");
    this.stage = h("div.snes-stage", this.canvas);
    this.playBtn = h("button.btn.small", { onclick: () => this.toggle() }, "▶");
    this.scrub = h("input", { type: "range", min: this.t0, max: this.t1, step: 0.1, value: this.t, style: { flex: 1 }, oninput: (e) => { this.t = +e.target.value; this.lastT = this.t; this.hold = null; } });
    const speed = h("select", { onchange: (e) => { this.speed = +e.target.value; } }, [0.5, 1, 2, 4].map((s) => h("option", { value: s, selected: s === 1 }, s + "×")));
    const sound = h("button.btn.small.ghost", { title: "sound", onclick: () => { this.chip.init(); this.chip.on = !this.chip.on; sound.textContent = this.chip.on ? "🔊" : "🔇"; } }, "🔊");
    this.recBtn = h("button.btn.small", { onclick: () => { if (this.live) { this.t = this.t0; this.hold = null; } this.makeVideo(); }, title: "render from here to the end as an mp4 (30 fps, 1280x720), like the replay videos" }, "🎬 Make video");
    const bar = this.live
      ? h("div.v3d-bar", this.again = h("button.btn.small.red.hidden", { onclick: () => { this.close(); openLive(this.live.params, { ...this.opts, live: null }); } }, "↻ Play again"),
          sound, this.recBtn, h("span.muted", { style: { fontSize: "12px" } },
            "Arrows/WASD run · Shift sprint · Space: kick (hold for power, let go before the red) / leap for a mark (when the ring turns green) / gather / tackle · J handball · L spoil · Q switch player (Q+arrow: that way) · Esc quit"))
      : h("div.v3d-bar", this.playBtn, speed, this.scrub, sound, this.recBtn, h("span.muted", { style: { fontSize: "12px" } }, "Space play/pause · ← → 5 s"));
    if (this.live) this.recBtn.classList.add("hidden");
    this.el = h("div.v3d.snes", this.stage, h("button.v3d-close", { onclick: () => this.close(), title: "close (Esc)" }, "×"), bar);
    document.body.appendChild(this.el);
    this.onKeyUp = (e) => { if (this.live) this.liveKey(e, false); };
    window.addEventListener("keyup", this.onKeyUp);
    this.onKey = (e) => {
      if (this.live) { if (e.key === "Escape") this.close(); else this.liveKey(e, true); return; }
      if (e.key === "Escape") this.close();
      else if (e.key === " ") { e.preventDefault(); this.toggle(); }
      else if (e.key === "ArrowRight") { this.t = Math.min(this.t1, this.t + 5); this.lastT = this.t; this.hold = null; }
      else if (e.key === "ArrowLeft") { this.t = Math.max(this.t0, this.t - 5); this.lastT = this.t; this.hold = null; }
    };
    window.addEventListener("keydown", this.onKey);
    this.onResize = () => this.fit(); window.addEventListener("resize", this.onResize); this.fit();
  }
  fit() {
    const r = this.stage.getBoundingClientRect(), k = Math.min(r.width / FW, r.height / FH);
    this.canvas.style.width = FW * k + "px"; this.canvas.style.height = FH * k + "px";
  }
  toggle() { this.chip.init(); this.playing = !this.playing; if (this.t >= this.t1 - 0.05) { this.t = this.t0; this.hold = null; } this.playBtn.textContent = this.playing ? "⏸" : "▶"; }
  close() {
    this.alive = false; if (this.making) this.making.cancel = true;
    window.removeEventListener("keydown", this.onKey); window.removeEventListener("keyup", this.onKeyUp); window.removeEventListener("resize", this.onResize);
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.live && !this.finished) fetch(`/api/live/${this.live.sid}/stop`, { method: "POST" });
    if (this.chip.ctx) this.chip.ctx.close();
    this.el.remove(); if (this.opts.onClose) this.opts.onClose(this.t);
  }

  // ---- data
  frameIndex(t) { const fr = this.d.frames; let lo = 0, hi = fr.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (fr[m].t <= t) lo = m; else hi = m - 1; } return lo; }
  frameAt(t) { return this.d.frames.length ? this.d.frames[this.frameIndex(t)] : null; }
  sample(t) {                                                               // positions eased between the 10-per-second frames
    const fr = this.d.frames, i = this.frameIndex(t), a = fr[i], b = fr[Math.min(i + 1, fr.length - 1)];
    const u = b.t > a.t ? clamp((t - a.t) / (b.t - a.t), 0, 1) : 0, lerp = (p, q) => p + (q - p) * u;
    return { a, p: a.p.map((v, k) => lerp(v, b.p[k] ?? v)), b: [lerp(a.b[0], b.b[0]), lerp(a.b[1], b.b[1])], h: lerp(a.h || 0, b.h || 0), i };
  }
  gameEnd() { const fr = this.d.frames; return fr.length ? fr[fr.length - 1].t : 0; }   // full time only at the real end
  latest(list, t) { let cur = null; for (const e of list) { if (e[0] <= t + 1e-9) cur = e; else break; } return cur; }
  scoreAt(t) { const s = this.latest(this.d.scores, t); return s ? s[1] : { A: [0, 0], B: [0, 0] }; }

  // ---- the loop: time runs, holds freeze it after a score and at full time
  loop(now) {
    if (!this.alive) return;
    const dt = Math.min(0.1, (now - this.last) / 1000); this.last = now;
    if (this.live && !this.making) {
      const fr = this.d.frames;
      if (this.hold && this.hold.kind !== "fulltime") { this.hold.left -= dt; if (this.hold.left <= 0) this.hold = null; }
      if (fr.length) this.t = Math.max(fr[0].t, fr[fr.length - 1].t - 0.04);          // just behind the newest frame
      if (this.charge) this.charge.power = Math.min(1.25, (performance.now() - this.charge.t0) / 1100);
      if (!fr.length) { this.waiting(this.x); requestAnimationFrame((n) => this.loop(n)); return; }
    } else if (this.playing && !this.making) this.advance(dt);
    if (!this.making) this.draw(this.x, this.t, dt, now / 1000);
    requestAnimationFrame((n) => this.loop(n));
  }
  advance(dt) {
    if (this.hold) {
      this.hold.left -= dt; if (this.hold.left > 0) return;
      if (this.hold.kind === "fulltime") { this.playing = false; this.playBtn.textContent = "▶"; return; }
      this.hold = null;
    }
    const t0 = this.t, t1 = Math.min(this.t1, this.t + dt * this.speed);
    const sc = this.d.scoring.find((s) => s[0] > t0 + 1e-6 && s[0] <= t1);
    this.t = sc ? sc[0] : t1;
    if (this.speed <= 2) { for (const a of this.d.actions) if (a[0] > t0 && a[0] <= this.t) this.chip.play(a[1]); }
    if (sc) { this.hold = { kind: sc[2], team: sc[1], left: HOLD[sc[2]] || 1, n: HOLD[sc[2]] || 1, t: sc[0] }; this.chip.play(sc[2]); }
    else if (this.t >= this.t1 - 1e-6) { this.hold = { kind: "fulltime", left: HOLD.fulltime, n: HOLD.fulltime }; this.chip.play("siren"); }
    this.scrub.value = this.t;
  }

  // ---- drawing (one frame)
  draw(x, t, dt, clock) {
    const s = this.sample(t), d = this.d, cam = this.cam, g = this.g;
    if (!this.hold) cam.pan += (cam.target(s.b[0], s.b[1]) - cam.pan) * (1 - Math.pow(0.88, (dt * this.speed) / 0.1));   // replay: 12 % a frame
    x.save(); x.fillStyle = BG; x.fillRect(0, 0, FW, FH);
    // the ground panel: crowd, oval, stripes, lines, posts
    x.save(); x.beginPath(); x.rect(GROUND.x0, GROUND.y0, GROUND.x1 - GROUND.x0, GROUND.y1 - GROUND.y0); x.clip();
    const bright = this.hold && this.hold.kind === "goal" && Math.floor(clock / 0.15) % 2 === 0;
    x.imageSmoothingEnabled = false;
    const cx0 = cam.sx(-206), cx1 = cam.sx(g.length + 206);
    x.drawImage(this.img[bright ? "crowdBright" : "crowd"], cx0, GROUND.y0, cx1 - cx0, GROUND.y1 - GROUND.y0);
    const oval = new Path2D(); g.outline.forEach(([px, py], i) => { const [X, Y] = cam.screen(px, py); i ? oval.lineTo(X, Y) : oval.moveTo(X, Y); }); oval.closePath();
    x.fillStyle = "#34823c"; x.fill(oval);
    x.save(); x.clip(oval);
    for (let i = 0, x0 = -5; x0 < g.length + 5; i++, x0 += 10) {
      const pts = [[x0, -cam.w / 2], [x0 + 10, -cam.w / 2], [x0 + 10, cam.w / 2], [x0, cam.w / 2]].map(([a, b]) => cam.screen(a, b));
      x.fillStyle = i % 2 ? "#2c7434" : "#3a8a42"; x.beginPath(); pts.forEach(([X, Y], k) => (k ? x.lineTo(X, Y) : x.moveTo(X, Y))); x.closePath(); x.fill();
    }
    x.restore();
    x.lineJoin = "round"; x.strokeStyle = "#ffffff";
    x.lineWidth = 3 * PT; x.stroke(oval);
    const poly = (pts, lw) => { x.lineWidth = lw; x.beginPath(); pts.forEach(([a, b], k) => { const [X, Y] = cam.screen(a, b); k ? x.lineTo(X, Y) : x.moveTo(X, Y); }); x.stroke(); };
    const [ccx, ccy, rad] = g.centre_circle;
    poly(Array.from({ length: 121 }, (_, k) => [ccx + rad * Math.cos((k / 120) * 2 * Math.PI), ccy + rad * Math.sin((k / 120) * 2 * Math.PI)]), 2 * PT);
    const [sqx, sqy, sqw, sqh] = g.centre_square; poly([[sqx, sqy], [sqx + sqw, sqy], [sqx + sqw, sqy + sqh], [sqx, sqy + sqh], [sqx, sqy]], 2 * PT);
    x.save(); x.clip(oval);
    for (const gx of [0, g.length]) {
      const a0 = gx === 0 ? -Math.PI / 2 : Math.PI / 2;
      poly(Array.from({ length: 80 }, (_, k) => { const a = a0 + (k / 79) * Math.PI; return [gx + g.arc_radius * Math.cos(a), g.arc_radius * Math.sin(a)]; }), 2 * PT);
    }
    x.restore();
    for (const [gx0, gy0, gw, gh] of g.goal_squares) poly([[gx0, gy0], [gx0 + gw, gy0], [gx0 + gw, gy0 + gh], [gx0, gy0 + gh], [gx0, gy0]], 2 * PT);
    x.strokeStyle = "#fff8e1"; x.lineCap = "butt";
    for (const gx of [0, g.length]) for (const [yy, w, hgt] of [[-g.goal_half_width, 4, 8], [g.goal_half_width, 4, 8], [-g.behind_half_width, 3, 4.96], [g.behind_half_width, 3, 4.96]]) {
      const [X, Y] = cam.screen(gx, yy); x.lineWidth = w * PT; x.beginPath(); x.moveTo(X, Y); x.lineTo(X, Y - hgt * cam.scale(yy) * cam.ppm); x.stroke();
    }
    // under the players: the holder's ring, the man on the mark, the kick's line, the ball's shadow
    const a = s.a, pos = (pid) => { const k = this.idx[pid]; return [s.p[2 * k], s.p[2 * k + 1]]; };
    x.lineWidth = 2 * PT;
    if (a.ho && this.idx[a.ho] !== undefined) { const [hx, hy] = pos(a.ho), [X, Y] = cam.screen(hx, hy); x.strokeStyle = a.pr ? "#00ff00" : "#ffff00"; x.beginPath(); x.arc(X, Y, 1.3 * cam.ppm * cam.scale(hy), 0, 2 * Math.PI); x.stroke(); }
    if (a.mm && this.idx[a.mm] !== undefined) { const [mx, my] = pos(a.mm), [X, Y] = cam.screen(mx, my); x.strokeStyle = "#ffffff"; x.setLineDash([6, 4]); x.beginPath(); x.arc(X, Y, 1.3 * cam.ppm * cam.scale(my), 0, 2 * Math.PI); x.stroke(); x.setLineDash([]); }
    if (a.l && a.s === "flight") { const [X0, Y0] = cam.screen(s.b[0], s.b[1]), [X1, Y1] = cam.screen(a.l[0], a.l[1]); x.strokeStyle = LED; x.lineWidth = 1.5 * PT; x.setLineDash([5.5, 2.4]); x.beginPath(); x.moveTo(X0, Y0); x.lineTo(X1, Y1); x.stroke(); x.setLineDash([]); }
    const bsc = cam.scale(s.b[1]), [BX, BY] = cam.screen(s.b[0], s.b[1]);
    x.fillStyle = "rgba(0,0,0,0.35)"; x.beginPath(); x.arc(BX, BY, 0.35 * cam.ppm * bsc, 0, 2 * Math.PI); x.fill();
    // the players, far to near, then the ball, then the labels
    const order = d.pids.map((pid) => ({ pid, p: pos(pid) })).sort((u, v) => cam.depth(v.p[1]) - cam.depth(u.p[1]));
    const prevI = Math.max(0, s.i - 1), pf = d.frames[prevI], nf = d.frames[s.i];
    const labels = [];
    for (const { pid, p } of order) {
      const k = this.idx[pid], vx = nf.p[2 * k] - pf.p[2 * k], vy = nf.p[2 * k + 1] - pf.p[2 * k + 1];
      const moving = Math.hypot(vx, vy) / Math.max(0.05, nf.t - pf.t) > 0.8 && !this.hold, facing = vx >= 0 ? 1 : -1;   // > 0.8 m/s
      const frame = moving ? Math.floor(t / 0.3) % 2 : 0, role = ["midfielder", "defender", "forward"].includes(d.roles[pid]) ? d.roles[pid] : "";
      const im = this.img[`p${pid[0]}_${frame}_${facing}_${role}`], sc = cam.scale(p[1]), [X, Y] = cam.proj(p[0], p[1]);
      const hgt = 1.8 * cam.ppm * sc * PT, wid = (hgt * 12) / 16, cxp = cam.sx(X), cyp = cam.sy(Y + 0.9 * sc);
      if (im && im.complete) x.drawImage(im, Math.round(cxp - wid / 2), Math.round(cyp - hgt / 2), Math.round(wid), Math.round(hgt));
      labels.push([d.tags[pid] || pid.slice(1), cam.sx(X), cam.sy(Y + 2.6 * sc), sc, pid[0]]);
    }
    const ang = a.s === "flight" ? Math.floor(t / 0.1) % 12 : 0, bim = this.img[`ball${ang}`];
    const bsize = 0.9 * cam.ppm * (1 + 0.12 * s.h) * bsc * PT, [bXp, bYp] = cam.proj(s.b[0], s.b[1]);
    if (bim && bim.complete) x.drawImage(bim, cam.sx(bXp) - bsize / 2, cam.sy(bYp + (0.45 + 0.9 * s.h) * bsc) - bsize / 2, bsize, bsize);
    x.textAlign = "center"; x.textBaseline = "middle";
    for (const [txt, lx, ly, sc, team] of labels) {
      const fs = 6.5 * (0.6 + 0.4 * sc) * PT; x.font = `bold ${fs.toFixed(1)}px ${MONO}`;
      const w = x.measureText(txt).width + fs * 0.2;
      x.globalAlpha = 0.85; x.fillStyle = d.sprites.colours[team]; x.fillRect(lx - w / 2, ly - fs * 0.6, w, fs * 1.2); x.globalAlpha = 1;
      x.fillStyle = "#ffffff"; x.fillText(txt, lx, ly + fs * 0.04);
    }
    if (this.live) this.liveExtras(x, s, pos);
    this.overlays(x, t);
    x.restore();
    this.chrome(x, t, a, clock);
    x.restore();
  }

  // ---- live play: controls, the tick, the markers
  waiting(x) {
    x.fillStyle = BG; x.fillRect(0, 0, FW, FH); x.fillStyle = "#ffffff"; x.font = `bold 40px ${MONO}`; x.textAlign = "center"; x.textBaseline = "middle";
    x.fillText("KICK OFF...", FW / 2, FH / 2);
  }
  dir() {
    const k = this.keys, x = (k.has("arrowright") || k.has("d") ? 1 : 0) - (k.has("arrowleft") || k.has("a") ? 1 : 0);
    const y = (k.has("arrowup") || k.has("w") ? 1 : 0) - (k.has("arrowdown") || k.has("s") ? 1 : 0);   // up the screen = the far touchline = +y
    return [x, y];
  }
  liveKey(e, down) {
    const k = e.key.toLowerCase();
    if (["arrowup", "arrowdown", "arrowleft", "arrowright", " "].includes(k)) e.preventDefault();
    if (this.finished) return;
    const f = this.d.frames[this.d.frames.length - 1], mine = f && f.ho && f.ho === this.control.pid;
    if (down && e.repeat) return;
    if (k === "q") {
      if (down) this.qHeld = { used: false };
      else { if (this.qHeld && !this.qHeld.used) this.presses.push("switch"); this.qHeld = null; }
      return;
    }
    if (down && this.qHeld && ["arrowup", "arrowdown", "arrowleft", "arrowright", "w", "a", "s", "d"].includes(k)) {
      const dx = { arrowright: 1, d: 1, arrowleft: -1, a: -1 }[k] || 0, dy = { arrowup: 1, w: 1, arrowdown: -1, s: -1 }[k] || 0;
      this.presses.push(`switch:${dx},${dy}`); this.qHeld.used = true; return;
    }
    if (down) this.keys.add(k); else this.keys.delete(k);
    this.poll();                                                           // a key change goes to the server at once
    if (k === " ") {
      if (down) { if (mine) this.charge = { t0: performance.now(), power: 0 }; else this.presses.push("action"); }
      else if (this.charge) { this.presses.push("kick:" + this.charge.power.toFixed(3)); this.charge = null; }
    } else if (down && (k === "j" || k === "z")) this.presses.push("handball");
    else if (down && (k === "l" || k === "x")) this.presses.push("spoil");
  }
  async poll() {
    if (this.polling) { this.pollAgain = true; return; }
    if (!this.alive || this.finished) return;
    this.polling = true;
    try {
      const body = { since: this.seq, ev: this.ev, input: { dir: this.dir(), sprint: this.keys.has("shift") }, presses: this.presses.splice(0) };
      const r = await fetch(`/api/live/${this.live.sid}/tick`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) { if (r.status === 404) { this.finished = true; toast("The live game ended", "bad"); } return; }
      const res = await r.json(), d = this.d;
      for (const f of res.frames) d.frames.push(f);
      this.seq = res.seq; this.ev = res.ev; this.control = res.control || {};
      if (d.frames.length) { this.t0 = d.frames[0].t; this.t1 = d.frames[d.frames.length - 1].t; }
      const now = performance.now();
      for (const n of res.notes || []) if (!this.notes.some((m) => m[0] === n[0] && m[1] === n[1])) this.notes.push([n[0], n[1], now, n[3]]);
      this.notes = this.notes.filter((n) => now - n[2] < 1200);
      for (const e of res.events) {
        if (e.text) d.ticker.push([e.t, e.text]);
        if (["kick", "handball", "mark", "spoil", "tackle"].includes(e.k)) { d.actions.push([e.t, e.k, e.by]); this.chip.play(e.k); }
        if (e.k === "chain") d.chains = [[-1, null, ""], [e.t, e.team, e.text]];
        if (e.k === "score") {
          d.scoring.push([e.t, e.team, e.kind]);
          const prev = d.scores[d.scores.length - 1][1], nx = { A: [...prev.A], B: [...prev.B] }; nx[e.team][e.kind === "goal" ? 0 : 1]++;
          d.scores.push([e.t, nx]);
          this.hold = { kind: e.kind, team: e.team, left: e.kind === "goal" ? 2.5 : 1.0, n: e.kind === "goal" ? 2.5 : 1.0, t: e.t }; this.chip.play(e.kind);
        }
        if (e.k === "end") {
          this.finished = true; this.hold = { kind: "fulltime", left: 1e9, n: 3 }; this.chip.play("siren");
          this.again.classList.remove("hidden"); this.recBtn.classList.remove("hidden");
        }
      }
      if (res.status !== "playing" && !this.finished) { this.finished = true; this.again.classList.remove("hidden"); }
    } catch (e) { /* a missed tick: the next one catches up */ }
    finally { this.polling = false; if (this.pollAgain) { this.pollAgain = false; this.poll(); } }
  }
  liveExtras(x, s, pos) {
    const cam = this.cam, a = s.a, pid = this.control.pid; if (!pid || this.idx[pid] === undefined) return;
    // the timing ring: where the kick comes down, closing as it falls; green = leap now
    if (a.s === "flight" && a.l && a.li !== undefined) {
      const [X, Y] = cam.screen(a.l[0], a.l[1]), sc = cam.scale(a.l[1]), inner = 0.9 * cam.ppm * sc, outer = (0.9 + Math.max(0, a.li - 0.1) * 3.2) * cam.ppm * sc;
      const ok = a.li <= this.live.window;
      x.lineWidth = 3; x.strokeStyle = ok ? "#00ff66" : "rgba(255,255,255,0.75)";
      x.beginPath(); x.ellipse(X, Y, outer, outer * 0.55, 0, 0, 2 * Math.PI); x.stroke();
      x.lineWidth = 2; x.strokeStyle = ok ? "#00ff66" : "rgba(255,255,255,0.45)"; x.beginPath(); x.ellipse(X, Y, inner, inner * 0.55, 0, 0, 2 * Math.PI); x.stroke();
    }
    // the next player Q would take
    if (this.control.next && this.idx[this.control.next] !== undefined) {
      const [nx, ny] = pos(this.control.next), [X, Y] = cam.screen(nx, ny), r = 1.1 * cam.ppm * cam.scale(ny);
      x.strokeStyle = "rgba(255,255,255,0.4)"; x.lineWidth = 1.5; x.setLineDash([3, 3]); x.beginPath(); x.ellipse(X, Y, r, r * 0.55, 0, 0, 2 * Math.PI); x.stroke(); x.setLineDash([]);
    }
    // P1: you
    const [px, py] = pos(pid), sc = cam.scale(py), [PX, PYp] = cam.proj(px, py), mx = cam.sx(PX), my = cam.sy(PYp + 3.9 * sc);
    x.fillStyle = "#ffe14a"; x.strokeStyle = "#000000"; x.lineWidth = 2;
    x.beginPath(); x.moveTo(mx - 9, my - 12); x.lineTo(mx + 9, my - 12); x.lineTo(mx, my); x.closePath(); x.fill(); x.stroke();
    x.font = `bold 13px ${MONO}`; x.textAlign = "center"; x.textBaseline = "bottom"; x.lineWidth = 3; x.strokeText("P1", mx, my - 13); x.fillText("P1", mx, my - 13);
    // the kick's power meter
    if (this.charge) {
      const w = 64, hh = 9, bx = mx - w / 2, by = my - 40, full = w / 1.25, p = this.charge.power;
      x.fillStyle = "rgba(0,0,0,0.75)"; x.fillRect(bx - 2, by - 2, w + 4, hh + 4);
      x.fillStyle = p <= 1 ? "#43a047" : "#e53935"; x.fillRect(bx, by, Math.min(p, 1.25) * full, hh);
      x.fillStyle = "rgba(229,57,53,0.35)"; x.fillRect(bx + full, by, w - full, hh);
      x.fillStyle = "#ffffff"; x.fillRect(bx + full - 1, by - 3, 2, hh + 6);
    }
    // feedback: TOO EARLY, LEAP!, TACKLE!...
    const now = performance.now();
    this.notes.forEach((n, i) => {
      const age = (now - n[2]) / 1200; if (age > 1) return;
      x.globalAlpha = 1 - age * 0.7; x.font = `bold 18px ${MONO}`; x.textAlign = "center"; x.textBaseline = "bottom";
      x.lineWidth = 4; x.strokeStyle = "#000000"; x.strokeText(n[1], mx, my - 50 - i * 20 - age * 16);
      x.fillStyle = n[1].includes("TOO") || n[1].includes("NO ") || n[1].includes("SPRAY") ? "#ff6e6e" : "#ffe14a"; x.fillText(n[1], mx, my - 50 - i * 20 - age * 16);
      x.globalAlpha = 1;
    });
  }

  overlays(x, t) {                                                          // GOAL!!! / BEHIND / FULL TIME, over the ground
    const ho = this.hold; if (!ho) return;
    const s = this.scoreAt(ho.t ?? t), names = this.d.names;
    let big, col, size, sub;
    if (ho.kind === "goal" || ho.kind === "behind") {
      const k = 1 - ho.left / ho.n, pulse = 1 + 0.08 * Math.sin(k * Math.PI * 4);
      big = ho.kind === "goal" ? "G O A L ! ! !" : "BEHIND"; col = this.d.sprites.colours[ho.team]; size = (ho.kind === "goal" ? 54 : 30) * pulse;
      sub = `${names[ho.team].toUpperCase()}   ${fmtScore(s.A)} - ${fmtScore(s.B)}`;
    } else {
      const pa = 6 * s.A[0] + s.A[1], pb = 6 * s.B[0] + s.B[1];
      big = "FULL TIME"; col = "#ffffff"; size = 40; sub = `${pa === pb ? "DRAW" : (pa > pb ? names.A : names.B).toUpperCase() + " WIN"}   ${fmtScore(s.A)} - ${fmtScore(s.B)}`;
    }
    const [cx, cy] = at(GROUND, 0.5, 0.56), fs = size * PT;
    x.font = `bold ${fs.toFixed(0)}px ${MONO}`; x.textAlign = "center"; x.textBaseline = "middle";
    const w = x.measureText(big).width, pad = fs * 0.6;
    x.globalAlpha = 0.8; x.fillStyle = "#000000"; x.fillRect(cx - w / 2 - pad, cy - fs / 2 - pad, w + 2 * pad, fs + 2 * pad); x.globalAlpha = 1;
    x.strokeStyle = LED; x.lineWidth = 3 * PT; x.strokeRect(cx - w / 2 - pad, cy - fs / 2 - pad, w + 2 * pad, fs + 2 * pad);
    x.fillStyle = col; x.fillText(big, cx, cy);
    const [sx, sy] = at(GROUND, 0.5, 0.30); x.font = `${(16 * PT).toFixed(0)}px ${MONO}`; x.fillStyle = "#ffffff"; x.fillText(sub, sx, sy);
  }

  chrome(x, t, a, clock) {                                                  // scoreboard, coach panels, energy, ticker
    const d = this.d, names = d.names, COL = d.sprites.colours, ho = this.hold;
    const text = (s, px, py, size, col, align = "left", bold = false) => { x.font = `${bold ? "bold " : ""}${(size * PT).toFixed(1)}px ${MONO}`; x.fillStyle = col; x.textAlign = align; x.textBaseline = "middle"; x.fillText(s, px, py); };
    // scoreboard
    x.fillStyle = "#000000"; x.fillRect(0.005 * FW, FH * (1 - 0.99), 0.99 * FW, 0.105 * FH);
    x.strokeStyle = LED; x.lineWidth = 2 * PT; x.strokeRect(0.005 * FW, FH * (1 - 0.99), 0.99 * FW, 0.105 * FH);
    const s = this.scoreAt(ho && ho.t !== undefined ? ho.t : t);
    text(names.A.toUpperCase(), ...at(TOP, 0.03, 0.62), 20, COL.A, "left", true);
    text(names.B.toUpperCase(), ...at(TOP, 0.97, 0.62), 20, COL.B, "right", true);
    text(fmtScore(s.A), ...at(TOP, 0.40, 0.62), 26, LED, "right", true);
    text(fmtScore(s.B), ...at(TOP, 0.60, 0.62), 26, LED, "left", true);
    text("-", ...at(TOP, 0.50, 0.62), 22, "#888888", "center");
    text(fmtClock(t) + (ho && ho.kind === "fulltime" ? "   FULL TIME" : ""), ...at(TOP, 0.50, 0.15), 12, LED, "center");
    text("defends the left goal", ...at(TOP, 0.03, 0.18), 8, "#999999", "left");
    text("defends the right goal", ...at(TOP, 0.97, 0.18), 8, "#999999", "right");
    // coach panels
    for (const [team, P] of [["A", LEFT], ["B", RIGHT]]) {
      const plan = this.latest(d.plans[team], t), talking = plan && t - plan[0] < 3.0, open = talking && Math.floor(t / 0.2) % 2 === 0;
      const port = this.img[`coach${team}${open ? 1 : 0}`], pw = 24 * 5 * PT, ph = 32 * 5 * PT, [px, py] = at(P, 0.5, 0.78 + (open ? 0.008 : 0));
      x.imageSmoothingEnabled = false; if (port && port.complete) x.drawImage(port, px - pw / 2, py - ph / 2, pw, ph);
      text("COACH", ...at(P, 0.5, 0.50), 8, "#bbbbbb", "center");
      text(names[team], ...at(P, 0.5, 0.46), 10, COL[team], "center", true);
      if (plan) {
        const lines = wrap(plan[2], 34).join("\n").slice(0, d.frames[0].e ? 520 : 900).split("\n");
        const fs = 7 * PT, lh = fs * 1.2; x.font = `${fs.toFixed(1)}px ${MONO}`;
        const w = Math.max(...lines.map((l) => x.measureText(l).width)), pad = fs * 0.5, [bx, by] = at(P, 0.5, 0.42);
        x.fillStyle = "#ffffff"; x.fillRect(bx - w / 2 - pad, by - pad, w + 2 * pad, lines.length * lh + 2 * pad);
        x.strokeStyle = COL[team]; x.lineWidth = (talking ? 3 : 1.5) * PT; x.strokeRect(bx - w / 2 - pad, by - pad, w + 2 * pad, lines.length * lh + 2 * pad);
        x.fillStyle = "#111111"; x.textAlign = "center"; x.textBaseline = "top"; lines.forEach((l, i) => x.fillText(l, bx, by + i * lh));
        text(`plan at ${fmtClock(plan[0])} (${plan[1]})`, ...at(P, 0.5, d.frames[0].e ? 0.30 : 0.005), 7, "#999999", "center");
      }
      if (a.e) {                                                            // energy, one bar per player
        const pids = d.pids.filter((p) => p[0] === team), n = pids.length, yTop = 0.235, yBot = 0.045, dy = (yTop - yBot) / Math.max(n, 1), hh = dy * 0.62;
        const fsz = n <= 10 ? 6.5 : Math.max(3.6, (6.5 * 10) / n);
        const [rx0, ry0] = at(P, 0.03, yTop + 0.055), [rx1, ry1] = at(P, 0.97, yBot - 0.02);
        x.fillStyle = "#000000"; x.fillRect(rx0, ry0, rx1 - rx0, ry1 - ry0); x.strokeStyle = COL[team]; x.lineWidth = 1.2 * PT; x.strokeRect(rx0, ry0, rx1 - rx0, ry1 - ry0);
        text("ENERGY", ...at(P, 0.5, yTop + 0.035), 7.5, "#bbbbbb", "center");
        pids.forEach((pid, k) => {
          const yy = yTop - (k + 0.5) * dy, ev = clamp(a.e[this.idx[pid]] ?? 1, 0, 1);
          text(d.tags[pid] || pid.slice(1), ...at(P, 0.19, yy), fsz, "#ffffff", "right");
          const [bx0, by0] = at(P, 0.22, yy + hh / 2), [bx1, by1] = at(P, 0.94, yy - hh / 2);
          x.fillStyle = "#2a2a2a"; x.fillRect(bx0, by0, bx1 - bx0, by1 - by0);
          x.fillStyle = ev > 0.6 ? "#43a047" : ev > 0.35 ? "#ffb300" : "#e53935"; x.fillRect(bx0, by0, (bx1 - bx0) * ev, by1 - by0);
        });
      }
    }
    // ticker and possession chain
    let tick = "";
    if (ho && (ho.kind === "goal" || ho.kind === "behind")) tick = `${ho.kind === "goal" ? "GOAL" : "BEHIND"}  ${names[ho.team]}`;
    else { const e = this.latest(d.ticker, t); if (e && t - e[0] <= 4.0) tick = e[1]; }
    text(tick, ...at(BOTTOM, 0.01, 0.72), 10, "#eeeeee", "left");
    const c = this.latest(d.chains, t);
    if (c && c[2]) { text("POSSESSION", ...at(BOTTOM, 0.01, 0.25), 8, "#888888", "left"); text(c[2].slice(-118), ...at(BOTTOM, 0.115, 0.25), 9, c[1] ? COL[c[1]] : "#eeeeee", "left"); }
  }

  // ---- a video: frame by frame at 30 fps, holds included, through the 3D view's encoder
  async makeVideo() {
    if (this.making) { this.making.cancel = true; return; }
    const fps = 30, step = this.speed / fps, start = this.t, end = this.t1;
    if (end - start < 0.2) return toast("Move back to where the video should start: it renders from here to the end", "bad");
    let vid;
    try {
      const r = await fetch("/api/analysis/video3d/start?fps=" + fps + "&name=" + encodeURIComponent((this.opts.recordName || "replay") + "_retro"), { method: "POST" });
      if (!r.ok) throw new Error(await r.text()); vid = (await r.json()).id;
    } catch (e) { return toast("Couldn't start the video: " + e.message, "bad"); }
    const job = (this.making = { cancel: false }); this.playing = false; this.playBtn.textContent = "▶";
    const jpeg = () => { const b64 = this.canvas.toDataURL("image/jpeg", 0.92).split(",")[1], bin = atob(b64), out = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i); return out; };
    let batch = [], done = 0, ok = false, clock = 0;
    const flush = async () => { if (!batch.length) return; const n = batch.length, body = new Blob(batch); batch = []; const r = await fetch(`/api/analysis/video3d/${vid}/frames?n=${n}`, { method: "POST", body }); if (!r.ok) throw new Error(await r.text()); };
    const shoot = async () => { this.draw(this.x, this.t, step / this.speed, clock); clock += 1 / fps; batch.push(jpeg()); done++; if (batch.length >= 30) await flush(); };
    const f0 = this.frameAt(start); if (f0) this.cam.pan = this.cam.target(f0.b[0], f0.b[1]);
    this.hold = null;
    try {
      while (!job.cancel) {
        if (this.hold) { for (let i = 0; i < Math.round(this.hold.n * fps) && !job.cancel; i++) { this.hold.left = this.hold.n - i / fps; await shoot(); } const ft = this.hold.kind === "fulltime"; this.hold = null; if (ft) break; continue; }
        const t0 = this.t, t1 = Math.min(end, this.t + step), sc = this.d.scoring.find((q) => q[0] > t0 + 1e-6 && q[0] <= t1);
        this.t = sc ? sc[0] : t1;
        if (sc) this.hold = { kind: sc[2], team: sc[1], left: HOLD[sc[2]] || 1, n: HOLD[sc[2]] || 1, t: sc[0] };
        else if (this.t >= end - 1e-6) { if (end >= this.gameEnd() - 1e-6) this.hold = { kind: "fulltime", left: HOLD.fulltime, n: HOLD.fulltime }; else { await shoot(); break; } }
        await shoot();
        if (done % 15 === 0) { this.recBtn.textContent = `■ Stop (${Math.round((100 * (this.t - start)) / Math.max(1e-6, end - start))}%)`; this.scrub.value = this.t; }
      }
      await flush(); ok = true;
    } catch (e) { toast("Making the video failed: " + e.message, "bad"); }
    try {
      const r = await fetch(`/api/analysis/video3d/${vid}/finish${ok ? "" : "?cancel=true"}`, { method: "POST" });
      const out = await r.json();
      if (ok && out.rel) toast(`Saved ${out.rel} (${(out.bytes / 1e6).toFixed(1)} MB, ${(done / fps).toFixed(1)} s)` + (job.cancel ? " up to where you stopped" : ""), "ok",
        { href: "#/inspect/video/" + encodeURIComponent(out.rel), text: "▶ Watch video" });
      else if (!r.ok) toast("Making the video failed: " + (out.detail || r.status), "bad");
    } catch (e) { toast("Making the video failed: " + e.message, "bad"); }
    this.making = null; this.hold = null; this.recBtn.textContent = "🎬 Make video";
  }
}
