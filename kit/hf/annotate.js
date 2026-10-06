/* kit/hf/annotate.js — marker annotations over screenshots, code and windows: tapered pen strokes on perfect-freehand
 * (needs core.js and vendor/perfect-freehand.js; vendor.py copies it).
 *
 *   const an = HF.annotate(K, layer, { x, y, w, h, srcW: 1728, color: C.acc, avoid: [[x, y, w, h]] });
 *   // x, y, w, h: where the annotated thing sits in the layer; with srcW, boxes are in its own pixels (e.g. locate.py boxes)
 *   an.circle([x, y, w, h], t)              // a loose hand loop with an overshoot
 *   an.underline([x, y, w, h], t)           // under the box; { double: true } for a return stroke
 *   an.highlight([x, y, w, h], t)           // a highlighter sweep, multiply blend (keeps the text black)
 *   an.scribble([x, y, w, h], t)            // scratch it out
 *   an.strike([x, y, w, h], t)  an.box([x, y, w, h], t)
 *   an.arrow([x0, y0], [x1, y1], t, { bend: 0.25 })
 *   an.note(x, y, "split 2 ways", t, { size: 54, rotate: -4 })   // handwriting (Excalifont), written on
 *   every call takes { dur, color, size, seed, until } and returns its end time; an.clear(t) fades everything
 *
 * Exact: the point list of every mark is authored once (seeded wobble); at time t the mark is
 * getStroke(points.slice(0, n(t)), { last: n === all }) -> one filled outline path, recomputed in K.onFrame only while
 * it is drawing. No dash tricks (the stroke is a polygon), no randomness at render time.
 * Rule: never on a face. Pass the face box as `avoid` and any mark that touches it throws at build time.
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/annotate.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";
  HF.rng = HF.rng || function (seed) {
    let a = seed >>> 0;
    return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  HF.HAND = HF.HAND || '"Excalifont", "Caveat", cursive';
  HF.handFont = HF.handFont || function () {
    if (HF._hand) return; HF._hand = true;
    const s = document.createElement("style");
    s.textContent = '@font-face{font-family:"Excalifont";src:url("assets/fonts/Excalifont-Regular.woff2") format("woff2");font-display:block}' +
      '@font-face{font-family:"Caveat";src:url("assets/fonts/Caveat-700.ttf");font-weight:400 900;font-display:block}';
    document.head.append(s);
    if (document.fonts && document.fonts.load) { document.fonts.load('48px "Excalifont"'); document.fonts.load('48px "Caveat"'); }
  };
  HF.writeOn = HF.writeOn || function (tl, el, t, dur) {
    tl.fromTo(el, { clipPath: "inset(-20% 100% -20% -2%)" }, { clipPath: "inset(-20% -2% -20% -2%)", duration: dur, ease: "power1.inOut" }, t);
  };
  // perfect-freehand's outline polygon -> a smooth closed SVG path (the helper from its README)
  const outline = (pts) => {
    if (pts.length < 3) return "";
    let d = `M${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)} Q`;
    for (let i = 0; i < pts.length; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
      d += ` ${x0.toFixed(1)} ${y0.toFixed(1)} ${((x0 + x1) / 2).toFixed(1)} ${((y0 + y1) / 2).toFixed(1)}`;
    }
    return d + " Z";
  };
  const ease = (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);   // pen speed: slow in, slow out

  HF.annotate = function (K, parent, o = {}) {
    const PF = root.PerfectFreehand;
    if (!PF || !PF.getStroke) throw new Error("HF.annotate needs vendor/perfect-freehand.js: `npm i` at the repo root, then vendor.copy_assets(film)");
    HF.handFont();
    const tl = K.tl, Q = K.Q;
    const vx = o.x || 0, vy = o.y || 0, vw = o.w || K.width, vh = o.h || K.height, S = o.srcW ? vw / o.srcW : 1;
    // no z-index / opacity on the view: the highlighter must multiply with the screenshot under it, so neither the
    // view nor the highlighter svg may sit in its own stacking context (put annotated thing + view in one parent)
    const view = K.el(parent, `left:${vx}px;top:${vy}px;width:${vw}px;height:${vh}px;pointer-events:none` + (o.z != null ? `;z-index:${o.z}` : ""));
    const mkSvg = (css) => { const s = document.createElementNS(NS, "svg"); s.setAttribute("width", vw); s.setAttribute("height", vh);
      s.style.cssText = "position:absolute;left:0;top:0;overflow:visible;" + css; view.append(s); return s; };
    const hi = mkSvg("mix-blend-mode:multiply"), svg = mkSvg(""), pen = svg;  // highlighters under the pen marks
    const color = o.color || C.acc, size0 = o.size || 10;
    const avoid = (o.avoid || []).map((r) => r.map((v) => v * S));
    let seedN = (o.seed || 3) * 131, live = [];
    const all = [];
    const M = (b) => b.map((v) => v * S);                                    // source px -> layer px

    const check = (pts, pad, what) => {
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
      for (const [ax, ay, aw, ah] of avoid) if (x0 < ax + aw && x1 > ax && y0 < ay + ah && y1 > ay) throw new Error(`HF.annotate: the ${what} touches an avoid box (the face): move it`);
    };
    // pressure along a stroke: a quick press, a slight swell, a lift at the end
    const press = (n, r) => Array.from({ length: n }, (_, i) => { const u = i / Math.max(1, n - 1); return 0.42 + 0.22 * Math.sin(Math.PI * Math.min(1, u * 1.15)) + (r() - 0.5) * 0.05; });

    // a mark = one or more strokes drawn in order within [t, t + dur]; each stroke is [[x, y, p], ...] in layer px
    const mark = (strokes, t, a, kind) => {
      const r = HF.rng(a.seed || (seedN += 17));
      const dur = a.dur || 0.55, size = a.size || size0, col = a.color || (kind === "highlight" ? o.highlight || "#f7b49a" : color);
      const opts = kind === "highlight"
        ? { size, thinning: 0, smoothing: 0.6, streamline: 0.25, simulatePressure: false, start: { cap: false, taper: 0 }, end: { cap: false, taper: 0 } }
        : { size, thinning: 0.55, smoothing: 0.55, streamline: 0.35, simulatePressure: false, start: { taper: size * 2.2, cap: true }, end: { taper: size * 3.2, cap: true } };
      strokes.forEach((s) => check(s, size, kind));
      const lens = strokes.map((s) => s.reduce((L, p, i) => L + (i ? Math.hypot(p[0] - s[i - 1][0], p[1] - s[i - 1][1]) : 0), 0));
      const tot = lens.reduce((x, y) => x + y, 0) || 1, lift = strokes.length > 1 ? 0.06 : 0;
      const usable = Math.max(0.1, dur - lift * (strokes.length - 1));
      let acc = 0;
      const els = strokes.map((s, i) => {
        const p = document.createElementNS(NS, "path");
        p.setAttribute("fill", col); p.setAttribute("d", "");
        if (kind === "highlight") p.setAttribute("opacity", a.opacity || 0.95);
        (kind === "highlight" ? hi : pen).append(p);
        const a0 = t + (acc / tot) * usable + i * lift; acc += lens[i];
        const it = { p, pts: s.map((q, k) => [q[0], q[1], q[2] != null ? q[2] : 0.5]), t0: a0, d: Math.max(0.08, (lens[i] / tot) * usable), opts, last: -1 };
        live.push(it);
        return p;
      });
      if (a.until != null) tl.to(els, { opacity: 0, duration: 0.3, ease: "power2.in" }, Q(a.until));
      all.push(...els);
      if (o.sfx !== false && a.sfx !== false && kind !== "highlight") K.sfx(a.cue || "swish", t, a.cueDb || -30);
      return t + dur;
    };
    const render = (it, t) => {
      const p = Math.max(0, Math.min(1, (t - it.t0) / it.d));
      if (p === it.last) return;
      it.last = p;
      if (p <= 0) { it.p.setAttribute("d", ""); return; }
      const N = it.pts.length, n = ease(p) * (N - 1), i = Math.floor(n), f = n - i;
      const sl = it.pts.slice(0, i + 1);
      if (f > 1e-3 && i + 1 < N) { const A = it.pts[i], B = it.pts[i + 1]; sl.push([A[0] + (B[0] - A[0]) * f, A[1] + (B[1] - A[1]) * f, A[2] + (B[2] - A[2]) * f]); }
      it.p.setAttribute("d", outline(PF.getStroke(sl, { ...it.opts, last: p >= 1 })));
    };
    K.onFrame((t) => { for (const it of live) render(it, t); });

    const an = { view, svg };
    // ---- point generators (layer px), seeded wobble
    an.circle = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 29)), pad = a.pad != null ? a.pad : 16;
      const cx = x + w / 2, cy = y + h / 2, rx = w / 2 + pad + w * 0.06, ry = h / 2 + pad + h * 0.12, rot = (r() - 0.5) * 0.12;
      const a0 = -Math.PI * (0.62 + r() * 0.1), sweep = Math.PI * 2 + 0.55 + r() * 0.25, n = 72, ph = r() * 6.28;
      const pr = press(n, r);
      const pts = Array.from({ length: n }, (_, k) => {
        const u = k / (n - 1), th = a0 + sweep * u, g = 1 + 0.045 * Math.sin(th * 2 + ph) + u * 0.07;      // drifts outward: the overlap never lands on itself
        const ex = rx * g * Math.cos(th), ey = ry * g * Math.sin(th);
        return [cx + ex * Math.cos(rot) - ey * Math.sin(rot), cy + ex * Math.sin(rot) + ey * Math.cos(rot), pr[k]];
      });
      return mark([pts], t, { dur: 0.6, ...a }, "circle");
    };
    an.underline = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 31)), yb = y + h + (a.gap != null ? a.gap : 8), n = 28;
      const bow = (r() - 0.3) * 6, sl = (r() - 0.6) * 8, pr = press(n, r);
      const line = (x0, x1, dy, rv) => Array.from({ length: n }, (_, k) => { const u = k / (n - 1), q = rv ? 1 - u : u;
        return [x0 + (x1 - x0) * u, yb + dy + sl * q + bow * Math.sin(Math.PI * q) + Math.sin(u * 9 + dy) * 0.8, pr[k]]; });
      const s = [line(x - 8, x + w + 10, 0, false)];
      if (a.double) s.push(line(x + w + 4, x + 6, 11, true));
      return mark(s, t, { dur: a.double ? 0.55 : 0.35, ...a }, "underline");
    };
    an.highlight = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 37)), n = 24, cy = y + h / 2;
      const pts = Array.from({ length: n }, (_, k) => { const u = k / (n - 1); return [x - 6 + (w + 12) * u, cy + (r() - 0.5) * 1.6 - u * 2, 0.5]; });
      return mark([pts], t, { size: h * 1.12, dur: 0.45, ...a }, "highlight");
    };
    an.scribble = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 41)), loops = a.loops || Math.max(4, Math.round(w / (h * 0.55)));
      const pts = [];
      for (let k = 0; k <= loops * 2; k++) {                                 // a zig-zag with soft turns, slightly slanted
        const u = k / (loops * 2), top = k % 2 === 0;
        const px = x - 4 + (w + 8) * u + (r() - 0.5) * 6, py = top ? y + h * (0.05 + r() * 0.12) : y + h * (0.88 + r() * 0.12);
        if (k) { const [qx, qy] = pts[pts.length - 1]; for (let j = 1; j < 4; j++) pts.push([qx + (px - qx) * (j / 4), qy + (py - qy) * (j / 4), 0.55]); }
        pts.push([px, py, 0.6]);
      }
      return mark([pts], t, { dur: 0.6, size: (a.size || size0) * 0.9, ...a }, "scribble");
    };
    an.strike = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 43)), n = 20, pr = press(n, r);
      const pts = Array.from({ length: n }, (_, k) => { const u = k / (n - 1); return [x - 6 + (w + 12) * u, y + h * 0.55 - u * 4 + Math.sin(u * 7) * 1.2, pr[k]]; });
      return mark([pts], t, { dur: 0.3, ...a }, "strike");
    };
    an.box = (box, t, a = {}) => {
      const [x, y, w, h] = M(box), r = HF.rng(a.seed || (seedN += 47)), p = a.pad != null ? a.pad : 12, j = () => (r() - 0.5) * 6;
      const c = [[x - p + j(), y - p + j()], [x + w + p + j(), y - p + j()], [x + w + p + j(), y + h + p + j()], [x - p + j(), y + h + p + j()], [x - p + 14 + j(), y - p - 4 + j()]];
      const pts = [];
      for (let k = 0; k < c.length - 1; k++) for (let i = 0; i < 10; i++) { const u = i / 10; pts.push([c[k][0] + (c[k + 1][0] - c[k][0]) * u, c[k][1] + (c[k + 1][1] - c[k][1]) * u, 0.55]); }
      return mark([pts], t, { dur: 0.7, ...a }, "box");
    };
    an.arrow = (from, to, t, a = {}) => {
      const [x0, y0] = M(from), [x1, y1] = M(to), r = HF.rng(a.seed || (seedN += 53)), n = 30, bend = a.bend != null ? a.bend : 0.22;
      const L = Math.hypot(x1 - x0, y1 - y0) || 1, mx = (x0 + x1) / 2 - ((y1 - y0) / L) * bend * L, my = (y0 + y1) / 2 + ((x1 - x0) / L) * bend * L;
      const c = [2 * mx - (x0 + x1) / 2, 2 * my - (y0 + y1) / 2], pr = press(n, r);
      const q = (u) => [(1 - u) ** 2 * x0 + 2 * (1 - u) * u * c[0] + u * u * x1, (1 - u) ** 2 * y0 + 2 * (1 - u) * u * c[1] + u * u * y1];
      const shaft = Array.from({ length: n }, (_, k) => [...q(k / (n - 1)), pr[k]]);
      const b = q(0.88), ang = Math.atan2(y1 - b[1], x1 - b[0]), hl = a.head || 34, sp = 0.5 + (r() - 0.5) * 0.12;
      const head = [];
      for (let i = 0; i <= 8; i++) head.push([x1 - hl * Math.cos(ang + sp) * (1 - i / 8), y1 - hl * Math.sin(ang + sp) * (1 - i / 8), 0.6]);
      for (let i = 1; i <= 8; i++) head.push([x1 - hl * Math.cos(ang - sp) * (i / 8), y1 - hl * Math.sin(ang - sp) * (i / 8), 0.6 - i * 0.03]);
      return mark([shaft, head], t, { dur: 0.5, ...a }, "arrow");
    };
    an.note = (x, y, text, t, a = {}) => {
      const [lx, ly] = M([x, y]), size = a.size || 54, est = text.length * size * 0.48;
      check([[lx, ly], [lx + (a.align === "right" ? -est : a.align === "center" ? est / 2 : est), ly + size * 1.1]], 0, "note");
      const d = K.el(view, `left:${a.align === "right" ? lx - 900 : a.align === "center" ? lx - 450 : lx}px;top:${ly}px;width:900px;text-align:${a.align || "left"};` +
        `font:400 ${size}px/1.05 ${HF.HAND};color:${a.color || color};white-space:pre;rotate:${a.rotate != null ? a.rotate : -3}deg;opacity:0`, HF.esc(text));
      if (a.halo !== false) d.style.textShadow = "0 0 6px rgba(255,255,255,.95), 0 0 2px #fff";
      const dur = a.dur || Math.min(0.9, 0.15 + text.length * 0.04);
      tl.set(d, { opacity: 1 }, Q(t)); HF.writeOn(tl, d, Q(t), dur);
      if (a.until != null) tl.to(d, { opacity: 0, duration: 0.3 }, Q(a.until));
      all.push(d);
      return t + dur;
    };
    an.clear = (t, dur = 0.3) => { tl.to(all.slice(), { opacity: 0, duration: dur, ease: "power2.in" }, Q(t)); return an; };
    return an;
  };
})(typeof window !== "undefined" ? window : globalThis);
