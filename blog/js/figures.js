// Every figure on the page. Data comes from assets/*.json, written by scripts/gen_*.py from real games and the real network.
const $ = (id) => document.getElementById(id);

// responsive SVG: redraws at the real pixel width, so type stays the same size on a phone
function chart(el, aspect, minH, draw) {
  const go = () => {
    const w = el.clientWidth; if (!w) return;
    const h = Math.max(minH, Math.round(w / aspect));
    el.innerHTML = ''; const s = AFL.svg('svg', { viewBox: `0 0 ${w} ${h}`, role: 'img' }, el); draw(s, w, h);
  };
  new ResizeObserver(go).observe(el); go();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', go);
}
function text(s, x, y, str, a = {}) { const t = AFL.svg('text', { x, y, 'font-size': 13, fill: 'var(--ink-2)', ...a }, s); t.textContent = str; return t; }
function line(s, x1, y1, x2, y2, stroke = 'var(--rule)', w = 1) { return AFL.svg('line', { x1, y1, x2, y2, stroke, 'stroke-width': w }, s); }
function hover(node, html) {
  node.addEventListener('pointermove', (e) => AFL.showTip(html, e.clientX, e.clientY));
  node.addEventListener('pointerleave', AFL.hideTip);
}

/* ---- hero: the game, with the network's rating underneath ---- */
async function figHero() {
  const m = await AFL.load('match');
  new Replay($('hero'), m, { autoplay: true, speed: 3, start: 44, mode: 'value' });
}

/* ---- pressure: the engine's own formula, on three opponents you can move ---- */
function figPressure() {
  const cv = $('pressure'), box = { x0: -24, x1: 24, y0: -15, y1: 15 }, opp = [[4.5, 2], [-8, 5.5], [10, -8]], SC = 5, CAP = 2;
  let v, W, H, ctx, drag = -1; const off = document.createElement('canvas'), GW = 96, GH = 60; off.width = GW; off.height = GH; const oc = off.getContext('2d');
  const pressure = (x, y) => opp.reduce((s, o) => s + Math.exp(-(((x - o[0]) ** 2 + (y - o[1]) ** 2) / (SC * SC))), 0);
  const draw = () => {
    if (!ctx) return;
    const img = oc.createImageData(GW, GH);
    for (let j = 0; j < GH; j++) for (let i = 0; i < GW; i++) {
      const x = box.x0 + (i + .5) / GW * 48, y = box.y1 - (j + .5) / GH * 30, p = Math.min(CAP, pressure(x, y)) / CAP, k = (j * GW + i) * 4;
      img.data[k] = 240; img.data[k + 1] = 115; img.data[k + 2] = 63; img.data[k + 3] = p * 215;
    }
    oc.putImageData(img, 0, 0);
    ctx.fillStyle = '#12261c'; ctx.fillRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = true; const a = v.p(box.x0, box.y1), b = v.p(box.x1, box.y0); ctx.drawImage(off, a[0], a[1], b[0] - a[0], b[1] - a[1]);
    const c = v.p(0, 0), r = 8;
    ctx.font = '12.5px "JetBrains Mono", monospace'; ctx.textAlign = 'center';
    opp.forEach((o) => {
      const p = v.p(o[0], o[1]), d = Math.hypot(o[0], o[1]), e = Math.exp(-((d / SC) ** 2));
      ctx.strokeStyle = 'rgba(255,255,255,.3)'; ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.moveTo(c[0], c[1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = '#f0733f'; ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, 7); ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = '#eef1ec'; ctx.fillText(`${d.toFixed(1)} m → ${e.toFixed(2)}`, p[0], p[1] - 14);
    });
    ctx.fillStyle = '#4b97ef'; ctx.beginPath(); ctx.arc(c[0], c[1], r + 1, 0, 7); ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(c[0], c[1], r + 4, 0, 7); ctx.stroke();
    const raw = pressure(0, 0), p = Math.min(CAP, raw);
    $('pressure-read').innerHTML = `<div class="stat"><b>${p.toFixed(2)}</b><span>pressure on the carrier${raw > CAP ? ' (capped)' : ''}, out of ${CAP}</span></div>`;
    $('pressure-bar').style.width = `${(p / CAP) * 100}%`;
  };
  AFL.fit(cv, 1.6, (c, w, h) => { ctx = c; W = w; H = h; v = AFL.view(w, h, box); draw(); });
  const at = (e) => { const r = cv.getBoundingClientRect(); return v.inv(e.clientX - r.left, e.clientY - r.top); };
  cv.addEventListener('pointerdown', (e) => { const q = at(e); let best = 1e9; opp.forEach((o, i) => { const d = Math.hypot(o[0] - q[0], o[1] - q[1]); if (d < best) { best = d; drag = i; } }); if (best > 6) drag = -1; else cv.setPointerCapture(e.pointerId); });
  cv.addEventListener('pointermove', (e) => { if (drag < 0) return; const q = at(e); opp[drag] = [Math.max(-23, Math.min(23, q[0])), Math.max(-14, Math.min(14, q[1]))]; draw(); });
  cv.addEventListener('pointerup', () => { drag = -1; });
}

/* ---- the harness loop: real decisions from the real game ---- */
async function figLoop() {
  const m = await AFL.load('match');
  const NAMES = { M: 'MOVE', O: 'HOLD', K: 'KICK', H: 'HANDBALL', P: 'ATTEMPT_POSSESSION', A: 'ATTEMPT_MARK', S: 'SPOIL', T: 'TACKLE' };
  const PACE = { s: 'sprint', r: 'run', j: 'jog' };
  const BOTS = {
    code: `<span class="k"># one Python file</span>\nclass Bot(BotBase):\n  def choose_actions(self, state):\n    ...\n    return intent, actions\n\n<span class="k"># about 1 s of match time per call\n# a full game: seconds of CPU</span>`,
    llm: `<span class="k"># the same state, as a prompt</span>\nmodel reads the rules + state\nmodel replies:\n{"intent": "...",\n "actions": [ ... ]}\n\n<span class="k"># same contract, same engine\n# one API call per decision</span>`,
  };
  AFL.seg($('loop-kind'), [['code', 'A bot written in code'], ['llm', 'An LLM making each decision']], 'code', (k) => { $('loop-bot').innerHTML = BOTS[k]; });
  $('loop-bot').innerHTML = BOTS.code;
  let i = 70, seen = false; const rp = { at: Replay.prototype.at, pad: 32, m };
  const tick = () => {
    if (!seen) return;
    const d = m.orders[i], f = rp.at(d.t), hold = f.holder >= 0 ? m.pids[f.holder] : null, st = { h: 'held', f: 'flight', l: 'loose' }[f.state] || 'dead';
    const sc = m.score[f.i];
    $('loop-state').textContent = `time      ${d.t.toFixed(1)} s\nscore     A ${sc[0]}  B ${sc[1]}\nball      ${st}\nball_at   (${f.ball[0].toFixed(0)}, ${f.ball[1].toFixed(0)})\nholder    ${hold ?? 'nobody'}\nplayers   16 x {pos, vel, energy,\n          role, attributes}`;
    const rows = d.o.slice(0, 8).map((o, k) => [m.pids[k], o]).filter(([, o]) => o).sort((a, b) => (a[1][0] === 'M') - (b[1][0] === 'M')).slice(0, 5);
    $('loop-orders').textContent = rows.map(([p, o]) => `${p} ${NAMES[o[0]] ?? o[0]}` + (o[1] !== null ? ` (${o[1].toFixed(0)}, ${o[2].toFixed(0)})` : '') + (o[0] === 'M' ? ` ${PACE[o[3]] ?? ''}` : '')).join('\n') + `\n<span>…three more</span>`.replace(/<\/?span>/g, '');
    i = i + 1 >= m.orders.length ? 0 : i + 1;
  };
  AFL.visible($('loop-fig'), (s) => { seen = s; }); seen = true; tick(); seen = false;
  if (!AFL.reduced) setInterval(tick, 1400);
}

/* ---- the climb ---- */
async function figClimb() {
  const d = await AFL.load('ladder'), bots = d.bots.filter((b) => b.family !== 'zoo' && b.elo >= 1450), zoo = d.bots.filter((b) => b.family === 'zoo' && b.elo > 1400);
  const lo = Math.min(...zoo.map((z) => z.elo)), hi = Math.max(...zoo.map((z) => z.elo));
  chart($('climb'), 2, 340, (s, w, h) => {
    const m = { l: 44, r: 16, t: 18, b: 34 }, X = (r) => m.l + ((r - .5) / 38.5) * (w - m.l - m.r), Y = (e) => h - m.b - ((e - 1450) / 650) * (h - m.t - m.b);
    for (const e of [1500, 1600, 1700, 1800, 1900, 2000, 2100]) { line(s, m.l, Y(e), w - m.r, Y(e)); text(s, m.l - 8, Y(e) + 4, e.toLocaleString(), { 'text-anchor': 'end', fill: 'var(--ink-3)', 'font-size': 12 }); }
    for (const r of [1, 10, 20, 30, 38]) text(s, X(r), h - m.b + 18, r, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12 });
    text(s, (m.l + w - m.r) / 2, h - 3, 'Round', { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12 });
    AFL.svg('rect', { x: m.l, y: Y(hi), width: w - m.l - m.r, height: Y(lo) - Y(hi), fill: 'var(--panel-2)' }, s);
    text(s, w - m.r - 6, Y(lo) - 6, `Hand-written clubs, ${lo.toLocaleString()}–${hi.toLocaleString()}`, { 'text-anchor': 'end', 'font-size': 12.5 });
    const best = []; let cur = 0;
    for (let r = 1; r <= 38; r++) { for (const b of bots) if (b.round === r) cur = Math.max(cur, b.elo); if (cur) best.push([r, cur]); }
    let dpath = ''; best.forEach(([r, e], i) => { dpath += i ? `H${X(r)}V${Y(e)}` : `M${X(r)} ${Y(e)}`; });
    AFL.svg('path', { d: dpath, fill: 'none', stroke: 'var(--a)', 'stroke-width': 2, 'stroke-linejoin': 'round' }, s);
    for (const b of bots) {
      const champ = b.name === 'round_36a', col = b.family === 'climb' ? 'var(--a)' : 'var(--ink-3)';
      AFL.svg('circle', { cx: X(b.round), cy: Y(b.elo), r: champ ? 6 : 3.6, fill: col, 'fill-opacity': champ ? 1 : .6, stroke: champ ? 'var(--page)' : 'none', 'stroke-width': 2 }, s);
      const hit = AFL.svg('circle', { cx: X(b.round), cy: Y(b.elo), r: 9, fill: 'transparent' }, s);
      hover(hit, `<b>${b.family === 'climb' ? '' : b.family + ' '}${b.name}</b><br>Elo ${b.elo.toLocaleString()} · ${b.games} games`);
    }
    const c = bots.find((b) => b.name === 'round_36a');
    text(s, X(36) - 10, Y(c.elo) - 3, `round_36a, ${c.elo.toLocaleString()}`, { 'text-anchor': 'end', fill: 'var(--ink)', 'font-weight': 600, 'font-size': 14 });
  });
}

/* ---- one position, many futures ---- */
async function figFutures() {
  const d = await AFL.load('moments'); let mi = 1, T = 0, raf = 0, v, W, H, ctx, seen = false, bg = null; const SPEED = 9, MAXT = 62;
  const cv = $('futures');
  AFL.seg($('futures-seg'), d.moments.map((m, i) => [i, m.name]), '1', (k) => { mi = +k; T = 0; start(); });
  const paint = () => {
    if (!ctx) return; const m = d.moments[mi];
    if (!bg) { bg = document.createElement('canvas'); bg.width = cv.width; bg.height = cv.height; const b = bg.getContext('2d'), s = cv.width / W; b.setTransform(s, 0, 0, s, 0, 0); AFL.drawGround(b, v); }
    ctx.clearRect(0, 0, W, H); ctx.drawImage(bg, 0, 0, W, H);
    let a = 0, b = 0;
    for (const r of m.rollouts) {
      const col = r.who === 'A' ? '75,151,239' : r.who === 'B' ? '240,115,63' : '200,200,200';
      const done = r.t <= T; if (done) { a += r.who === 'A'; b += r.who === 'B'; }
      ctx.strokeStyle = `rgba(${col},${done ? .34 : .5})`; ctx.lineWidth = 1.1; ctx.beginPath();
      let last = null;
      for (let i = 0; i < r.path.length; i++) {
        const q = r.path[i]; if (q[2] > T) { if (last) { const p0 = r.path[i - 1], k = (T - p0[2]) / (q[2] - p0[2] || 1); const p = v.p(p0[0] + (q[0] - p0[0]) * k, p0[1] + (q[1] - p0[1]) * k); ctx.lineTo(p[0], p[1]); last = p; } break; }
        const p = v.p(q[0], q[1]); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); last = p;
      }
      ctx.stroke();
      if (last && !done) { ctx.fillStyle = `rgb(${col})`; ctx.beginPath(); ctx.arc(last[0], last[1], 2.2, 0, 7); ctx.fill(); }
    }
    const rad = Math.max(3.2, v.s * 1.15);
    for (const [id, p] of Object.entries(m.pos)) { const q = v.p(p[0], p[1]); ctx.fillStyle = id[0] === 'A' ? '#4b97ef' : '#f0733f'; ctx.globalAlpha = T > 0 ? .35 : 1; ctx.beginPath(); ctx.arc(q[0], q[1], rad, 0, 7); ctx.fill(); ctx.globalAlpha = 1; }
    const bq = v.p(m.ball[0], m.ball[1]); ctx.fillStyle = '#ffe9a8'; ctx.beginPath(); ctx.arc(bq[0], bq[1], rad * .8, 0, 7); ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(bq[0], bq[1], rad + 3, 0, 7); ctx.stroke();
    const n = a + b, share = n ? a / n : 0;
    $('fut-a').textContent = a; $('fut-b').textContent = b; $('fut-share').textContent = n ? AFL.pct(share) : '–'; $('fut-net').textContent = AFL.pct(m.v);
    $('fut-bar-a').style.width = `${(a / m.rollouts.length) * 100}%`; $('fut-bar-b').style.width = `${(b / m.rollouts.length) * 100}%`;
  };
  function start() {
    cancelAnimationFrame(raf); if (AFL.reduced) { T = MAXT; paint(); return; }
    let last = performance.now();
    const step = (now) => { T += Math.min(.3, (now - last) / 1000) * SPEED; last = now; if (T > MAXT + 14) T = 0; paint(); if (seen) raf = requestAnimationFrame(step); };
    if (seen) raf = requestAnimationFrame(step); else paint();
  }
  AFL.fit(cv, 1.42, (c, w, h) => { ctx = c; W = w; H = h; v = AFL.view(w, h); bg = null; paint(); });
  AFL.visible(cv, (s) => { seen = s; if (s) start(); else cancelAnimationFrame(raf); });
}

/* ---- watch the network think ---- */
async function figNetwork() {
  const m = await AFL.load('match'), cv = $('net'); let ctx, W, H, last = -1;
  const bytes = m.layers.map((l) => Uint8Array.from(atob(l.b64), (c) => c.charCodeAt(0)));
  const cur = m.layers.map((l) => new Float32Array(l.keep)), n = m.pids.length;
  const layout = () => {
    const cols = [{ c: 5, rows: 16 }, { c: 5, rows: 16 }, { c: 3, rows: 16 }]; const top = 38, bot = H - 26, cell = Math.min(11, (bot - top) / 16), gap = 1.5;
    const xs = [W * .1, W * .34, W * .56, W * .76, W * .92];
    return { cols, top, cell, gap, xs, h: 16 * cell };
  };
  const draw = (di, val) => {
    if (!ctx) return; const L = layout();
    ctx.clearRect(0, 0, W, H); ctx.font = '12px "Source Sans 3", sans-serif'; ctx.textAlign = 'center';
    m.layers.forEach((l, li) => { for (let j = 0; j < l.keep; j++) cur[li][j] += (bytes[li][di * l.keep + j] / 255 - cur[li][j]) * .22; });
    const pos = (li, j) => { const c = L.cols[li], w = c.c * (L.cell + L.gap), x = L.xs[li + 1] - w / 2 + (j % c.c) * (L.cell + L.gap), y = L.top + Math.floor(j / c.c) * (L.cell + L.gap); return [x, y]; };
    const inY = (i) => L.top + (i + .5) * (L.h / 16);
    const tops = m.layers.map((l, li) => [...cur[li]].map((a, j) => [a, j]).sort((a, b) => b[0] - a[0]).slice(0, 7));
    ctx.lineWidth = 1;
    const link = (x1, y1, x2, y2, a) => { ctx.strokeStyle = `rgba(150,195,255,${a})`; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.bezierCurveTo((x1 + x2) / 2, y1, (x1 + x2) / 2, y2, x2, y2); ctx.stroke(); };
    const sens = [...Array(n).keys()].map((i) => [m.sens[di * n + i] / 99, i]).sort((a, b) => b[0] - a[0]).slice(0, 5);
    for (const [k, i] of sens) for (const [a, j] of tops[0].slice(0, 3)) { const p = pos(0, j); link(L.xs[0] + 6, inY(i), p[0], p[1] + L.cell / 2, .1 + .28 * k * a); }
    for (let li = 0; li < 2; li++) for (const [a, j] of tops[li].slice(0, 4)) for (const [b, q] of tops[li + 1].slice(0, 3)) { const p = pos(li, j), r = pos(li + 1, q); link(p[0] + L.cell, p[1] + L.cell / 2, r[0], r[1] + L.cell / 2, .06 + .24 * a * b); }
    for (const [a, j] of tops[2].slice(0, 5)) { const p = pos(2, j); link(p[0] + L.cell, p[1] + L.cell / 2, L.xs[4] - 16, L.top + L.h / 2, .08 + .25 * a); }
    for (let i = 0; i < n; i++) {
      const k = m.sens[di * n + i] / 99; ctx.fillStyle = i < 8 ? '#4b97ef' : '#f0733f'; ctx.globalAlpha = .28 + .72 * k; ctx.beginPath(); ctx.arc(L.xs[0], inY(i), 2.6 + 3.4 * k, 0, 7); ctx.fill();
    }
    ctx.globalAlpha = 1;
    m.layers.forEach((l, li) => { for (let j = 0; j < l.keep; j++) { const a = cur[li][j], p = pos(li, j); ctx.fillStyle = `rgba(${Math.round(60 + 170 * a)},${Math.round(90 + 150 * a)},${Math.round(120 + 135 * a)},${.2 + .8 * a})`; ctx.fillRect(p[0], p[1], L.cell, L.cell); } });
    const oy = L.top + L.h / 2; ctx.fillStyle = AFL.diverge(val, .4); ctx.beginPath(); ctx.arc(L.xs[4], oy, 17, 0, 7); ctx.fill(); ctx.strokeStyle = 'rgba(255,255,255,.7)'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.fillStyle = '#fff'; ctx.font = '600 12.5px "JetBrains Mono", monospace'; ctx.fillText(AFL.pct(val), L.xs[4], oy + 4.5);
    ctx.font = '12px "Source Sans 3", sans-serif'; ctx.fillStyle = '#a9b5ad';
    [['269 inputs', 0], ['512', 1], ['512', 2], ['256', 3], ['1', 4]].forEach(([t, i]) => ctx.fillText(t, L.xs[i], 20));
    ctx.fillText('16 players', L.xs[0], L.top + L.h + 16); ctx.fillText('strongest units shown', L.xs[2], L.top + L.h + 16); ctx.fillText('P(next goal)', L.xs[4] - 6, oy + 34);
  };
  AFL.fit(cv, .98, (c, w, h) => { ctx = c; W = w; H = h; draw(Math.max(0, last), .5); });
  new Replay($('net-replay'), m, { autoplay: true, speed: 1, start: 46, mode: 'network', legend: '<span>Halo: how much that player moves the rating</span>', onframe: (r, di, val) => { last = di; draw(di, val); } });
}

/* ---- the map: P(next goal) by ball position, labels and network ---- */
async function figMap() {
  const d = await AFL.load('field'); let tab = 'mine'; const ids = ['map-label', 'map-net'], keys = ['label', 'net'], st = [{}, {}];
  const draw = (i) => {
    const s = st[i]; if (!s.c) return; const f = d.field[tab], c = s.c, cw = 140 / d.nx, ch = 100 / d.ny;
    c.clearRect(0, 0, s.w, s.h); c.save(); AFL.ovalPath(c, s.v); c.fillStyle = '#12261c'; c.fill(); c.clip();
    const o = document.createElement('canvas'); o.width = d.nx; o.height = d.ny; const oc = o.getContext('2d'), im = oc.createImageData(d.nx, d.ny);
    for (let y = 0; y < d.ny; y++) for (let x = 0; x < d.nx; x++) {
      const val = f[keys[i]][d.ny - 1 - y][x], k = (y * d.nx + x) * 4; if (val < 0) continue;
      const [r, g, b] = AFL.divergeRGB(val, .38); im.data[k] = r; im.data[k + 1] = g; im.data[k + 2] = b; im.data[k + 3] = 255;
    }
    oc.putImageData(im, 0, 0); c.imageSmoothingEnabled = true; c.imageSmoothingQuality = 'high';
    const a = s.v.p(0, 50), b = s.v.p(140, -50); c.drawImage(o, a[0], a[1], b[0] - a[0], b[1] - a[1]);
    c.restore(); AFL.drawGround(c, s.v, { turf: false });
    c.fillStyle = '#eef1ec'; c.font = '12.5px "Source Sans 3", sans-serif'; c.textAlign = 'center'; const p = s.v.p(70, -46); c.fillText('attacking →', p[0], p[1]);
  };
  AFL.seg($('map-seg'), [['mine', 'We have the ball'], ['theirs', 'They have the ball'], ['loose', 'In dispute']], tab, (k) => { tab = k; draw(0); draw(1); });
  ids.forEach((id, i) => {
    const cv = $(id);
    AFL.fit(cv, 1.42, (c, w, h) => { st[i] = { c, w, h, v: AFL.view(w, h) }; draw(i); });
    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect(), q = st[i].v.inv(e.clientX - r.left, e.clientY - r.top), x = Math.floor(q[0] / (140 / d.nx)), y = Math.floor((q[1] + 50) / (100 / d.ny));
      const f = d.field[tab], val = f[keys[i]][y]?.[x];
      if (val === undefined || val < 0) return AFL.hideTip();
      AFL.showTip(`<b>${AFL.pct(val)}</b> we score next<br>${f.n[y][x].toLocaleString()} positions here`, e.clientX, e.clientY);
    });
    cv.addEventListener('pointerleave', AFL.hideTip);
  });
}

/* ---- calibration ---- */
async function figCalib() {
  const d = await AFL.load('field');
  const frame = (s, w, h, xl, yl) => {
    const m = { l: 42, r: 10, t: 8, b: 38 }, X = (v) => m.l + v * (w - m.l - m.r), Y = (v) => h - m.b - v * (h - m.t - m.b);
    for (const t of [0, .25, .5, .75, 1]) { line(s, m.l, Y(t), w - m.r, Y(t)); text(s, m.l - 7, Y(t) + 4, AFL.pct(t), { 'text-anchor': 'end', fill: 'var(--ink-3)', 'font-size': 12 }); text(s, X(t), h - m.b + 17, AFL.pct(t), { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12 }); }
    line(s, X(0), Y(0), X(1), Y(1), 'var(--axis)', 1.5);
    text(s, (m.l + w - m.r) / 2, h - 3, xl, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12.5 });
    const t = text(s, 0, 0, yl, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12.5, transform: `translate(11 ${(m.t + h - m.b) / 2}) rotate(-90)` }); return { X, Y, t };
  };
  chart($('cal-a'), 1.1, 280, (s, w, h) => {
    const { X, Y } = frame(s, w, h, 'What the network said', 'What actually happened');
    let p = ''; d.calibration.forEach((c, i) => { p += `${i ? 'L' : 'M'}${X(c.p)} ${Y(c.y)}`; });
    AFL.svg('path', { d: p, fill: 'none', stroke: 'var(--a)', 'stroke-width': 2 }, s);
    for (const c of d.calibration) { AFL.svg('circle', { cx: X(c.p), cy: Y(c.y), r: 4, fill: 'var(--a)', stroke: 'var(--panel)', 'stroke-width': 2 }, s); hover(AFL.svg('circle', { cx: X(c.p), cy: Y(c.y), r: 11, fill: 'transparent' }, s), `Said <b>${AFL.pct(c.p, 1)}</b>, happened <b>${AFL.pct(c.y, 1)}</b><br>${c.n.toLocaleString()} held-out rows`); }
  });
  chart($('cal-b'), 1.1, 280, (s, w, h) => {
    const { X, Y } = frame(s, w, h, 'What the network said', 'Share of 100 rollouts');
    for (const r of d.mc) AFL.svg('circle', { cx: X(r.nn), cy: Y(r.mc), r: 2.6, fill: 'var(--a)', 'fill-opacity': .45 }, s);
    s.addEventListener('pointermove', (e) => {
      const b = s.getBoundingClientRect(), px = e.clientX - b.left, py = e.clientY - b.top; let best = null, bd = 196;
      for (const r of d.mc) { const q = (X(r.nn) - px) ** 2 + (Y(r.mc) - py) ** 2; if (q < bd) { bd = q; best = r; } }
      best ? AFL.showTip(`Network <b>${AFL.pct(best.nn)}</b>, rollouts <b>${AFL.pct(best.mc)}</b>`, e.clientX, e.clientY) : AFL.hideTip();
    });
    s.addEventListener('pointerleave', AFL.hideTip);
  });
  $('cal-stats').innerHTML = [[AFL.pct(d.test_acc, 1), 'right about who scores next, held-out games'], [d.test_bce.toFixed(3), `log loss, against ${d.coin_bce.toFixed(3)} for a coin`], [d.mc_r.toFixed(2), `correlation with 100-rollout truth, ${d.mc.length} positions`]].map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join('');
}

/* ---- the what-if tool ---- */
async function figWhatif() {
  const d = await AFL.load('moments'), cv = $('whatif'); let mi = 0, v, W, H, ctx, ball = null, img = null;
  const look = (x, y) => {
    const g = d.moments[mi].whatif, fx = (x - g.x0) / g.step, fy = (y - g.y0) / g.step, i = Math.floor(fx), j = Math.floor(fy), a = fx - i, b = fy - j;
    let s = 0, wt = 0; for (const [p, q, w] of [[i, j, (1 - a) * (1 - b)], [i + 1, j, a * (1 - b)], [i, j + 1, (1 - a) * b], [i + 1, j + 1, a * b]]) { const val = g.v[q]?.[p]; if (val != null) { s += val * w; wt += w; } }
    return wt ? s / wt : null;
  };
  const build = () => {
    const g = d.moments[mi].whatif; img = document.createElement('canvas'); img.width = g.nx; img.height = g.ny; const c = img.getContext('2d'), im = c.createImageData(g.nx, g.ny);
    for (let j = 0; j < g.ny; j++) for (let i = 0; i < g.nx; i++) { const val = g.v[g.ny - 1 - j][i], k = (j * g.nx + i) * 4; if (val == null) continue; const [r, gg, b] = AFL.divergeRGB(val, .42); im.data[k] = r; im.data[k + 1] = gg; im.data[k + 2] = b; im.data[k + 3] = 255; }
    c.putImageData(im, 0, 0);
  };
  const paint = () => {
    if (!ctx) return; const m = d.moments[mi], g = m.whatif;
    ctx.clearRect(0, 0, W, H); ctx.save(); AFL.ovalPath(ctx, v); ctx.fillStyle = '#2b312d'; ctx.fill(); ctx.clip();
    const a = v.p(-g.step / 2, 50 + g.step / 2), b = v.p(140 + g.step / 2, -50 - g.step / 2); ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(img, a[0], a[1], b[0] - a[0], b[1] - a[1]); ctx.restore();
    AFL.drawGround(ctx, v, { turf: false });
    const r = Math.max(3.4, v.s * 1.2);
    for (const [id, p] of Object.entries(m.pos)) { if (id === m.holder) continue; const q = v.p(p[0], p[1]); ctx.fillStyle = id[0] === 'A' ? '#4b97ef' : '#f0733f'; ctx.strokeStyle = 'rgba(255,255,255,.85)'; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, 7); ctx.fill(); ctx.stroke(); }
    const o = v.p(m.ball[0], m.ball[1]), q = v.p(ball[0], ball[1]);
    ctx.strokeStyle = 'rgba(255,255,255,.8)'; ctx.setLineDash([4, 4]); ctx.lineWidth = 1.3; ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(q[0], q[1]); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(255,255,255,.75)'; ctx.beginPath(); ctx.arc(o[0], o[1], 3, 0, 7); ctx.fill();
    ctx.fillStyle = '#ffe9a8'; ctx.strokeStyle = '#10150f'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(q[0], q[1], r + 3, 0, 7); ctx.fill(); ctx.stroke();
    const here = look(ball[0], ball[1]) ?? m.v, base = look(m.ball[0], m.ball[1]) ?? m.v, dv = (here - base) * 100;
    $('wi-here').textContent = AFL.pct(here); $('wi-base').textContent = AFL.pct(base); $('wi-d').textContent = `${dv >= 0 ? '+' : '−'}${Math.abs(dv).toFixed(0)} pts`;
  };
  const reset = () => { const m = d.moments[mi]; ball = [Math.min(132, m.ball[0] + 32), Math.max(-34, Math.min(34, m.ball[1] < 0 ? m.ball[1] + 26 : m.ball[1] - 26))]; build(); paint(); };
  AFL.seg($('whatif-seg'), d.moments.map((m, i) => [i, m.name]), '0', (k) => { mi = +k; reset(); });
  AFL.fit(cv, 1.42, (c, w, h) => { ctx = c; W = w; H = h; v = AFL.view(w, h); if (!ball) reset(); else paint(); });
  const move = (e) => { const r = cv.getBoundingClientRect(), q = v.inv(e.clientX - r.left, e.clientY - r.top); const x = Math.max(1, Math.min(139, q[0])), hw = AFL.halfWidth(x) - 1; ball = [x, Math.max(-hw, Math.min(hw, q[1]))]; paint(); };
  cv.addEventListener('pointerdown', (e) => { cv.setPointerCapture(e.pointerId); move(e); });
  cv.addEventListener('pointermove', (e) => { if (e.buttons || e.pointerType === 'mouse') move(e); });
}

/* ---- kicks to space are kept: the Sharks analyst's own numbers (its figure code, run again) ---- */
async function figSpace() {
  const d = await AFL.load('space');
  const G = [['Power v Sharks', 'var(--a)'], ['strong v Sharks', 'var(--c)'], ['Sharks v Power', 'var(--b)']];
  const frame = (s, w, h, x0, x1, y1, xl, yl, yfmt) => {
    const m = { l: 44, r: 10, t: 10, b: 38 }, X = (v) => m.l + (v - x0) / (x1 - x0) * (w - m.l - m.r), Y = (v) => h - m.b - v / y1 * (h - m.t - m.b);
    for (let t = 0; t <= 4; t++) { const v = y1 * t / 4; line(s, m.l, Y(v), w - m.r, Y(v)); text(s, m.l - 7, Y(v) + 4, yfmt(v), { 'text-anchor': 'end', fill: 'var(--ink-3)', 'font-size': 12 }); }
    for (let v = Math.ceil(x0 / 5) * 5; v <= x1; v += 5) text(s, X(v), h - m.b + 17, v, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12 });
    line(s, X(0), m.t, X(0), h - m.b, 'var(--axis)', 1.2);
    text(s, (m.l + w - m.r) / 2, h - 3, xl, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12.5 });
    text(s, 0, 0, yl, { 'text-anchor': 'middle', fill: 'var(--ink-3)', 'font-size': 12.5, transform: `translate(11 ${(m.t + h - m.b) / 2}) rotate(-90)` });
    return { X, Y };
  };
  chart($('space-a'), 1.1, 280, (s, w, h) => {
    const { X, Y } = frame(s, w, h, -10, 20, 1, 'Space advantage at the kick (m)', 'Share of kicks kept', (v) => AFL.pct(v));
    let p = ''; d.curve.forEach((c, i) => { p += `${i ? 'L' : 'M'}${X(c.mid)} ${Y(c.kept)}`; });
    AFL.svg('path', { d: p, fill: 'none', stroke: 'var(--ink-2)', 'stroke-width': 2 }, s);
    for (const c of d.curve) {
      AFL.svg('circle', { cx: X(c.mid), cy: Y(c.kept), r: 4.5, fill: 'var(--ink-2)', stroke: 'var(--panel)', 'stroke-width': 2 }, s);
      hover(AFL.svg('circle', { cx: X(c.mid), cy: Y(c.kept), r: 12, fill: 'transparent' }, s), `${c.lo < -50 ? 'below ' + c.hi : c.hi > 50 ? 'above ' + c.lo : c.lo + ' to ' + c.hi} m: <b>${AFL.pct(c.kept)}</b> kept<br>${c.n.toLocaleString()} kicks`);
    }
  });
  chart($('space-b'), 1.1, 280, (s, w, h) => {
    const sh = G.map(([k]) => { const g = d.groups[k]; const t = g.hist.reduce((a, b) => a + b, 0); return g.hist.map((x) => x / t); });
    const top = Math.ceil(Math.max(...sh.flat()) * 10) / 10;
    const { X, Y } = frame(s, w, h, -15, 25, top, 'Space advantage at the kick (m)', 'Share of kicks', (v) => AFL.pct(v));
    const e = d.groups[G[0][0]].edges;
    G.forEach(([k, col], gi) => {
      let p = `M${X(e[0])} ${Y(0)}`; sh[gi].forEach((v, i) => { p += `L${X(e[i])} ${Y(v)}L${X(e[i + 1])} ${Y(v)}`; }); p += `L${X(e[e.length - 1])} ${Y(0)}`;
      AFL.svg('path', { d: p, fill: 'none', stroke: col, 'stroke-width': 2, 'stroke-linejoin': 'round' }, s);
    });
    const tip = AFL.svg('rect', { x: X(-15), y: 10, width: X(25) - X(-15), height: h - 48, fill: 'transparent' }, s);
    hover(tip, G.map(([k]) => { const g = d.groups[k]; return `${k.replace('strong', 'Eight strongest clubs')}: <b>${AFL.pct(g.le0)}</b> at 0 m or less, <b>${AFL.pct(g.over6)}</b> above 6 m (${g.n} kicks)`; }).join('<br>'));
  });
}

/* ---- 400 games, before and after (official grades: assets/results.json) ---- */
async function figWaffle() {
  const d = await AFL.load('results'); let club = 'sharks_open';
  const NAME = { giants: 'Giants', eagles: 'Eagles', sharks: 'Sharks, limit', sharks_open: 'Sharks, no limit' };
  const NOTE = { giants: '3 changes, 7 lines. A reliable gain of 16 points.', eagles: '3 changes of one line each. A gain of 28 points.',
    sharks: '3 changes, 6 lines. Up from 13 wins in 400, but still a loss in most games.', sharks_open: 'A new 545-line program. The Power beats the champion in 78% of games.' };
  const panel = (el, r) => {
    const seq = [...Array(r.w).fill('w'), ...Array(r.d).fill('d'), ...Array(r.l).fill('l')], col = { w: 'var(--a)', d: 'var(--axis)', l: 'var(--b)' };
    el.innerHTML = ''; const cols = 40, rows = 10, cell = 10, s = AFL.svg('svg', { viewBox: `0 0 ${cols * cell} ${rows * cell}`, role: 'img', 'aria-label': `${r.w} wins, ${r.d} draws, ${r.l} losses` }, el);
    seq.forEach((k, i) => { const x = Math.floor(i / rows), y = i % rows; const c = AFL.svg('circle', { cx: x * cell + cell / 2, cy: y * cell + cell / 2, r: 3.9, fill: col[k], opacity: AFL.reduced ? 1 : 0, style: `transition:opacity .25s ${i * 1.5}ms` }, s); requestAnimationFrame(() => requestAnimationFrame(() => c.setAttribute('opacity', 1))); });
  };
  const show = () => {
    const g = d.rows[club];
    panel($('wf-before'), g.before); panel($('wf-after'), g.plan);
    $('wf-before-n').textContent = `${g.before.w}–${g.before.l}–${g.before.d}`; $('wf-after-n').textContent = `${g.plan.w}–${g.plan.l}–${g.plan.d}`;
    $('wf-before-p').textContent = AFL.pct(g.before.score, 1); $('wf-after-p').textContent = AFL.pct(g.plan.score, 1);
    $('wf-note').textContent = NOTE[club];
  };
  AFL.seg($('wf-seg'), Object.entries(NAME), club, (k) => { club = k; show(); });
  show();                                   // the figure itself is already started when it comes near the screen
}

/* ---- the Power against the Sharks, before and after (assets/sharks_before.json, sharks_after.json) ---- */
async function figSharks() {
  const [b, a] = await Promise.all([AFL.load('sharks_before'), AFL.load('sharks_after')]); let r = null;
  const show = (k) => {
    if (r) { r.touched = true; r.pause(); }
    const cur = r = new Replay($('sharks-rp'), k === 'before' ? b : a, { autoplay: true, speed: 3, mode: 'value' });
    setTimeout(() => {                         // start at once if the figure is on screen (a new player gets no fresh visibility event)
      const q = $('sharks-rp').getBoundingClientRect();
      if (cur === r && !AFL.reduced && !cur.touched && q.bottom > 0 && q.top < innerHeight) cur.play();
    }, 60);
  };
  AFL.seg($('sharks-seg'), [['before', 'Before: the original Power'], ['after', "After: Claude's plan"]], 'before', show);
  show('before');
}

/* ---- the plan diff: each limited plan against the original Power (assets/results.json) ---- */
async function figDiff() {
  const d = await AFL.load('results'), host = $('diff');
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const show = (club) => {
    host.innerHTML = d.diffs[club].map((h, k) => {
      let o = h.old, n = h.new;
      const rows = h.lines.map(([t, x]) => {
        const no = t === '+' ? n++ : t === '-' ? o++ : (o++, n++);
        return `<div class="dl ${t === '+' ? 'add' : t === '-' ? 'del' : 'ctx'}"><span class="dn">${no}</span><span class="dm">${t === ' ' ? '' : t}</span><span class="dt">${esc(x)}</span></div>`;
      }).join('');
      return `<div class="dh"><p class="dnote"><b>Change ${k + 1}.</b> ${esc(h.note)}</p><div class="dcode">${rows}</div></div>`;
    }).join('');
  };
  AFL.seg($('diff-seg'), [['giants', 'Giants'], ['eagles', 'Eagles'], ['sharks', 'Sharks, limit']], 'eagles', show);
  show('eagles');
}

/* start each figure as it comes near the screen */
const FIGS = [['hero', figHero], ['pressure', figPressure], ['loop-fig', figLoop], ['climb', figClimb], ['futures', figFutures], ['net', figNetwork], ['map-label', figMap], ['cal-a', figCalib], ['whatif', figWhatif], ['space-a', figSpace], ['wf-seg', figWaffle], ['diff', figDiff], ['sharks-rp', figSharks], ['orders', async () => {
  const m = await AFL.load('match');
  const r = new Replay($('orders'), m, { speed: 1, start: 50, autoplay: true, mode: 'bare', legend: '' });
  AFL.seg($('orders-seg'), [['bare', 'What a camera sees'], ['orders', 'What the coach ordered']], 'bare', (k) => { r.mode = k; r.render(); });
}]];
for (const f of FIGS) {
  const go = () => { if (f.started) return; f.started = true; Promise.resolve().then(f[1]).catch((e) => console.error(f[0], e)); };
  f.go = go; AFL.whenSeen($(f[0]), go);
}
// start anything still waiting shortly after load, so the page's height settles and links to sections land in the right place
addEventListener('load', () => FIGS.forEach((f, i) => setTimeout(f.go, 900 + i * 120)));
