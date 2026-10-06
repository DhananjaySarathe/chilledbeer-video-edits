/* kit/hf/collage.js — paper cut-out / scrapbook collage (Vox / Johnny Harris look): screenshots as torn paper, tape,
 * drop shadows, halftone dots, paper grain, pieces that move "on twos" and a light 2.5D parallax camera (needs core.js).
 *
 *   const cg = HF.collage(K, layer, { x: 0, y: 0, w: 1080, h: 1920, seed: 11 });  // a 3D stage + a camera rig
 *   const a = cg.piece({ x: 90, y: 560, w: 440, h: 640, z: 0, rot: -4, img: "assets/shot.jpg", torn: "tb", tape: ["top"] });
 *   const s = cg.strip("Same prompt.", { x: 120, y: 330, w: 560, h: 130, z: 90, rot: -2, size: 92 });
 *   const d = cg.halftone({ x: 540, y: 900, r: 360, z: -80 });
 *   cg.enter(a, t, { from: "drop" })     // "drop" | "left" | "right" | "up" | "down" | "pop": on twos (12 fps)
 *   cg.exit(a, t)
 *   cg.move(t, { z: 90, ry: -3, x: -20, dur: 6, ease: "sine.inOut" })   // the camera (smooth, on the main timeline)
 *   cg.show(a, b)
 *
 * Exact: torn edges, tape ends and halftone dots are generated once from the seed; grain is an SVG feTurbulence with a
 * fixed seed (static); piece motion lives on a child timeline driven by child.time(floor(t*12)/12) in K.onFrame, and the
 * resting "boil" (a sub-pixel nudge per 12 fps step) comes from a prebuilt table. No randomness at render time.
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/collage.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";
  HF.rng = HF.rng || function (seed) {
    let a = seed >>> 0;
    return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  let uid = 0;

  // a torn sheet: the outer outline (the paper) and an inner one (the printed face), so a white fibre rim shows on torn edges
  HF.torn = function (w, h, r, o = {}) {
    const torn = o.torn === "all" ? "trbl" : o.torn == null ? "tb" : o.torn, A = o.amp || 7, rimW = o.rim != null ? o.rim : 6, border = o.border || 0;
    const outer = [], inner = [];
    const edge = (key, x0, y0, x1, y1, nx, ny) => {                           // n = inward normal
      const len = Math.hypot(x1 - x0, y1 - y0), N = Math.max(2, Math.ceil(len / 5)), isT = torn.includes(key);
      let lo = 0, lo2 = 0;
      const ph = r() * 6.28, wl = 40 + r() * 50;
      for (let i = 0; i < N; i++) {
        const u = i / N, s = u * len;
        lo = lo * 0.82 + (r() - 0.5) * 0.9; lo2 = lo2 * 0.9 + (r() - 0.5) * 0.6;
        const px = x0 + (x1 - x0) * u, py = y0 + (y1 - y0) * u;
        let d = 0, rim = border;
        if (isT) {
          d = A * Math.max(0, 0.55 + 0.45 * Math.sin(s / wl + ph) * 0.6 + lo * 0.55 + (r() - 0.5) * 0.35);
          rim = Math.max(1.5, rimW * (0.55 + lo2 * 0.9) + r() * 1.6);
        } else d = (r() - 0.5) * 0.5;
        outer.push([px + nx * d, py + ny * d]); inner.push([px + nx * (d + rim), py + ny * (d + rim)]);
      }
    };
    edge("t", 0, 0, w, 0, 0, 1); edge("r", w, 0, w, h, -1, 0); edge("b", w, h, 0, h, 0, -1); edge("l", 0, h, 0, 0, 1, 0);
    const poly = (P) => `polygon(${P.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(",")})`;
    return { outer: poly(outer), inner: poly(inner) };
  };

  HF.collage = function (K, parent, o = {}) {
    const tl = K.tl, Q = K.Q, W = o.w || K.width, H = o.h || K.height, rand = HF.rng(o.seed || 11), id = "cg" + uid++;
    const stage = K.el(parent, `left:${o.x || 0}px;top:${o.y || 0}px;width:${W}px;height:${H}px;overflow:hidden;perspective:${o.perspective || 1600}px;perspective-origin:50% 46%`);
    const cam = K.el(stage, `left:0;top:0;width:${W}px;height:${H}px;transform-style:preserve-3d;transform-origin:50% 50%`);
    // the board: oversized and pushed back, so it parallaxes less than the pieces on it
    if (o.board !== false) {
      const bz = -260, k = 1 + 260 / (o.perspective || 1600) + 0.18, bw = W * k, bh = H * k;
      const board = K.el(cam, `left:${(W - bw) / 2}px;top:${(H - bh) / 2}px;width:${bw}px;height:${bh}px;background:${o.boardColor || "radial-gradient(110% 80% at 50% 40%, #f7f2ea 0%, #efe8dd 62%, #e6ddcf 100%)"}`);
      board.innerHTML = `<svg width="100%" height="100%" style="position:absolute;inset:0;opacity:${o.mottle != null ? o.mottle : 0.16};mix-blend-mode:multiply"><filter id="${id}m" x="0" y="0" width="100%" height="100%">` +
        `<feTurbulence type="fractalNoise" baseFrequency="0.006 0.009" numOctaves="4" seed="${(o.seed || 11) + 3}"/><feColorMatrix values="0 0 0 0 0.45  0 0 0 0 0.36  0 0 0 0 0.26  0 0 0 -1.2 0.7"/></filter>` +
        `<rect width="100%" height="100%" filter="url(#${id}m)"/></svg>`;
      gsap.set(board, { z: bz });
    }
    // paper grain over everything: fixed-seed fractal noise, static
    if (o.grain !== false) {
      const g = K.el(stage, `left:0;top:0;width:${W}px;height:${H}px;pointer-events:none;z-index:9;mix-blend-mode:multiply;opacity:${o.grainOpacity || 0.5};will-change:transform`);
      g.innerHTML = `<svg width="${W}" height="${H}"><filter id="${id}g" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="${o.seed || 11}" stitchTiles="stitch"/>` +
        `<feColorMatrix values="0 0 0 0 0.24  0 0 0 0 0.18  0 0 0 0 0.12  0 0 0 -1.4 0.78"/></filter><rect width="100%" height="100%" filter="url(#${id}g)"/></svg>`;
    }
    const twos = new gsap.core.Timeline({ paused: true });                // piece motion, sampled at 12 fps (a free child, not a composition)
    const pieces = [];
    const NUDGE = Array.from({ length: 24 }, () => [(rand() - 0.5) * 1.6, (rand() - 0.5) * 1.6, (rand() - 0.5) * 0.3]);
    K.onFrame((t) => {
      const ts = Math.floor(t * 12 + 1e-6) / 12, step = Math.floor(t * 12 + 1e-6);
      twos.time(ts, true);
      for (const p of pieces) {                                               // resting boil: tiny, on twos
        if (p.boil && t >= p.restAt) { const n = NUDGE[(step + p.k * 7) % NUDGE.length]; p.el.style.translate = `${n[0].toFixed(2)}px ${n[1].toFixed(2)}px`; p.el.style.rotate = `${n[2].toFixed(3)}deg`; }
        else { p.el.style.translate = ""; p.el.style.rotate = ""; }
      }
    });
    const SHADOW = "drop-shadow(0 2px 2px rgba(45,28,12,.22)) drop-shadow(0 16px 22px rgba(45,28,12,.26))";
    const place = (el, a) => { gsap.set(el, { z: a.z || 0, rotation: a.rot || 0, x: 0, y: 0, scale: 1, opacity: 0, transformOrigin: "50% 50%" }); };
    const reg = (el, a) => { const p = { el, k: pieces.length, boil: a.boil !== false, restAt: 1e9, rot: a.rot || 0 }; pieces.push(p); el._cg = p; return el; };

    const cg = { stage, cam, twos };
    cg.tape = (host, a = {}) => {                                            // a strip of tape, on a piece (host) or the cam
      const r = HF.rng((o.seed || 11) * 97 + (a.seed || pieces.length * 13 + 5)), len = a.len || 150, th = a.th || 44, j = [];
      for (let i = 0; i <= 6; i++) j.push([i % 2 ? 5 + r() * 5 : r() * 3, (th * i) / 6]);
      const pts = [...j.map(([x, y]) => [x, y]), ...j.reverse().map(([x, y]) => [len - x, y])];
      const t = K.el(host, `left:${a.x || 0}px;top:${a.y || 0}px;width:${len}px;height:${th}px;transform:translate(-50%,-50%) rotate(${a.rot || 0}deg);` +
        `background:linear-gradient(180deg, rgba(255,255,255,.22), rgba(255,255,255,0) 40%, rgba(120,100,70,.06)), ${a.color || "rgba(238,228,204,.82)"};` +
        `clip-path:polygon(${pts.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(",")});z-index:5;mix-blend-mode:multiply`);
      return t;
    };
    const tapesFor = (el, w, h, list, a) => (list || []).forEach((s, i) => {
      const spec = typeof s === "string" ? { side: s } : s, side = spec.side || "top", k = (a.seed || 0) + i;
      const at = { top: [w * (spec.u != null ? spec.u : 0.5), 4], bottom: [w * (spec.u != null ? spec.u : 0.5), h - 4], tl: [26, 22], tr: [w - 26, 22], bl: [26, h - 22], br: [w - 26, h - 22] }[side];
      const rot = spec.rot != null ? spec.rot : { top: -3, bottom: 2, tl: -42, tr: 40, bl: 40, br: -40 }[side] + (k % 3 - 1) * 3;
      cg.tape(el, { x: at[0], y: at[1], rot, len: spec.len || (side.length === 2 ? 120 : 170), seed: k + 1 });
    });

    // a paper piece: an image (screenshot) or html, torn edges, rim, shadow, optional halftone print
    cg.piece = (a) => {
      const w = a.w, h = a.h, r = HF.rng((o.seed || 11) * 31 + pieces.length * 101 + (a.seed || 0));
      const sh = HF.torn(w, h, r, { torn: a.torn, amp: a.amp, rim: a.rim, border: a.border });
      const el = K.el(cam, `left:${a.x}px;top:${a.y}px;width:${w}px;height:${h}px;filter:${a.shadow === false ? "none" : SHADOW}`);
      K.el(el, `left:0;top:0;width:${w}px;height:${h}px;background:${a.paper || "#fffdf8"};clip-path:${sh.outer}`);
      const face = K.el(el, `left:0;top:0;width:${w}px;height:${h}px;overflow:hidden;clip-path:${sh.inner};background:${a.bg || "#fff"}`,
        a.img ? `<img src="${a.img}" alt="" style="position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;object-position:${a.pos || "50% 0%"};display:block">` : a.html || "");
      if (a.print) K.el(face, `left:0;top:0;width:100%;height:100%;background-image:radial-gradient(rgba(40,30,20,.5) 0.8px, transparent 1.25px);background-size:5px 5px;mix-blend-mode:multiply;opacity:${a.print === true ? 0.18 : a.print}`);
      if (a.img && a.tint !== false) K.el(face, `left:0;top:0;width:100%;height:100%;background:rgba(243,232,214,.16);mix-blend-mode:multiply`);   // printed on warm paper
      tapesFor(el, w, h, a.tape, a);
      place(el, a);
      return reg(el, a);
    };
    // a torn strip of paper with words on it (headline cut from a page)
    cg.strip = (text, a = {}) => {
      const size = a.size || 84, w = a.w || Math.round(text.length * size * 0.46 + 70), h = a.h || Math.round(size * 1.45);
      return cg.piece({ ...a, w, h, torn: a.torn || "all", amp: a.amp || 5, rim: a.rim != null ? a.rim : 0, bg: a.bg || a.paper || "#fffdf8",
        html: `<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding-top:${Math.round(size * 0.08)}px;` +
          `font:${a.italic ? "italic " : ""}${a.weight || 400} ${size}px/1 ${(a.font || "'InstrumentSerif', serif").replace(/"/g, "'")};letter-spacing:${a.track || "-.01em"};color:${a.color || C.ink};white-space:nowrap">${a.raw ? text : HF.esc(text)}</div>` });
    };
    // a halftone disc (dot radius falls off from the centre), on its own depth
    cg.halftone = (a = {}) => {
      const R = a.r || 320, sp = a.spacing || 15, ang = ((a.angle != null ? a.angle : 22) * Math.PI) / 180, col = a.color || C.acc;
      const dots = [];
      for (let i = -Math.ceil(R / sp) - 2; i <= Math.ceil(R / sp) + 2; i++) for (let j = -Math.ceil(R / sp) - 2; j <= Math.ceil(R / sp) + 2; j++) {
        const gx = i * sp, gy = j * sp, x = gx * Math.cos(ang) - gy * Math.sin(ang), y = gx * Math.sin(ang) + gy * Math.cos(ang), d = Math.hypot(x, y) / R;
        if (d >= 1) continue;
        const v = Math.pow(1 - d * d, a.falloff || 0.9), rr = sp * 0.52 * v;
        if (rr > 0.5) dots.push(`<circle cx="${(x + R).toFixed(1)}" cy="${(y + R).toFixed(1)}" r="${rr.toFixed(2)}"/>`);
      }
      const el = K.el(cam, `left:${a.x - R}px;top:${a.y - R}px;width:${2 * R}px;height:${2 * R}px`, `<svg width="${2 * R}" height="${2 * R}" fill="${col}" style="display:block">${dots.join("")}</svg>`);
      place(el, a);
      return reg(el, { ...a, boil: false });
    };
    // on twos: entrances and exits live on the 12 fps child timeline
    cg.enter = (el, t, a = {}) => {
      const p = el._cg, dur = a.dur || 0.42, from = a.from || "drop", rot = p.rot;
      const F = { drop: { y: -26, scale: 1.12, rotation: rot - 5 }, pop: { scale: 0.6, rotation: rot + 8 }, left: { x: -700, rotation: rot - 10 }, right: { x: 700, rotation: rot + 10 },
        up: { y: 900, rotation: rot + 6 }, down: { y: -900, rotation: rot - 6 } }[from];
      twos.fromTo(el, { opacity: from === "drop" || from === "pop" ? 0 : 1, x: 0, y: 0, scale: 1, ...F }, { opacity: 1, x: 0, y: 0, scale: 1, rotation: rot, duration: dur, ease: a.ease || (from === "drop" ? "power3.out" : "back.out(1.3)") }, t);
      if (from !== "drop" && from !== "pop") twos.set(el, { opacity: 0 }, 0), twos.set(el, { opacity: 1 }, t);
      p.restAt = t + dur + 0.1;
      if (a.sfx !== false) K.sfx(a.cue || (from === "drop" || from === "pop" ? "pop" : "swish"), t, a.cueDb || -26);
      return t + dur;
    };
    cg.exit = (el, t, a = {}) => { twos.to(el, { opacity: 0, y: a.y || -20, duration: a.dur || 0.25, ease: "power2.in" }, t); el._cg.restAt = 1e9; return cg; };
    // the camera: smooth GSAP moves of the rig; pieces at different z parallax against each other and the board
    let cs = { x: 0, y: 0, z: 0, rotationX: 0, rotationY: 0, rotation: 0 };
    gsap.set(cam, { ...cs });
    cg.move = (t, a = {}) => {
      const to = { x: a.x != null ? a.x : cs.x, y: a.y != null ? a.y : cs.y, z: a.z != null ? a.z : cs.z, rotationX: a.rx != null ? a.rx : cs.rotationX, rotationY: a.ry != null ? a.ry : cs.rotationY, rotation: a.rz != null ? a.rz : cs.rotation };
      tl.fromTo(cam, { ...cs }, { ...to, duration: a.dur || 1, ease: a.ease || "sine.inOut", immediateRender: false }, Q(t));
      cs = to; return cg;
    };
    let shown = false;
    cg.show = (a, b) => { if (!shown) { tl.set(stage, { autoAlpha: 0 }, 0); shown = true; } tl.set(stage, { autoAlpha: 1 }, Q(a)); if (b != null) tl.set(stage, { autoAlpha: 0 }, Q(b)); return cg; };
    return cg;
  };
})(typeof window !== "undefined" ? window : globalThis);
