/* kit/hf/sketch.js — hand-drawn (Excalidraw-look) diagrams that draw themselves, on rough.js (needs core.js,
 * vendor/rough.js and, for the pen, vendor/DrawSVGPlugin.min.js; vendor.py copies both).
 *
 *   const sk = HF.sketch(K, layer, { x: 60, y: 420, w: 960, h: 1060, seed: 7 });
 *   sk.node("read", { x: 480, y: 140, w: 290, h: 140, label: "Read", fill: C.accTint })      // x, y = centre (view px)
 *   sk.arrow("a1", "read", "plan", { bend: 0.25 })                                           // node ids or [x, y]
 *   sk.text("t", 480, 520, "until it passes", { size: 40, color: C.ink2 })
 *   sk.ring("r", "check", { color: C.acc })                                                  // an emphasis loop around a node
 *   sk.draw("read", 0.2); sk.draw(["a1", "plan"], 0.8, { stagger: 0.35 })                   // strokes draw, fills fade, labels write
 *   sk.boil(3.6, 6.2)                                                                       // 12 fps line boil while it holds still
 *   sk.hide(["read", "plan"], 6.2)  /  sk.show(a, b)
 *
 * Exact: every shape is generated once with a fixed rough.js seed (seed, seed+1000, seed+2000 for the 3 boil variants);
 * strokes draw with DrawSVG tweens on the timeline, fills only fade, and the boil picks variant floor(t*12) % 3 in a
 * K.onFrame. No randomness at render time.
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/sketch.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";

  // ---- shared by the v7 style modules (sketch, annotate, scribble, collage): defined once, whichever loads first
  HF.rng = HF.rng || function (seed) {                                        // mulberry32: a seeded PRNG for build time only
    let a = seed >>> 0;
    return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  HF.HAND = '"Excalifont", "Caveat", cursive';
  HF.handFont = HF.handFont || function () {                                   // @font-face once + make fonts.ready wait for it
    if (HF._hand) return; HF._hand = true;
    const s = document.createElement("style");
    s.textContent = '@font-face{font-family:"Excalifont";src:url("assets/fonts/Excalifont-Regular.woff2") format("woff2");font-display:block}' +
      '@font-face{font-family:"Caveat";src:url("assets/fonts/Caveat-700.ttf");font-weight:400 900;font-display:block}';
    document.head.append(s);
    if (document.fonts && document.fonts.load) { document.fonts.load('48px "Excalifont"'); document.fonts.load('48px "Caveat"'); }
  };
  HF.drawOn = HF.drawOn || function (tl, path, t, dur, ease) {               // the pen: DrawSVG when vendored, else a dash
    if (root.DrawSVGPlugin) { gsap.registerPlugin(root.DrawSVGPlugin); return tl.fromTo(path, { drawSVG: "0% 0%" }, { drawSVG: "0% 100%", duration: dur, ease: ease || "power1.inOut" }, t); }
    const len = path.getTotalLength() + 1;
    path.style.strokeDasharray = `${len} ${len}`;
    return tl.fromTo(path, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: dur, ease: ease || "power1.inOut" }, t);
  };
  HF.svg = HF.svg || function (parent, w, h, css = "") {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("width", w); s.setAttribute("height", h); s.setAttribute("viewBox", `0 0 ${w} ${h}`);
    s.style.cssText = "position:absolute;left:0;top:0;overflow:visible;" + css; parent.append(s); return s;
  };
  HF.writeOn = HF.writeOn || function (tl, el, t, dur) {                     // handwriting reveal: a left-to-right wipe
    tl.fromTo(el, { clipPath: "inset(-20% 100% -20% -2%)" }, { clipPath: "inset(-20% -2% -20% -2%)", duration: dur, ease: "power1.inOut" }, t);
  };

  HF.sketch = function (K, parent, o = {}) {
    if (!root.rough) throw new Error("HF.sketch needs vendor/rough.js: `npm i` at the repo root, then vendor.copy_assets(film)");
    HF.handFont();
    const tl = K.tl, Q = K.Q;
    const vx = o.x || 0, vy = o.y || 0, vw = o.w || K.width, vh = o.h || K.height;
    const view = K.el(parent, `left:${vx}px;top:${vy}px;width:${vw}px;height:${vh}px`);
    const svg = HF.svg(view, vw, vh);
    const gen = root.rough.generator();
    const ink = o.stroke || (o.dark ? "#f3eee6" : C.ink);
    const base = { roughness: o.roughness != null ? o.roughness : 1.25, bowing: o.bowing != null ? o.bowing : 1, stroke: ink, strokeWidth: o.strokeWidth || 3.4,
      fillStyle: o.fillStyle || "hachure", hachureGap: o.hachureGap || 12, hachureAngle: -41, fillWeight: o.fillWeight || 2.2 };
    let nextSeed = (o.seed || 1) * 7919;
    const items = {}, list = [], boils = [];

    // one shape -> 3 seeded variants, each a <g> of stroke paths (drawn) and fill paths (faded)
    const build = (make, opt) => {
      const seed = opt.seed || (nextSeed += 101);
      const g = document.createElementNS(NS, "g"); svg.append(g);
      const vars = [0, 1, 2].map((k) => {
        const vg = document.createElementNS(NS, "g"); g.append(vg);
        const strokes = [], fills = [];
        const ds = [].concat(make({ ...base, ...opt, seed: seed + k * 1000 }));
        ds.forEach((dr) => dr.sets.forEach((set) => {
          const p = document.createElementNS(NS, "path"), O = dr.options;
          p.setAttribute("d", gen.opsToPath(set, 2));
          if (set.type === "path") { p.setAttribute("fill", "none"); p.setAttribute("stroke", O.stroke); p.setAttribute("stroke-width", O.strokeWidth); strokes.push(p); }
          else if (set.type === "fillSketch") { p.setAttribute("fill", "none"); p.setAttribute("stroke", O.fill); p.setAttribute("stroke-width", O.fillWeight); fills.push(p); }
          else { p.setAttribute("fill", O.fill); p.setAttribute("stroke", "none"); fills.push(p); }
          p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round");
          vg.append(p);
        }));
        if (k) vg.style.display = "none";
        return { g: vg, strokes, fills };
      });
      tl.set(g, { autoAlpha: 0 }, 0);
      return { g, vars, v: 0 };
    };
    const label = (x, y, text, opt) => {
      if (!text) return null;
      const size = opt.size || 52;
      const d = K.el(view, `left:${x - 400}px;top:${y - size * 0.62}px;width:800px;text-align:${opt.align || "center"};font:400 ${size}px/1.1 ${HF.HAND};color:${opt.color || ink};white-space:pre;opacity:0` +
        (opt.rotate ? `;rotate:${opt.rotate}deg` : ""), HF.esc(text));
      if (opt.align === "left") d.style.left = x + "px";
      d._rot = opt.rotate || 0;
      return d;
    };
    const add = (id, it) => { if (items[id]) throw new Error("HF.sketch: duplicate id " + id); it.id = id; items[id] = it; list.push(it); return it; };

    const sk = { view, svg, items };
    sk.node = (id, n) => {
      const w = n.w || 280, h = n.h || 130, x0 = n.x - w / 2, y0 = n.y - h / 2, shape = n.shape || "rect";
      const opt = { fill: n.fill, fillStyle: n.fillStyle || base.fillStyle, stroke: n.stroke || ink, strokeWidth: n.strokeWidth || base.strokeWidth, seed: n.seed, roughness: n.roughness != null ? n.roughness : base.roughness };
      if (!n.fill) delete opt.fill;
      const r = Math.min(n.radius != null ? n.radius : 22, w / 4, h / 4);
      const make = (O) => shape === "ellipse" ? gen.ellipse(n.x, n.y, w, h, O)
        : shape === "diamond" ? gen.polygon([[n.x, y0], [x0 + w, n.y], [n.x, y0 + h], [x0, n.y]], O)
        : r > 0 ? gen.path(`M${x0 + r} ${y0} L${x0 + w - r} ${y0} Q${x0 + w} ${y0} ${x0 + w} ${y0 + r} L${x0 + w} ${y0 + h - r} Q${x0 + w} ${y0 + h} ${x0 + w - r} ${y0 + h} ` +
          `L${x0 + r} ${y0 + h} Q${x0} ${y0 + h} ${x0} ${y0 + h - r} L${x0} ${y0 + r} Q${x0} ${y0} ${x0 + r} ${y0} Z`, O)
        : gen.rectangle(x0, y0, w, h, O);
      return add(id, { kind: "node", ...build(make, opt), n: { ...n, w, h, shape }, label: label(n.x, n.y + (n.labelDy || 0), n.label, { size: n.size || 56, color: n.color }) });
    };
    const cen = (a) => (Array.isArray(a) ? { x: a[0], y: a[1], w: 0, h: 0, shape: "pt" } : items[a] ? items[a].n : null);
    const edge = (n, tx, ty, gap) => {                                      // boundary point of node n toward (tx, ty), plus a gap
      const dx = tx - n.x, dy = ty - n.y, L = Math.hypot(dx, dy) || 1;
      if (n.shape === "pt") return [n.x + (dx / L) * gap, n.y + (dy / L) * gap];
      const a = n.w / 2, b = n.h / 2;
      const s = n.shape === "ellipse" ? 1 / Math.hypot(dx / a, dy / b) : n.shape === "diamond" ? 1 / (Math.abs(dx) / a + Math.abs(dy) / b) : Math.min(a / Math.abs(dx || 1e-9), b / Math.abs(dy || 1e-9));
      return [n.x + dx * s + (dx / L) * gap, n.y + dy * s + (dy / L) * gap];
    };
    sk.arrow = (id, from, to, a = {}) => {
      const A = cen(from), B = cen(to);
      if (!A || !B) throw new Error(`HF.sketch: arrow ${id}: unknown end ${!A ? from : to}`);
      const bend = a.bend || 0, mx0 = (A.x + B.x) / 2, my0 = (A.y + B.y) / 2, L = Math.hypot(B.x - A.x, B.y - A.y) || 1;
      const mx = mx0 - ((B.y - A.y) / L) * bend * L, my = my0 + ((B.x - A.x) / L) * bend * L;     // the curve passes through (mx, my)
      const gap = a.gap != null ? a.gap : 18;
      const p0 = edge(A, mx, my, gap), p1 = edge(B, mx, my, gap);
      const c = [2 * mx - (p0[0] + p1[0]) / 2, 2 * my - (p0[1] + p1[1]) / 2];
      const q = (t) => [(1 - t) * (1 - t) * p0[0] + 2 * (1 - t) * t * c[0] + t * t * p1[0], (1 - t) * (1 - t) * p0[1] + 2 * (1 - t) * t * c[1] + t * t * p1[1]];
      const pts = Array.from({ length: 11 }, (_, k) => q(k / 10));
      const tip = p1, back = q(0.9), ang = Math.atan2(tip[1] - back[1], tip[0] - back[0]), hl = a.head || 26;
      const hp = (s) => [tip[0] - hl * Math.cos(ang + s), tip[1] - hl * Math.sin(ang + s)];
      const opt = { stroke: a.stroke || ink, strokeWidth: a.strokeWidth || base.strokeWidth, seed: a.seed, roughness: a.roughness != null ? a.roughness : base.roughness, strokeLineDash: a.dashed ? [14, 12] : undefined };
      if (!a.dashed) delete opt.strokeLineDash;
      const it = add(id, { kind: "arrow", ...build((O) => [gen.curve(pts, O), gen.linearPath([hp(0.48), tip, hp(-0.48)], { ...O, strokeLineDash: undefined })], opt), n: { x: mx, y: my, w: 0, h: 0, shape: "pt" } });
      if (a.label) it.label = label(mx + (a.labelDx || 0), my + (a.labelDy || 0), a.label, { size: a.size || 38, color: a.color || C.ink2 });
      return it;
    };
    sk.line = (id, pts, a = {}) => add(id, { kind: "line", ...build((O) => gen.curve(pts, O), { stroke: a.stroke || ink, strokeWidth: a.strokeWidth || base.strokeWidth, seed: a.seed }),
      n: { x: pts[0][0], y: pts[0][1], w: 0, h: 0, shape: "pt" } });
    sk.ring = (id, target, a = {}) => {
      const n = cen(target), pad = a.pad != null ? a.pad : 34;
      return add(id, { kind: "ring", ...build((O) => gen.ellipse(n.x, n.y, n.w * 1.18 + pad * 2, n.h * 1.3 + pad * 2, O),
        { stroke: a.color || C.acc, strokeWidth: a.strokeWidth || 4.5, roughness: a.roughness || 1.8, seed: a.seed }), n: { ...n } });
    };
    sk.text = (id, x, y, str, a = {}) => add(id, { kind: "text", g: null, vars: [], v: 0, n: { x, y, w: 0, h: 0, shape: "pt" }, label: label(x, y, str, a) });

    // draw on: strokes with the pen, then the fill fades in and the label writes itself
    sk.draw = (ids, t, a = {}) => {
      let end = t;
      [].concat(ids).forEach((id, k) => {
        const it = items[id]; if (!it) throw new Error("HF.sketch: no item " + id);
        const t0 = Q(t + k * (a.stagger != null ? a.stagger : 0.3)), dur = a.dur || (it.kind === "arrow" ? 0.45 : it.kind === "ring" ? 0.5 : 0.6);
        if (it.g) {
          tl.set(it.g, { autoAlpha: 1 }, t0);
          const v0 = it.vars[0];
          const segs = it.kind === "arrow" ? [[0, 0.72], [0.74, 1]] : null;     // shaft, then the head
          v0.strokes.forEach((p, i) => {
            const [f0, f1] = segs ? segs[Math.min(i, 1)] : [0, 1];
            HF.drawOn(tl, p, Q(t0 + f0 * dur), Math.max(0.1, (f1 - f0) * dur), "power1.inOut");
          });
          it.vars.forEach((vr) => vr.fills.forEach((p) => tl.fromTo(p, { opacity: 0 }, { opacity: 1, duration: 0.4, ease: "power1.out" }, Q(t0 + dur * 0.55))));
        }
        let te = t0 + dur + (it.g && it.vars[0].fills.length ? 0.3 : 0);
        if (it.label) {
          const n = it.label.textContent.length, lt = Q(it.g ? t0 + dur * 0.4 : t0), ld = a.write || Math.min(0.7, 0.12 + n * 0.035);
          tl.set(it.label, { opacity: 1 }, lt); HF.writeOn(tl, it.label, lt, ld); te = Math.max(te, lt + ld);
        }
        it.doneAt = te; end = Math.max(end, te);
      });
      return end;
    };
    sk.boil = (a, b) => { boils.push([a, b]); return sk; };
    sk.hide = (ids, t, dur = 0.35) => { [].concat(ids).forEach((id) => { const it = items[id]; tl.to([it.g, it.label].filter(Boolean), { opacity: 0, duration: dur, ease: "power2.in" }, Q(t)); }); return sk; };
    let shown = false;
    sk.show = (a, b) => { if (!shown) { tl.set(view, { autoAlpha: 0 }, 0); shown = true; } tl.set(view, { autoAlpha: 1 }, Q(a)); if (b != null) tl.set(view, { autoAlpha: 0 }, Q(b)); return sk; };

    // the boil: a pure function of time
    const JIT = [[0, 0, 0], [0.9, -0.7, 0.35], [-0.8, 0.6, -0.3]];
    K.onFrame((t) => {
      const on = boils.some(([a, b]) => t >= a && t < b), k = Math.floor(t * 12 + 1e-6) % 3;
      for (const it of list) {
        const v = on && it.doneAt != null && t >= it.doneAt ? k : 0;
        if (v === it.v) continue;
        it.vars.forEach((vr, i) => { vr.g.style.display = i === v ? "" : "none"; });
        if (it.label) { it.label.style.translate = `${JIT[v][0]}px ${JIT[v][1]}px`; it.label.style.rotate = `${JIT[v][2] + (it.label._rot || 0)}deg`; }
        it.v = v;
      }
    });
    return sk;
  };
})(typeof window !== "undefined" ? window : globalThis);
