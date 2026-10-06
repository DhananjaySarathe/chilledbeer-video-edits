/* kit/hf/motion.js — the A-roll camera: a motion vocabulary, a director that picks moves from the edit, and an
 * evaluator that gives the camera transform at any time. Pure math (no DOM, no randomness): the same file runs in
 * the page (HF.camera uses it) and in Node (kit/motion/bake.py asks it for the motion-blur sub-frames).
 *
 *   const P = HF.motion.direct({ pieces, words, fps: 30, framing: { intro: "W", demo: "PIP" }, format: "long",
 *                                tags: { punch: [ids], joke: [ids], story: [[id0, id1]], section: [ids] },
 *                                faces: [[cx, cy, size], ...] });   // optional per-frame face track (output frames)
 *   HF.motion.at(P, t)        -> { m: [a, b, c, d, e, f], clip, view, top, move }   CSS matrix() of the A-roll, origin 0 0
 *   HF.motion.samples(P, f)   -> [m, ...]   sub-frame matrices for motion blur at output frame f ([m] = no blur)
 *   HF.motion.windows(P)      -> [{ f0, f1, view, top, frames: [[m, ...], ...] }]   the frames that need blur
 *   node kit/motion/plan.cjs in.json out.json   plan + blur windows as JSON (in = the direct() options)
 *
 * The vocabulary (long-form defaults; "reel" is denser, see RULES):
 *   reframe   hard cut between two framings (wide 1.0 <-> tight 1.15 in W) at a new thought; held for the thought
 *   punch     hard cut to 1.22-1.32 just before a stressed word, held to the end of the line, hard cut back
 *   ease      eased punch: x1.18 in 15 frames (power3.out), 180 deg shutter blur, held to the end of the line
 *   snap      crash zoom to 1.4 in 5 frames (expo out .16,1,.3,1) with a 3% overshoot settling in 8 frames, 270 deg
 *             shutter blur and a landing shake (1% of the height, 0.4 deg, 7 frames, 9/11.3/7.4 Hz); a swish cue
 *   push      slow push +5-10% over a 4-10 s story passage (sine in-out), then a hard cut back out
 *   zoomx     zoom transition: 100 -> 300% in 6 frames (expo in) into a section cut, 300 -> 100% out (expo out), 330 deg
 *   drift     every held framing creeps in ~0.6%/s, easing out at +3% (a held shot is never a still)
 * Scale is interpolated in log space and the eyes (not the top-left corner) are interpolated, so the face never swims.
 * Composition: eyes on the upper third with a sliver of headroom (3% above the hair), the face at the layout's x (W/M/C centre, SR right,
 * SL left), clamped so the picture always covers the frame.
 */
(function (root) {
  const HF = root.HF || (root.HF = {});
  const MO = (HF.motion = {});
  MO.version = "2.0.0";

  // films' face = [cx, cy, size]: YuNet box centre and head width (films/*/face_track.py). Measured on jobs/ew2: YuNet's
  // eye landmarks sit 0.20 head widths above the box centre (40 frames); the top of the (thick) hair ~1.1 (5 frames).
  const EYE_K = 0.2, HEAD_K = 1.1;
  MO.EYE_K = EYE_K;
  MO.HEAD_K = HEAD_K;

  // ---------------------------------------------------------------- easing
  function bezier(x1, y1, x2, y2) {
    const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    const X = (t) => ((ax * t + bx) * t + cx) * t, Y = (t) => ((ay * t + by) * t + cy) * t, DX = (t) => (3 * ax * t + 2 * bx) * t + cx;
    return (x) => {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      let t = x;
      for (let i = 0; i < 8; i++) {
        const e = X(t) - x, d = DX(t);
        if (Math.abs(e) < 1e-9) return Y(t);
        if (Math.abs(d) < 1e-6) break;
        t -= e / d;
        if (t < 0 || t > 1) break;
      }
      let lo = 0, hi = 1;
      t = x;
      for (let i = 0; i < 60; i++) { const v = X(t); if (Math.abs(v - x) < 1e-9) break; if (v < x) lo = t; else hi = t; t = (lo + hi) / 2; }
      return Y(t);
    };
  }
  const EASE = {
    none: (p) => p,
    sine: bezier(0.37, 0, 0.63, 1),                                       // sine in-out
    p3out: (p) => 1 - Math.pow(1 - p, 3),                                 // power3.out
    p3inout: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    expo: bezier(0.16, 1, 0.3, 1),                                        // expo out, the snap
    expoIn: (p) => (p <= 0 ? 0 : Math.pow(2, 10 * p - 10)),
    expoOut: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  };
  MO.EASE = EASE;
  MO.bezier = bezier;
  const clamp01 = (p) => Math.max(0, Math.min(1, p));

  // ---------------------------------------------------------------- rules and scales
  MO.RULES = {
    long: {
      hold: 3.0,               // a reframe needs the framing held this long (a thought, never A/B on every cut)
      holdMax: 9.0,            // a framing held longer than this may reframe at a clause cut
      minThought: 1.2,         // ... and needs this much of the new thought left to hold
      drift: 0.006, driftCap: 0.03,
      third: 1 / 3, headroom: 0.03,
      punch: { gap: 16, s: [1.22, 1.32], mult: 1.2, hold: [0.8, 3.2], lead: 2 },        // ~1 per 15-20 s
      ease: { frames: 15, mult: 1.18, lead: 0.24, shutter: 180, max: 8 },
      snap: { gap: 25, s: 1.4, frames: 5, overshoot: 0.03, settle: 8, lead: 3, shutter: 270, max: 24,
        shake: { amp: 0.01, rot: 0.4, frames: 7, hz: [9.0, 11.3, 7.4] } },
      push: { gap: 30, rate: 0.012, amount: [0.05, 0.1], len: [4, 14] },
      zoomx: { frames: 6, peak: 3.0, shutter: 330, max: 32 },
      auto: true,
    },
    reel: {
      hold: 1.5, holdMax: 4.5, minThought: 0.8,
      drift: 0.008, driftCap: 0.035,
      third: 1 / 3, headroom: 0.03,
      punch: { gap: 6, s: [1.28, 1.4], mult: 1.25, hold: [0.6, 2.4], lead: 2 },
      ease: { frames: 12, mult: 1.2, lead: 0.2, shutter: 180, max: 8 },
      snap: { gap: 10, s: 1.5, frames: 4, overshoot: 0.03, settle: 8, lead: 3, shutter: 270, max: 24,
        shake: { amp: 0.012, rot: 0.5, frames: 7, hz: [9.0, 11.3, 7.4] } },
      push: { gap: 15, rate: 0.015, amount: [0.05, 0.1], len: [3, 10] },
      zoomx: { frames: 6, peak: 3.0, shutter: 330, max: 32 },
      auto: true,
    },
  };
  // framing variants per layout: [wide, tight]; a reframe flips between them (>= 1.12x apart: less reads as a glitch)
  MO.SCALES = { W: [1.0, 1.15], M: [1.12, 1.26], C: [1.24, 1.36], SR: [1.2, 1.34], SL: [1.2, 1.34], P: [1.0, 1.15] };
  const FULL = { W: 1, M: 1, C: 1, P: 1, H: 1 }, SIDE = { SR: 1, SL: 1 }, SMALL = { PIP: 1, OFF: 1 };
  MO.FULL = FULL; MO.SIDE = SIDE; MO.SMALL = SMALL;
  const MAXS = 1.5;                                                       // never past this outside a zoom transition
  // sound cues (kit/sfx): [file, seconds from the file's start to its peak (lined up with the move), gain dB]
  MO.SFX = { snap: ["whoosh/whoosh__fast-transitions-swoosh__mixkit-3115", 0.114, -20],
    zoomx: ["whoosh/whoosh__fast-small-sweep-transition__mixkit-166", 0.336, -23] };

  function merge(a, b) {
    const o = Array.isArray(a) ? a.slice() : Object.assign({}, a);
    for (const k in b || {}) o[k] = b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) && a && typeof a[k] === "object" ? merge(a[k], b[k]) : b[k];
    return o;
  }
  const find = (arr, t) => {                                              // the item with t0 <= t < t1 (sorted, no overlap)
    let lo = 0, hi = arr.length - 1, k = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m].t0 <= t + 1e-9) { k = m; lo = m + 1; } else hi = m - 1; }
    return k < 0 ? arr[0] : arr[k];
  };

  // ---------------------------------------------------------------- composition
  function clampXY(P, view, s, x, y) {
    const [VW, VH] = view, [SW, SH] = P.src;
    const x0 = VW - SW * s, y0 = VH - SH * s;
    return [x0 > 0 ? x0 / 2 : Math.min(0, Math.max(x0, x)), y0 > 0 ? y0 / 2 : Math.min(0, Math.max(y0, y))];
  }
  // where the framing at scale s puts the picture: eyes on the upper third (with headroom), face at the layout's x
  function place(P, sh, s, face) {
    const view = sh.view || P.view, [VW, VH] = view, R = P.R;
    const [cx, cy, sz] = face, ey = cy - EYE_K * sz;
    const tx = sh.layout === "SR" ? VW * 0.651 : sh.layout === "SL" ? VW * 0.333 : VW / 2;
    const ty = Math.max(VH * R.third, R.headroom * VH + (HEAD_K - EYE_K) * sz * s);
    const [x, y] = clampXY(P, view, s, tx - cx * s, ty - ey * s);
    return { s, x, y };
  }
  const eyes = (face) => [face[0], face[1] - EYE_K * face[2]];
  // between two framings of the same face: log-space scale, the eyes move in a straight line
  function blend(P, sh, A, B, e, face) {
    const s = A.s * Math.pow(B.s / A.s, e), [ax, ay] = eyes(face);
    const px = A.x + ax * A.s + (B.x + ax * B.s - A.x - ax * A.s) * e, py = A.y + ay * A.s + (B.y + ay * B.s - A.y - ay * A.s) * e;
    const [x, y] = clampXY(P, sh.view || P.view, s, px - ax * s, py - ay * s);
    return { s, x, y };
  }
  // zoom about the eyes from a framing (zoom transitions)
  function about(P, sh, A, s, face) {
    const [ax, ay] = eyes(face), px = A.x + ax * A.s, py = A.y + ay * A.s;
    const [x, y] = clampXY(P, sh.view || P.view, s, px - ax * s, py - ay * s);
    return { s, x, y };
  }
  function smallState(P, layout, face) {                                // the corner face (PIP) / hidden (OFF)
    const B = P.pip, s = B.scale, half = B.s / 2 / s, [cx, cy] = face, fy = cy + B.dy, [SW, SH] = P.src;
    return { s, x: B.x + B.s / 2 - cx * s, y: B.y + B.s / 2 - fy * s, clip: [fy - half, SW - cx - half, SH - fy - half, cx - half, B.radius / s] };
  }
  // the drift: ~rate per second at first, easing out at +cap (never a hard stop)
  const drift = (R, dt) => 1 + R.driftCap * (1 - Math.exp(-(R.drift * Math.max(0, dt)) / R.driftCap));

  // ---------------------------------------------------------------- the evaluator
  function moveAt(P, t) {
    for (const m of P.moves) if (t >= m.t0 - 1e-9 && t < m.t1 - 1e-9) return m;
    return null;
  }
  function stateAt(P, t) {
    const sh = find(P.shots, t), pc = find(P.pieces, t), face = pc.face, R = P.R;
    const view = sh.view || P.view, top = sh.top != null ? sh.top : P.top;
    const out = (st, extra) => Object.assign({ rot: 0, dx: 0, dy: 0, clip: null, view, top, layout: sh.layout, face }, st, extra || {});
    if (SMALL[sh.layout]) return out(smallState(P, sh.layout, face));
    const base = (tt) => sh.s * drift(R, tt - sh.t0);
    const m = moveAt(P, t);
    if (!m) return out(place(P, sh, base(t), face));
    const fps = P.fps;
    if (m.kind === "punch") return out(place(P, sh, m.s * drift(R, t - m.t0), face), { move: m.kind });
    if (m.kind === "push") {
      const e = EASE.sine(clamp01((t - m.t0) / (m.t1 - m.t0)));
      return out(place(P, sh, base(m.t0) * Math.pow(1 + m.amount, e), face), { move: m.kind });
    }
    if (m.kind === "ease") {
      const d = m.frames / fps;
      if (t < m.t0 + d) return out(blend(P, sh, place(P, sh, m.s0 || base(m.t0), face), place(P, sh, m.s, face), EASE.p3out((t - m.t0) / d), face), { move: m.kind });
      return out(place(P, sh, m.s * drift(R, t - m.t0 - d), face), { move: m.kind });
    }
    if (m.kind === "snap") {
      const d1 = m.frames / fps, d2 = m.settle / fps, peak = m.s * (1 + m.overshoot);
      let st;
      if (t < m.t0 + d1) st = blend(P, sh, place(P, sh, m.s0 || base(m.t0), face), place(P, sh, peak, face), EASE.expo((t - m.t0) / d1), face);
      else if (t < m.t0 + d1 + d2) st = blend(P, sh, place(P, sh, peak, face), place(P, sh, m.s, face), EASE.sine((t - m.t0 - d1) / d2), face);
      else st = place(P, sh, m.s * drift(R, t - m.t0 - d1 - d2), face);
      return out(st, Object.assign({ move: m.kind }, shake(P, sh, m, t - m.t0 - d1, st, face)));
    }
    if (m.kind === "zoomx") {
      const d = m.frames / fps, B = place(P, sh, base(t), face);
      const e = t < m.tc ? EASE.expoIn(clamp01((t - m.t0) / d)) : 1 - EASE.expoOut(clamp01((t - m.tc) / d));
      return out(about(P, sh, B, B.s * Math.pow(m.peak, e), face), { move: m.kind });
    }
    return out(place(P, sh, base(t), face));
  }
  // landing shake: a sum of sines (fixed frequencies, zero phase: it starts from rest), exponential decay, limited by
  // the slack the clamp leaves so the frame edge never shows
  function shake(P, sh, m, dt, st, face) {
    const k = m.shake;
    if (!k || dt < 0 || dt >= k.frames / P.fps) return {};
    const [VW, VH] = sh.view || P.view, [SW, SH] = P.src, dur = k.frames / P.fps;
    const env = Math.exp(-dt / (dur / 3)) * (1 - dt / dur), w = (f) => Math.sin(2 * Math.PI * f * dt);
    const slx = Math.min(-st.x, st.x - (VW - SW * st.s)), sly = Math.min(-st.y, st.y - (VH - SH * st.s));
    let rot = k.rot * env * w(k.hz[2]), rm = (Math.abs(rot) * Math.PI / 180) * Math.hypot(VW, VH);
    if (rm > Math.min(slx, sly)) { rot = 0; rm = 0; }                    // no room to roll: translate only
    const sx = Math.max(0, slx - rm), sy = Math.max(0, sly - rm), A = k.amp * VH * env;
    const dy = Math.max(-sy, Math.min(sy, A * (0.6 * w(k.hz[0]) + 0.4 * w(k.hz[1]))));
    const dx = Math.max(-sx, Math.min(sx, 0.6 * A * (0.6 * w(k.hz[1]) + 0.4 * w(k.hz[2]))));
    const [ax, ay] = eyes(face);
    return { dx, dy, rot, pivot: [st.x + ax * st.s, st.y + ay * st.s] };
  }
  function matrixOf(c) {
    const th = (c.rot || 0) * Math.PI / 180, co = Math.cos(th), si = Math.sin(th), s = c.s;
    const [px, py] = c.pivot || [0, 0], dx = c.dx || 0, dy = c.dy || 0;
    return [s * co, s * si, -s * si, s * co, co * (c.x - px) - si * (c.y - py) + px + dx, si * (c.x - px) + co * (c.y - py) + py + dy];
  }
  function lerpState(A, B, e) {
    const L = (a, b) => a + (b - a) * e, clip = A.clip || B.clip ? (A.clip || [0, 0, 0, 0, 0]).map((v, i) => L(v, (B.clip || [0, 0, 0, 0, 0])[i])) : null;
    return Object.assign({}, B, { s: L(A.s, B.s), x: L(A.x, B.x), y: L(A.y, B.y), rot: 0, dx: 0, dy: 0, pivot: null, clip, move: "layout" });
  }
  const css = (clip) => (clip ? `inset(${clip.slice(0, 4).map((v) => v.toFixed(1) + "px").join(" ")} round ${clip[4].toFixed(1)}px)` : "inset(0px 0px 0px 0px round 0px)");
  MO.at = function (P, t) {
    let c = null;
    for (const tr of P.trans) if (t >= tr.t0 && t < tr.t1) { c = lerpState(tr.from, tr.to, EASE.p3inout((t - tr.t0) / (tr.t1 - tr.t0))); break; }
    if (!c) c = stateAt(P, t);
    c.m = matrixOf(c);
    c.clipCss = css(c.clip);
    return c;
  };

  // ---------------------------------------------------------------- motion blur sub-frames
  const BLUR = { ease: "ease", snap: "snap", zoomx: "zoomx" };
  function inv(m) {
    const [a, b, c, d, e, f] = m, det = a * d - b * c;
    return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
  }
  const ap = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  function disp(A, B, view) {                                            // largest on-screen travel between two matrices
    const Ai = inv(A), [VW, VH] = view;
    let d = 0;
    for (const [x, y] of [[0, 0], [VW, 0], [0, VH], [VW, VH], [VW / 2, VH / 2]]) {
      const [u, v] = ap(Ai, x, y), [X, Y] = ap(B, u, v);
      d = Math.max(d, Math.hypot(X - x, Y - y));
    }
    return d;
  }
  MO.disp = disp;
  // the continuous stretch of camera around t (no hard cut inside): sub-frames never cross a cut
  function span(P, t, m) {
    const pc = find(P.pieces, t), sh = find(P.shots, t);
    let lo = Math.max(pc.t0, sh.t0, m.t0), hi = Math.min(pc.t1, sh.t1, m.t1);
    if (m.kind === "zoomx") { if (t < m.tc) hi = Math.min(hi, m.tc); else lo = Math.max(lo, m.tc); }
    return [lo, hi];
  }
  MO.samples = function (P, f, opt) {
    const t = f / P.fps, c = MO.at(P, t), m = moveAt(P, t);
    if (!m || !BLUR[m.kind] || P.trans.some((tr) => t >= tr.t0 && t < tr.t1)) return [c.m];
    const cfg = P.R[m.kind], h = cfg.shutter / 360 / P.fps / 2, [lo, hi] = span(P, t, m), eps = 1e-6;
    const ta = Math.max(lo, t - h), tb = Math.min(hi - eps, t + h);
    if (tb <= ta) return [c.m];
    const A = MO.at(P, ta).m, B = MO.at(P, tb).m, d = disp(A, B, c.view);
    if (d < 1) return [c.m];
    const n = Math.min((opt && opt.max) || cfg.max, Math.max(2, Math.ceil(d / 1.5)));
    const out = [];
    for (let k = 0; k < n; k++) out.push(MO.at(P, ta + ((tb - ta) * k) / (n - 1)).m);
    return out;
  };
  MO.windows = function (P, opt) {
    const W = [];
    for (const m of P.moves) {
      if (!BLUR[m.kind]) continue;
      for (let f = Math.floor(m.t0 * P.fps - 1e-6); f <= Math.ceil(m.t1 * P.fps); f++) {
        const ss = MO.samples(P, f, opt);
        if (ss.length < 2) continue;
        const c = MO.at(P, f / P.fps), last = W[W.length - 1];
        if (last && last.f1 === f && last.view[0] === c.view[0] && last.view[1] === c.view[1]) { last.f1 = f + 1; last.frames.push(ss); }
        else W.push({ f0: f, f1: f + 1, view: c.view, top: c.top, frames: [ss] });
      }
    }
    return W;
  };

  // ---------------------------------------------------------------- the director
  const END = /[.?!…]["'”’)\]]*$/, CLAUSE = /[,;:—–]["'”’)\]]*$/;
  const INTENS = /^(never|ever|always|best|worst|super|insane|crazy|huge|massive|exactly|only|zero|free|expensive|cheap|magic(al)?|awesome|loved?|hate|nothing|everything|seamless)$/i;
  function autoEmphasis(words) {                                          // stressed-word guesses, scored
    const out = [];
    words.forEach((w, k) => {
      const bare = w.text.replace(/[^\w$%.-]/g, "");
      let sc = 0;
      if (INTENS.test(bare)) sc += 1;
      if (/\d|\$|%/.test(w.text)) sc += 2;
      const prev = words[k - 1], prev2 = words[k - 2];
      if (prev && prev2 && prev.text.replace(/\W/g, "").toLowerCase() === bare.toLowerCase() && prev2.text.replace(/\W/g, "").toLowerCase() === bare.toLowerCase()) sc += 2;
      if (sc) out.push({ w, score: sc });
    });
    return out;
  }

  MO.direct = function (o) {
    const format = o.format || (o.mode === "panel" ? "reel" : "long");
    const R = merge(MO.RULES[format], o.rules || {});
    const fps = o.fps || 30, Q = (t) => Math.round(t * fps) / fps;
    const SC = Object.assign({}, MO.SCALES, o.scales || {});
    const H = o.height || (o.view ? o.view[1] : 1080);
    const panel = o.mode === "panel", top = panel ? (o.top != null ? o.top : 880) : 0;
    const view = panel ? [o.width || 1080, H - top] : o.view || [o.width || 1920, H];
    const layoutOf = (tag) => {
      if (panel) return "P";
      if (!o.framing) return "W";
      const L = o.framing[tag];
      if (!L) throw new Error("HF.motion: no framing for tag " + tag);
      return L;
    };
    const pieces = (o.pieces || []).map((p, i) => ({ i, t0: p.out_a, t1: p.out_b, face: p.face, tag: p.tag, layout: layoutOf(p.tag) }));
    if (!pieces.length) throw new Error("HF.motion: no pieces");
    const t0 = o.from != null ? o.from : pieces[0].t0, tEnd = o.until != null ? o.until : pieces[pieces.length - 1].t1;
    const words = (o.words || []).filter((w) => w.text && w.t != null && w.t >= t0 - 0.05 && w.t < tEnd).slice().sort((a, b) => a.t - b.t);
    const byId = new Map(words.map((w, k) => [w.i, k]));
    const tags = o.tags || {};
    const P = {
      v: 2, fps, src: o.src || [1920, 1080], view, top, mode: panel ? "panel" : "frame", format, R,
      pip: Object.assign({ x: 1556, y: 716, s: 316, scale: 0.5, radius: 26, dy: 70 }, o.pip || {}),
      pieces: pieces.map((p) => ({ t0: p.t0, t1: p.t1, face: p.face })), shots: [], moves: [], trans: [], cues: [], log: [],
    };
    if (o.pipRadius != null) P.pip.radius = o.pipRadius;
    if (o.pipScale != null) P.pip.scale = o.pipScale;
    P.pieces[0].t0 = Math.min(P.pieces[0].t0, 0);
    P.pieces[P.pieces.length - 1].t1 = 1e9;
    const pieceAt = (t) => find(pieces, t);
    const say = (t, what) => P.log.push(`${t.toFixed(2)} ${what}`);

    // ---- boundaries: every cut, and every sentence start (a camera cut on continuous footage sits mid-pause)
    const B = [];
    pieces.forEach((p, i) => {
      if (!i) return;
      const before = words.filter((w) => w.t < p.t0 - 0.01).pop();
      const kind = p.tag !== pieces[i - 1].tag ? "scene" : before && END.test(before.text) ? "thought" : before && CLAUSE.test(before.text) ? "clause" : "mid";
      B.push({ t: p.t0, kind, cut: true });
    });
    words.forEach((w, k) => {
      if (!k || !END.test(words[k - 1].text)) return;
      const w0 = words[k - 1];
      if (B.some((b) => b.cut && b.t > w0.e - 0.05 && b.t <= w.t + 0.05)) return;    // a cut already sits in this pause
      B.push({ t: w.t - w0.e > 0.07 ? Q((w0.e + w.t) / 2) : Q(w.t - 0.03), kind: "thought", cut: false });
    });
    const secT = (tags.section || []).map((x) => (typeof x === "number" ? (byId.has(x) ? words[byId.get(x)].t : null) : x && x.t != null ? x.t : null)).filter((x) => x != null);
    secT.forEach((ts) => {
      const near = B.filter((b) => b.t <= ts + 0.02 && b.t > ts - 0.8).sort((a, b) => b.t - a.t)[0];
      if (near) near.kind = "section";
      else B.push({ t: Q(ts - 0.05), kind: "section", cut: false });
    });
    B.sort((a, b) => a.t - b.t);
    const isNew = (b) => b.kind === "thought" || b.kind === "scene" || b.kind === "section";
    const nextNew = (t) => { const b = B.find((x) => x.t > t + 1e-6 && isNew(x)); return b ? b.t : tEnd; };

    // ---- 1. shot times: a new framing only at a new thought, held at least R.hold (never A/B on every cut)
    let cur = null;
    const open = (t, layout, why) => {
      if (cur) cur.t1 = t;
      cur = { t0: t, t1: 1e9, layout, v: 0, s: 1, why };
      P.shots.push(cur);
    };
    open(Math.min(t0, 0), pieceAt(t0).layout, "start");
    if (panel && o.hook) {                                                 // 9:16 hook: the face full screen first
      Object.assign(cur, { layout: "H", view: [view[0], H], top: 0, why: "hook (full screen)" });
      open(o.hook[1], "P", "after the hook");
    }
    for (const b of B) {
      if (panel && o.hook && b.t < o.hook[1] + 0.05) continue;
      const L = pieceAt(b.t + 1e-6).layout;
      if (L !== cur.layout) { open(b.t, L, "layout"); continue; }
      if (SMALL[L]) continue;
      const held = b.t - cur.t0, left = nextNew(b.t) - b.t;
      if (b.kind === "section") open(b.t, L, "section");
      else if (isNew(b) && held >= R.hold && left >= R.minThought) open(b.t, L, `reframe (${b.kind})`);
      else if (b.kind === "clause" && b.cut && held >= R.holdMax && left >= R.minThought) open(b.t, L, "reframe (long hold)");
    }
    const shotAt = (t) => find(P.shots, t);
    const prevShot = (sh) => P.shots[P.shots.indexOf(sh) - 1];
    const nextShot = (sh) => P.shots[P.shots.indexOf(sh) + 1];
    const cuts = [...new Set([...pieces.slice(1).map((p) => p.t0), ...P.shots.slice(1).map((s) => s.t0)])].sort((a, b) => a - b);

    // ---- 2. moves (where and what): tagged first, then guesses; budgets; no overlaps
    const lineEnd = (k) => { let j = k; while (j < words.length - 1 && !END.test(words[j].text)) j++; return words[j].e + 0.12; };
    const fits = (L, kind) => (FULL[L] && L !== "H") || (SIDE[L] && (kind === "punch" || kind === "ease" || kind === "push"));
    const touch = (x, y) => Math.abs(x - y) < 1e-6;                      // back to back on the same cut is fine
    const busy = (a, b, pad = 0.3) => P.moves.some((m) => a < m.t1 + pad && b > m.t0 - pad && !touch(b, m.t0) && !touch(a, m.t1));
    const family = { punch: 1, ease: 1, snap: 1 };
    const gapOK = (t, kind) => P.moves.every((m) => (m.kind === "zoomx" ? Math.abs(m.tc - t) >= 3 : !family[m.kind] ||
      Math.abs(m.t0 - t) >= (kind === "snap" && m.kind === "snap" ? Math.max(R.punch.gap, R.snap.gap) : R.punch.gap)));
    const nearLayout = (a, b) => P.shots.some((s, i) => i && s.t0 > a - 0.7 && s.t0 < b + 0.7 && s.layout !== P.shots[i - 1].layout);
    const add = (m) => { P.moves.push(m); P.moves.sort((x, y) => x.t0 - y.t0); return true; };
    function proposePunch(k, kind, why) {
      const w = words[k], sh = shotAt(w.t);
      if (!fits(sh.layout, kind)) return false;
      let a = Q(w.t - (kind === "snap" ? R.snap.lead / fps : kind === "ease" ? R.ease.lead : R.punch.lead / fps));
      const before = cuts.filter((c) => c <= a + 1e-6 && c > a - 0.6).pop();
      if (before != null && before >= sh.t0) a = before;                  // a cut just before: cut on the cut (no double cut)
      if (a - sh.t0 < 0.6) a = sh.t0;
      let b = Math.min(lineEnd(k), sh.t1, a + R.punch.hold[1] + (kind === "ease" ? R.ease.frames / fps : 0));
      const after = cuts.find((c) => c >= b - 1e-6 && c < b + 0.6 && c <= sh.t1);
      if (after != null) b = after;                                        // cut back out on the next cut
      if (b - a < R.punch.hold[0] || busy(a, b) || !gapOK(a, kind) || nearLayout(a, b)) return false;
      return add({ kind, t0: a, t1: b, why, word: w.i });
    }
    function proposePush(a, b, why) {
      const sh = shotAt(a + 1e-6), len = b - a;
      if (!fits(sh.layout, "push") || shotAt(b - 1e-3) !== sh || len < R.push.len[0] || len > R.push.len[1] || busy(a, b) || nearLayout(a, b)) return false;
      if (P.moves.some((m) => m.kind === "push" && Math.abs(m.t0 - a) < R.push.gap)) return false;
      return add({ kind: "push", t0: a, t1: b, amount: +Math.max(R.push.amount[0], Math.min(R.push.amount[1], R.push.rate * len)).toFixed(4), why });
    }
    const kOf = (id) => (byId.has(id) ? byId.get(id) : -1);
    B.filter((b) => b.kind === "section").forEach((b) => {                // zoom transitions at sections
      const d = R.zoomx.frames / fps, A = shotAt(b.t - 1e-3), C = shotAt(b.t + 1e-6);
      if (!FULL[A.layout] || !FULL[C.layout] || A.layout === "H" || b.t - d < t0) return;
      add({ kind: "zoomx", t0: Q(b.t - d), t1: Q(b.t + d), tc: b.t, frames: R.zoomx.frames, peak: R.zoomx.peak, why: "section" });
      P.cues.push({ name: MO.SFX.zoomx[0], t: +Math.max(0, b.t - MO.SFX.zoomx[1]).toFixed(3), db: MO.SFX.zoomx[2] });
    });
    (tags.joke || []).forEach((id) => kOf(id) >= 0 && proposePunch(kOf(id), "snap", "joke"));
    (tags.punchline || []).forEach((id) => kOf(id) >= 0 && proposePunch(kOf(id), "punch", "punchline"));
    (tags.punch || tags.emphasis || []).forEach((id) => kOf(id) >= 0 && proposePunch(kOf(id), "punch", "emphasis"));
    (tags.ease || []).forEach((id) => kOf(id) >= 0 && proposePunch(kOf(id), "ease", "tagged"));
    (tags.story || []).forEach(([i0, i1]) => {
      const k0 = kOf(i0), k1 = kOf(i1);
      if (k0 < 0 || k1 < 0) return;
      const a = B.filter((b) => b.t <= words[k0].t + 0.02).map((b) => b.t).pop();
      const end = B.find((b) => b.t >= words[k1].e - 0.02);
      proposePush(a != null && words[k0].t - a < 0.8 ? a : Q(words[k0].t - 0.1), end && end.t - words[k1].e < 0.8 ? end.t : Q(words[k1].e + 0.15), "story");
    });
    if (o.auto != null ? o.auto : R.auto) {
      autoEmphasis(words).sort((a, b) => b.score - a.score || a.w.t - b.w.t).forEach(({ w }) => proposePunch(byId.get(w.i), "punch", `auto "${w.text}"`));
      const th = [t0, ...B.filter(isNew).map((b) => b.t), tEnd];
      th.slice(0, -1).map((a, i) => [a, th[i + 1]]).sort((x, y) => y[1] - y[0] - (x[1] - x[0])).forEach(([a, b]) => proposePush(a, b, "auto (long thought)"));
    }
    // never the same move twice in a row: punch <-> ease, a second snap eases, a second push in a row is dropped
    const seq = P.moves.filter((m) => m.kind !== "zoomx");
    for (let i = 1; i < seq.length; i++) {
      const a = seq[i - 1], m = seq[i];
      if (a.kind !== m.kind) continue;
      if (m.kind === "push") m.drop = true;
      else if (m.kind === "ease") Object.assign(m, { kind: "punch", why: m.why + ", hard (no repeat)" });
      else {
        const sh = shotAt(m.t0 + 1e-6), t = Math.max(sh.t0, Q(m.t0 - (R.ease.lead - R.punch.lead / fps)));
        Object.assign(m, { kind: "ease", t0: t, why: m.why + ", eased (no repeat)" });
      }
    }
    P.moves = P.moves.filter((m) => !m.drop);

    // ---- 3. framing variants: flip at each reframe, unless the cut would be under 1.1x (e.g. after a push or a punch)
    const STEP = 1.1;
    const moveIn = (sh) => P.moves.filter((m) => m.t0 >= sh.t0 - 1e-6 && m.t0 < sh.t1 - 1e-6);
    const endScale = (sh) => {                                             // the framing a shot cuts away from
      const m = moveIn(sh).filter((x) => x.t1 >= sh.t1 - 1e-6 && x.kind !== "zoomx").pop();
      if (m && family[m.kind]) return m.s || Math.max(R.punch.s[0], m.kind === "snap" ? R.snap.s : 0);
      if (m && m.kind === "push") return sh.s * drift(R, m.t0 - sh.t0) * (1 + m.amount);
      return sh.s * drift(R, sh.t1 - sh.t0);
    };
    P.shots.forEach((sh, i) => {
      const ps = P.shots[i - 1], V = SC[sh.layout] || SC.W;
      if (SMALL[sh.layout]) return;
      if (sh.layout === "H") { sh.s = (H / P.src[1]) * 1.08; return; }
      if (!ps || ps.layout !== sh.layout || sh.why === "section") { sh.v = 0; sh.s = V[0]; return; }
      const e = endScale(ps), ok = (v) => Math.max(V[v], e) / Math.min(V[v], e) >= STEP;
      sh.v = ok(1 - ps.v) ? 1 - ps.v : ok(ps.v) ? ps.v : 1 - ps.v;
      sh.s = V[sh.v];
    });
    // consecutive shots on the same framing are one shot (no drift restart, no cut)
    P.shots = P.shots.filter((sh, i) => {
      const ps = P.shots[i - 1];
      if (!ps || ps.layout !== sh.layout || ps.v !== sh.v || ps.view || sh.why === "section" || SMALL[sh.layout]) return true;
      if (P.moves.some((m) => Math.abs(m.t0 - sh.t0) < 1e-6 || Math.abs(m.t1 - sh.t0) < 1e-6)) return true;
      ps.t1 = sh.t1;
      return false;
    });
    for (let i = 0; i < P.shots.length; i++) {                             // keep t1 = next t0 after merging
      if (i + 1 < P.shots.length) P.shots[i].t1 = P.shots[i + 1].t0;
    }

    // ---- 4. how far each move goes: >= 1.1x from every framing it cuts from or back to, within the image limits
    const heldAt = (sh, t) => sh.s * drift(R, t - sh.t0);
    P.moves = P.moves.filter((m) => {
      if (m.kind === "push" || m.kind === "zoomx") return true;
      const sh = shotAt(m.t0 + 1e-6), ps = prevShot(sh), ns = nextShot(sh), L = sh.layout;
      const atStart = m.t0 <= sh.t0 + 1e-6 && ps && ps.layout === L && !SMALL[ps.layout];
      // a continuous move that opens a thought starts from the framing before it (one move, not a cut and a move)
      if (atStart && m.kind !== "punch") m.s0 = +endScale(ps).toFixed(4);
      const from = m.kind === "punch" ? (atStart ? endScale(ps) : heldAt(sh, m.t0)) : m.s0 || heldAt(sh, m.t0);
      const to = m.t1 >= sh.t1 - 1e-6 && ns && !SMALL[ns.layout] ? ns.s : heldAt(sh, m.t1);
      const lo = SIDE[L] ? sh.s * 1.12 : R.punch.s[0], hi = SIDE[L] ? 1.38 : R.punch.s[1] + 0.04;
      const want = m.kind === "snap" ? Math.max(R.snap.s, from * 1.2) : Math.min(R.punch.s[1], (m.kind === "ease" ? from * R.ease.mult : sh.s * R.punch.mult));
      const s = Math.max(lo, want, STEP * Math.max(from, to), m.kind === "ease" ? 0 : STEP * from);
      if (s > (m.kind === "snap" ? MAXS : hi)) return false;               // too soft on a 1080 source
      m.s = +s.toFixed(4);
      if (m.kind === "snap") Object.assign(m, { frames: R.snap.frames, overshoot: R.snap.overshoot, settle: R.snap.settle, shake: R.snap.shake });
      if (m.kind === "ease") m.frames = R.ease.frames;
      return true;
    });
    P.moves.forEach((m) => {
      if (m.kind === "snap") P.cues.push({ name: MO.SFX.snap[0], t: +Math.max(0, m.t0 + (m.frames / fps) / 2 - MO.SFX.snap[1]).toFixed(3), db: MO.SFX.snap[2] });
      say(m.t0, `${m.kind}${m.s ? " " + (m.s0 ? m.s0.toFixed(2) + "->" : "") + m.s.toFixed(2) : m.amount ? " +" + (m.amount * 100).toFixed(0) + "%" : ""} until ${m.t1.toFixed(2)} (${m.why})`);
    });
    P.shots.forEach((s, i) => { if (i) say(s.t0, `${s.layout} ${s.s.toFixed(2)} (${s.why})`); });
    P.log.sort((a, b) => parseFloat(a) - parseFloat(b));
    P.cues.sort((a, b) => a.t - b.t);

    // ---- 5. the face each stretch of camera frames on: with a per-frame track (o.faces, [cx, cy, size] per output frame),
    // the median over each span between hard cuts (a 1.4x punch on the piece's median face clips a head that leans in)
    if (o.faces && o.faces.length) {
      const F = o.faces, hard = new Set([...pieces.map((p) => p.t0), ...P.shots.map((x) => x.t0)]);
      P.moves.forEach((m) => {
        if (m.kind === "zoomx") hard.add(m.tc);
        else if (m.kind !== "push") { hard.add(m.t1); if (m.kind === "punch") hard.add(m.t0); }
      });
      const med = (a) => { const b = a.slice().sort((x, y) => x - y); return b[b.length >> 1]; };
      P.pieces = [];
      pieces.forEach((p, i) => {
        const end = i + 1 < pieces.length ? pieces[i + 1].t0 : p.t1;
        const edges = [p.t0, ...[...hard].filter((c) => c > p.t0 + 1e-6 && c < end - 1e-6).sort((a, b) => a - b), end];
        for (let k = 0; k + 1 < edges.length; k++) {
          const f0 = Math.round(edges[k] * fps), fs = F.slice(f0, Math.max(f0 + 1, Math.round(edges[k + 1] * fps))).filter(Boolean);
          P.pieces.push({ t0: edges[k], t1: edges[k + 1], face: fs.length ? [0, 1, 2].map((q) => +med(fs.map((f) => f[q])).toFixed(1)) : p.face });
        }
      });
      P.pieces[0].t0 = Math.min(P.pieces[0].t0, 0);
      P.pieces[P.pieces.length - 1].t1 = 1e9;
    }

    // ---- layout transitions to and from the corner face: a 0.6 s eased move (like v1); everything else is a hard cut
    P.shots.forEach((s, i) => {
      if (i && !!SMALL[P.shots[i - 1].layout] !== !!SMALL[s.layout]) P.trans.push({ t0: Q(s.t0 - 0.22), t1: Q(s.t0 + 0.38), from: null, to: null, small: !!SMALL[s.layout] });
    });
    const all = P.trans;
    P.trans = [];
    all.forEach((tr) => {
      tr.from = MO.at(P, tr.t0);
      tr.to = MO.at(P, tr.t1);
      ["m", "clipCss"].forEach((k) => { delete tr.from[k]; delete tr.to[k]; });
    });
    P.trans = all;
    P.shots[P.shots.length - 1].t1 = 1e9;
    return P;
  };

})(typeof window !== "undefined" ? window : globalThis);
