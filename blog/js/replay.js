// The match replay. One real game, recorded by the engine, drawn three ways: with the network's rating, with the
// coach's orders, or with the network's layers lighting up.
class Replay {
  constructor(root, m, opts = {}) {
    this.root = root; this.m = m; this.o = { speed: 3, mode: 'value', aspect: 1.42, ...opts };
    this.t = this.o.start ?? 0; this.playing = false; this.seen = false; this.speed = this.o.speed; this.mode = this.o.mode; this.trail = [];
    this.pad = this.m.pids.length * 2;
    root.innerHTML = `
      <div class="rp-head"><div class="rp-score"></div><div class="rp-clock"></div></div>
      <canvas class="rp-pitch" aria-label="Replay of a simulated match, seen from above"></canvas>
      <canvas class="rp-strip" aria-label="The network's rating over the game. Drag to move through the match"></canvas>
      <div class="rp-ctl"><button class="rp-btn" type="button" aria-label="Play or pause">▶</button><div class="spd"></div><div class="rp-legend"></div><div class="rp-read"></div></div>`;
    this.pitch = root.querySelector('.rp-pitch'); this.strip = root.querySelector('.rp-strip');
    this.btn = root.querySelector('.rp-btn'); this.scoreEl = root.querySelector('.rp-score'); this.clock = root.querySelector('.rp-clock'); this.read = root.querySelector('.rp-read');
    root.querySelector('.rp-legend').innerHTML = this.o.legend ?? `<span><i style="background:var(--night-a)"></i>${m.a}</span><span><i style="background:var(--night-b)"></i>${m.b}</span>`;
    AFL.seg(root.querySelector('.spd'), [['1', '1×'], ['3', '3×'], ['6', '6×']], String(this.speed), (k) => { this.speed = +k; });
    this.btn.onclick = () => this.toggle();
    this.drawPitch = AFL.fit(this.pitch, this.o.aspect, (c, w, h) => { this.pc = c; this.pw = w; this.ph = h; this.v = AFL.view(w, h); this.bg = null; this.render(); });
    AFL.fit(this.strip, this.o.stripAspect ?? 13, (c, w, h) => { this.sc = c; this.sw = w; this.sh = h; this.sbg = null; this.renderStrip(); });
    const seek = (e) => { const r = this.strip.getBoundingClientRect(); this.t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * m.seconds; this.trail = []; this.render(); this.renderStrip(); };
    this.strip.style.cursor = 'pointer';
    this.strip.addEventListener('pointerdown', (e) => { this.strip.setPointerCapture(e.pointerId); seek(e); this.strip.onpointermove = seek; });
    this.strip.addEventListener('pointerup', () => { this.strip.onpointermove = null; });
    AFL.visible(root, (s) => { this.seen = s; if (s && this.o.autoplay && !AFL.reduced && !this.touched) this.play(); if (!s && this.playing) this.pause(true); else if (s && this.resume) this.play(); });
  }

  toggle() { this.touched = true; this.playing ? this.pause() : this.play(); }
  play() {
    if (this.playing) return; this.playing = true; this.resume = false; this.btn.textContent = '❚❚'; let last = performance.now();
    const step = (now) => {
      if (!this.playing) return;
      this.t += Math.min(.1, (now - last) / 1000) * this.speed; last = now;
      if (this.t >= this.m.seconds - .2) { this.t = 0; this.trail = []; }
      this.render(); this.renderStrip(); requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  pause(auto) { this.playing = false; this.resume = !!auto; this.btn.textContent = '▶'; }

  at(t) {                                                                  // interpolated positions at time t
    const m = this.m, f = Math.max(0, Math.min(m.n - 1.001, (t - m.t0) / m.dt)), i = Math.floor(f), k = f - i, n = this.pad, P = [];
    for (let j = 0; j < n; j++) P.push((m.p[i * n + j] * (1 - k) + m.p[(i + 1) * n + j] * k) / 10);
    const a = m.ball[i], b = m.ball[i + 1];
    return { P, ball: [(a[0] * (1 - k) + b[0] * k) / 10, (a[1] * (1 - k) + b[1] * k) / 10, (a[2] * (1 - k) + b[2] * k) / 10], state: m.state[i], holder: m.holder[i], i };
  }
  dec(t) {                                                                 // index of the latest decision at or before t
    const v = this.m.value; let lo = 0, hi = v.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; v[mid][0] <= t ? (lo = mid) : (hi = mid - 1); }
    return lo;
  }
  value(t) { const v = this.m.value, i = this.dec(t), a = v[i], b = v[Math.min(i + 1, v.length - 1)]; const k = b[0] > a[0] ? Math.min(1, (t - a[0]) / (b[0] - a[0])) : 0; return a[1] + (b[1] - a[1]) * k; }

  tally(t) {
    const s = { A: [0, 0], B: [0, 0] };
    for (const e of this.m.scores) if (e.t <= t) s[e.team][e.pts >= 6 ? 0 : 1]++;
    return s;
  }

  render() {
    if (!this.pc) return;
    const c = this.pc, v = this.v;
    if (!this.bg) {
      this.bg = document.createElement('canvas'); this.bg.width = this.pitch.width; this.bg.height = this.pitch.height;
      const b = this.bg.getContext('2d'), d = this.pitch.width / this.pw; b.setTransform(d, 0, 0, d, 0, 0); AFL.drawGround(b, v);
    }
    c.clearRect(0, 0, this.pw, this.ph); c.drawImage(this.bg, 0, 0, this.pw, this.ph);
    const s = this.at(this.t), A = '#4b97ef', B = '#f0733f', di = this.dec(this.t), r = Math.max(3.4, v.s * 1.25);

    if (this.mode === 'orders') {                                          // what each player has been told
      const o = this.m.orders[Math.min(di, this.m.orders.length - 1)].o;
      c.lineWidth = 1.1;
      o.forEach((x, i) => {
        if (!x || x[1] === null) return;
        const p = v.p(s.P[i * 2], s.P[i * 2 + 1]), q = v.p(x[1], x[2]);
        c.strokeStyle = i < 8 ? 'rgba(75,151,239,.8)' : 'rgba(240,115,63,.8)';
        c.setLineDash(x[3] === 'j' ? [3, 3] : []);
        c.beginPath(); c.moveTo(p[0], p[1]); c.lineTo(q[0], q[1]); c.stroke();
        c.setLineDash([]); c.fillStyle = c.strokeStyle; c.beginPath(); c.arc(q[0], q[1], 2.1, 0, 7); c.fill();
      });
    }
    if (this.mode === 'network') {                                         // halos: how much each player moves the rating
      const sens = this.m.sens, n = this.m.pids.length;
      for (let i = 0; i < n; i++) {
        const k = sens[di * n + i] / 99, p = v.p(s.P[i * 2], s.P[i * 2 + 1]);
        c.fillStyle = `rgba(255,255,255,${.04 + .3 * k})`; c.beginPath(); c.arc(p[0], p[1], r + 1 + k * r * 2.6, 0, 7); c.fill();
      }
    }
    this.trail.push([s.ball[0], s.ball[1]]); if (this.trail.length > 26) this.trail.shift();
    if (this.trail.length > 1) {
      for (let i = 1; i < this.trail.length; i++) {
        const a = v.p(...this.trail[i - 1]), b = v.p(...this.trail[i]);
        if (Math.hypot(a[0] - b[0], a[1] - b[1]) > 60) continue;
        c.strokeStyle = `rgba(255,255,255,${(i / this.trail.length) * .5})`; c.lineWidth = 1.5; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke();
      }
    }
    this.m.pids.forEach((id, i) => {
      const p = v.p(s.P[i * 2], s.P[i * 2 + 1]);
      c.fillStyle = 'rgba(0,0,0,.35)'; c.beginPath(); c.arc(p[0] + .8, p[1] + 1.2, r, 0, 7); c.fill();
      c.fillStyle = i < 8 ? A : B; c.beginPath(); c.arc(p[0], p[1], r, 0, 7); c.fill();
      if (i === s.holder) { c.strokeStyle = '#fff'; c.lineWidth = 1.8; c.beginPath(); c.arc(p[0], p[1], r + 2.2, 0, 7); c.stroke(); }
    });
    const bp = v.p(s.ball[0], s.ball[1]), lift = s.ball[2] * v.s * .35;
    if (s.ball[2] > .3) { c.fillStyle = 'rgba(0,0,0,.4)'; c.beginPath(); c.arc(bp[0], bp[1], r * .55, 0, 7); c.fill(); }
    c.fillStyle = '#ffe9a8'; c.beginPath(); c.ellipse(bp[0], bp[1] - lift, r * .8 + s.ball[2] * .06, r * .55 + s.ball[2] * .04, -.5, 0, 7); c.fill();

    const sc = this.tally(this.t), row = (k, name, col) => `<span><i style="background:${col}"></i>${name}</span><span class="pts">${sc[k][0] * 6 + sc[k][1]}</span><span>${sc[k][0]}.${sc[k][1]}</span>`;
    const html = row('A', this.m.a, A) + '<span style="opacity:.4">·</span>' + row('B', this.m.b, B);
    if (html !== this._s) { this.scoreEl.innerHTML = html; this._s = html; }
    const mm = Math.floor(this.t / 60), ss = Math.floor(this.t % 60);
    this.clock.textContent = `${mm}:${String(ss).padStart(2, '0')} of 4:00`;
    const val = this.value(this.t);
    if (this.mode === 'value' || this.mode === 'network') this.read.textContent = `Next goal: ${this.m.a} ${AFL.pct(val)}`;
    if (this.mode === 'orders' || this.mode === 'bare') this.read.textContent = '';
    this.o.onframe && this.o.onframe(this, di, val);
  }

  renderStrip() {
    if (!this.sc) return;
    const c = this.sc, w = this.sw, h = this.sh, m = this.m, x = (t) => (t / m.seconds) * w, y = (v) => h - 4 - v * (h - 8);
    if (!this.sbg) {                                                       // the rating over the game is fixed: draw it once
      const b = document.createElement('canvas'), d = this.strip.width / w; b.width = this.strip.width; b.height = this.strip.height;
      const g = b.getContext('2d'); g.setTransform(d, 0, 0, d, 0, 0);
      g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(0, 0, w, h);
      for (const [col, above] of [['rgba(75,151,239,.55)', true], ['rgba(240,115,63,.55)', false]]) {
        g.save(); g.beginPath(); above ? g.rect(0, 0, w, y(.5)) : g.rect(0, y(.5), w, h); g.clip();
        g.beginPath(); g.moveTo(0, y(.5)); m.value.forEach(([t, v]) => g.lineTo(x(t), y(v))); g.lineTo(w, y(.5)); g.closePath(); g.fillStyle = col; g.fill(); g.restore();
      }
      g.strokeStyle = 'rgba(255,255,255,.3)'; g.lineWidth = 1; g.beginPath(); g.moveTo(0, y(.5)); g.lineTo(w, y(.5)); g.stroke();
      for (const e of m.scores) if (e.pts >= 6) { g.fillStyle = e.team === 'A' ? '#4b97ef' : '#f0733f'; g.fillRect(x(e.t) - 1, 0, 2, h); g.beginPath(); g.arc(x(e.t), e.team === 'A' ? 4 : h - 4, 3.2, 0, 7); g.fill(); }
      this.sbg = b;
    }
    c.clearRect(0, 0, w, h); c.drawImage(this.sbg, 0, 0, w, h);
    c.fillStyle = '#fff'; c.fillRect(x(this.t) - 1, 0, 2, h);
  }
  relayout() { this.bg = null; this.sbg = null; this.render(); this.renderStrip(); }
}
