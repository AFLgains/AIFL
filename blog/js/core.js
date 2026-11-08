// Shared pieces: data loading, the oval, colours, canvas sizing, tooltips, segmented controls.
const AFL = (() => {
  const cache = {};
  const load = (name) => (cache[name] ||= fetch(`assets/${name}.json`).then((r) => r.json()));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // the ground, in metres: x 0..140 goal line to goal line, y -50..50. Same oval as the engine.
  const G = { L: 140, W: 100, goal: 3.2, behind: 9.6, sq: 50, arc: 42.42, gsq: 9 };
  G.a = (G.L / 2) / Math.sqrt(1 - (G.behind / (G.W / 2)) ** 2);
  const halfWidth = (x) => { const u = (x - G.L / 2) / G.a; return (G.W / 2) * Math.sqrt(Math.max(0, 1 - u * u)); };

  function ovalPath(ctx, v) {
    ctx.beginPath();
    for (let i = 0; i <= 80; i++) { const x = (G.L * i) / 80; const p = v.p(x, halfWidth(x)); i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]); }
    for (let i = 80; i >= 0; i--) { const x = (G.L * i) / 80; const p = v.p(x, -halfWidth(x)); ctx.lineTo(p[0], p[1]); }
    ctx.closePath();
  }

  // world-to-pixel view for a canvas of w x h, showing x0..x1, y0..y1
  function view(w, h, box = { x0: -3, x1: 143, y0: -53, y1: 53 }) {
    const s = Math.min(w / (box.x1 - box.x0), h / (box.y1 - box.y0));
    const ox = (w - s * (box.x1 - box.x0)) / 2 - s * box.x0, oy = (h - s * (box.y1 - box.y0)) / 2 + s * box.y1;
    return { s, p: (x, y) => [ox + s * x, oy - s * y], inv: (px, py) => [(px - ox) / s, (oy - py) / s] };
  }

  function drawGround(ctx, v, { turf = true } = {}) {
    if (turf) {
      ctx.save(); ovalPath(ctx, v); ctx.clip();
      ctx.fillStyle = '#12261c'; ctx.fillRect(0, 0, 9999, 9999);
      for (let i = 0; i < 14; i += 2) {                                    // mown stripes
        const a = v.p(i * 10, 60), b = v.p((i + 1) * 10, -60);
        ctx.fillStyle = '#152c20'; ctx.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
      }
      ctx.restore();
    }
    ctx.strokeStyle = 'rgba(255,255,255,.34)'; ctx.lineWidth = 1.2;
    ovalPath(ctx, v); ctx.stroke();
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(255,255,255,.2)';
    const sq = G.sq / 2, c = v.p(G.L / 2 - sq, sq), d = v.p(G.L / 2 + sq, -sq);
    ctx.strokeRect(c[0], c[1], d[0] - c[0], d[1] - c[1]);
    const m = v.p(G.L / 2, 0);
    ctx.beginPath(); ctx.arc(m[0], m[1], 3 * v.s, 0, 7); ctx.stroke();
    ctx.save(); ovalPath(ctx, v); ctx.clip();
    for (const gx of [0, G.L]) {                                           // the fifties
      const g = v.p(gx, 0); ctx.beginPath(); ctx.arc(g[0], g[1], G.arc * v.s, 0, 7); ctx.stroke();
      const dir = gx ? -1 : 1, q = v.p(gx, G.goal), r = v.p(gx + dir * G.gsq, -G.goal);
      ctx.strokeRect(q[0], q[1], r[0] - q[0], r[1] - q[1]);
    }
    ctx.restore();
    ctx.lineWidth = 2;
    for (const gx of [0, G.L]) for (const [py, col] of [[G.goal, '#fff'], [-G.goal, '#fff'], [G.behind, 'rgba(255,255,255,.55)'], [-G.behind, 'rgba(255,255,255,.55)']]) {
      const p = v.p(gx, py); ctx.fillStyle = col; ctx.beginPath(); ctx.arc(p[0], p[1], Math.max(1.6, v.s * .55), 0, 7); ctx.fill();
    }
  }

  // size a canvas to its box at device resolution, and call back on every change
  function fit(canvas, aspect, draw, maxVh = .68) {
    const ctx = canvas.getContext('2d');
    const go = () => {
      const w = canvas.clientWidth || canvas.parentElement.clientWidth; if (!w) return;
      const h = Math.min(Math.round(w / aspect), Math.max(220, Math.round(innerHeight * maxVh))), dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.style.height = h + 'px';
      if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw(ctx, w, h);
    };
    new ResizeObserver(go).observe(canvas.parentElement);
    go();
    return go;
  }

  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
  const mix = (a, b, t) => { const p = hex(a), q = hex(b); return `rgb(${p.map((x, i) => Math.round(x + (q[i] - x) * t)).join(',')})`; };
  // diverging: orange (B / they score next), neutral, blue (A / we score next)
  const MID = '#2b312d', POS = '#4b97ef', NEG = '#f0733f';
  const diverge = (v, spread = .3) => { const t = Math.max(-1, Math.min(1, (v - .5) / spread)); return t >= 0 ? mix(MID, POS, t) : mix(MID, NEG, -t); };
  const divergeRGB = (v, spread = .3) => { const t = Math.max(-1, Math.min(1, (v - .5) / spread)), p = hex(MID), q = hex(t >= 0 ? POS : NEG), k = Math.abs(t); return p.map((x, i) => x + (q[i] - x) * k); };

  const tip = () => document.getElementById('tip');
  function showTip(html, x, y) {
    const t = tip(); t.innerHTML = html; t.style.opacity = 1;
    const r = t.getBoundingClientRect();
    t.style.left = Math.max(6, Math.min(innerWidth - r.width - 6, x + 12)) + 'px';
    t.style.top = Math.max(6, y - r.height - 10) + 'px';
  }
  const hideTip = () => { tip().style.opacity = 0; };

  function seg(el, options, value, on) {
    el.classList.add('seg'); el.setAttribute('role', 'group');
    el.innerHTML = options.map(([k, label]) => `<button type="button" data-k="${k}" aria-pressed="${String(k) === String(value)}">${label}</button>`).join('');
    el.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      el.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
      on(b.dataset.k);
    });
  }

  // run a callback once a figure is near the screen, and report visibility for animation loops
  function whenSeen(el, fn) {
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: '500px' });
    io.observe(el);
  }
  function visible(el, cb) { new IntersectionObserver((es) => cb(es[es.length - 1].isIntersecting), { threshold: .15 }).observe(el); }

  const svg = (tag, attrs = {}, parent) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const k in attrs) n.setAttribute(k, attrs[k]); parent && parent.appendChild(n); return n; };
  const pct = (x, d = 0) => (x * 100).toFixed(d) + '%';

  return { load, css, reduced, G, halfWidth, ovalPath, view, drawGround, fit, mix, diverge, divergeRGB, showTip, hideTip, seg, whenSeen, visible, svg, pct };
})();
