/* kit/stickman/stickman.js — an ink-line stick figure for HyperFrames / GSAP compositions (preset_paper_studio look).
 *
 * The figure's pose is a pure function of time: keyframes and loops are stored as data and evaluated per frame, and one
 * linear proxy tween on the composition timeline redraws every figure. Seeking to any frame is exact.
 *
 *   const fig = Stickman.create(svgParentEl, { x: 760, ground: 860, scale: 1.3 });
 *   fig.set("type");                          // pose at t = 0
 *   fig.loop("type", 0, 2.3);                 // fingers going
 *   fig.to(2.3, "handsOnHead", 0.25, "power3.out");
 *   fig.to(3.1, "facepalm", 0.45);
 *   Stickman.drive(tl, totalSeconds);         // once, after all figures are set up
 *
 * Angles are degrees. 0 = the limb points straight down; positive swings toward screen-right. torso/neck: 0 upright,
 * positive leans right. Arms are relative to the torso, forearms to the upper arm, shins to the thigh. "x" moves the
 * figure, "lift" raises it (jumps), "s" scales it. The lowest foot always rests on the ground line.
 */
(function (root) {
  const NS = "http://www.w3.org/2000/svg";
  const RAD = Math.PI / 180;
  const INK = "#1b1815", PAPER = "#f3eee6", ACC = "#e2562b", MUTE = "#8a8178", OK = "#2f8a5b";
  // proportions in units (the figure stands ~350 units tall at scale 1)
  const B = { head: 30, neck: 9, torso: 122, upper: 66, fore: 60, thigh: 80, shin: 78, shoulder: 14 };
  const JOINTS = ["torso", "neck", "shL", "elL", "shR", "elR", "hipL", "knL", "hipR", "knR", "x", "lift", "s"];
  const BASE = { torso: 0, neck: 0, shL: -14, elL: -6, shR: 14, elR: 6, hipL: -9, knL: 4, hipR: 9, knR: -4, lift: 0 };

  // ------------------------------------------------------------------ pose library (partial poses merge onto the current one)
  const POSES = {
    stand: { torso: 0, neck: 0, shL: -14, elL: -6, shR: 14, elR: 6, hipL: -9, knL: 4, hipR: 9, knR: -4 },
    wave: { shR: 140, elR: 28, shL: -14, elL: -6, neck: -4 },
    pointRight: { torso: 3, shR: 92, elR: -2, shL: -16, elL: -8, neck: 6 },
    pointLeft: { torso: -3, shL: -92, elL: 2, shR: 16, elR: 8, neck: -6 },
    presentRight: { torso: 2, shR: 62, elR: 38, shL: -14, elL: -6, neck: 4 },
    presentLeft: { torso: -2, shL: -62, elL: -38, shR: 14, elR: 6, neck: -4 },
    pointUp: { shR: 138, elR: 26, shL: -16, elL: -8, neck: -3 },
    raiseHand: { shR: 142, elR: 20, shL: -14, elL: -6, neck: -4 },
    think: { torso: -2, neck: 9, shR: 85, elR: 160, shL: -10, elL: 80 },
    shrug: { neck: 7, shR: 46, elR: 60, shL: -46, elL: -60 },
    facepalm: { torso: 5, neck: -11, shR: 120, elR: 135, shL: -6, elL: 0, hipL: -6, knL: 6, hipR: 7, knR: -2 },
    handsOnHead: { neck: 0, shR: 100, elR: 121, shL: -100, elL: -121, hipL: -12, hipR: 12 },
    celebrate: { neck: 0, shR: 150, elR: 12, shL: -150, elL: -12, hipL: -15, knL: 2, hipR: 15, knR: -2 },
    type: { torso: 0, neck: 8, shR: 32, elR: -60, shL: -32, elL: 60 },
    holdOut: { shR: 40, elR: -82, shL: -40, elL: 82 },
    armsCrossed: { neck: -4, shR: 30, elR: -112, shL: -30, elL: 112 },
    slump: { torso: 7, neck: 24, shR: 9, elR: 2, shL: -12, elL: 0, hipL: -5, knL: 5, hipR: 6, knR: -3 },
    relax: { torso: -4, neck: -6, shR: 126, elR: 136, shL: -126, elL: -136 },
    sip: { neck: 4, shR: 84, elR: 158, shL: -16, elL: -8 },
    handOnHip: { shR: 40, elR: -95, shL: -14, elL: -6 },
    stop: { torso: -3, shR: 70, elR: 85, shL: -14, elL: -6, neck: -5 },
    sad: { torso: 0, neck: 16, shR: 11, elR: -4, shL: -11, elL: 4, hipL: -6, hipR: 6 },
  };

  // ------------------------------------------------------------------ easing (GSAP's when available, else smooth)
  const easeFn = (e) => {
    if (typeof e === "function") return e;
    if (root.gsap && root.gsap.parseEase) return root.gsap.parseEase(e || "power2.inOut");
    return (p) => p * p * (3 - 2 * p);
  };
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const mix = (a, b, p) => a + (b - a) * p;

  // ------------------------------------------------------------------ procedural loops (additive on joint angles; never idle)
  const LOOPS = {
    bob: (t, k) => ({ torso: Math.sin(t * 2.1) * 1.2 * k, neck: Math.sin(t * 2.1 + 1) * 1.6 * k, lift: (Math.sin(t * 4.2) * 0.5 + 0.5) * 2.2 * k }),
    type: (t, k) => ({ elR: Math.sin(t * 38) * 9 * k, elL: Math.sin(t * 38 + 2.1) * 9 * k, shR: Math.sin(t * 19) * 2 * k, shL: Math.sin(t * 19 + 1) * 2 * k, neck: Math.sin(t * 3) * 2 * k }),
    walk: (t, k) => {
      const w = Math.sin(t * 9);
      return { hipL: 22 * w * k, knL: Math.max(0, -w) * 30 * k, hipR: -22 * w * k, knR: -Math.max(0, w) * 30 * k,
        shL: -20 * w * k, shR: -20 * w * k, lift: Math.abs(Math.cos(t * 9)) * 6 * k };
    },
    wave: (t, k) => ({ elR: Math.sin(t * 16) * 22 * k }),
    nod: (t, k) => ({ neck: Math.sin(t * 9) * 7 * k }),
    shake: (t, k) => ({ torso: Math.sin(t * 47) * 2.2 * k, neck: Math.sin(t * 31) * 3 * k }),
    clap: (t, k) => { const c = (Math.sin(t * 14) * 0.5 + 0.5) * k; return { shR: -10 * c, elR: -30 * c, shL: 10 * c, elL: 30 * c }; },
    jump: (t, k) => ({ lift: Math.abs(Math.sin(t * 7)) * 46 * k, knL: 12 * k, knR: -12 * k }),
  };

  const ALL = [];
  let CLIPS = 0;

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  // ------------------------------------------------------------------ the figure
  function create(parent, o = {}) {
    const W = o.width || 1920, H = o.height || 1080;
    let svg = parent;
    if (!(parent instanceof SVGElement)) {
      svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, style: "position:absolute;left:0;top:0;overflow:visible" }, parent);
    }
    const ground = o.ground != null ? o.ground : H * 0.82;
    const ink = o.color || INK, lw = o.lineWidth || 9;
    const g = svgEl("g", { fill: "none", stroke: ink, "stroke-width": lw, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
    const parts = {};
    ["legL", "legR", "body", "armL", "armR"].forEach((n) => (parts[n] = svgEl("path", {}, g)));
    parts.head = svgEl("circle", { r: B.head, fill: o.headFill || PAPER }, g);
    const front = svgEl("g", {}, svg);                                       // props held in a hand draw above the figure

    const start = { ...BASE, x: o.x != null ? o.x : W / 2, s: o.scale || 1 };
    const keys = [], loops = [{ name: "bob", t0: -1e9, t1: 1e9, k: o.bob != null ? o.bob : 1 }], holds = [];
    let resolved = false;
    const fig = { svg, g, front, parts, ground, joints: {} };

    const full = (p) => (typeof p === "string" ? (POSES[p] || (() => { throw new Error("stickman: no pose " + p); })()) : p);
    fig.set = (pose) => { Object.assign(start, full(pose)); resolved = false; return fig; };
    // move toward `pose` starting at t, arriving at t + dur
    fig.to = (t, pose, dur = 0.35, ease = "power2.inOut") => { keys.push({ t, pose: full(pose), dur: Math.max(1e-3, dur), ease: easeFn(ease) }); resolved = false; return fig; };
    // an additive motion loop between t0 and t1 (fades in and out over 0.15 s); k = strength
    fig.loop = (name, t0, t1, k = 1) => { if (!LOOPS[name]) throw new Error("stickman: no loop " + name); loops.push({ name, t0, t1, k }); return fig; };
    // keep an element (a <g> made by Stickman.props) in a hand or on the head: dx/dy in units, rot in degrees
    fig.hold = (el, joint = "handR", t0 = -1e9, t1 = 1e9, opt = {}) => { front.appendChild(el); holds.push({ el, joint, t0, t1, ...opt }); return fig; };

    function resolve() {
      keys.sort((a, b) => a.t - b.t);
      let cur = { ...start }, prev = null;
      for (const k of keys) {
        if (prev) {
          const p = prev.ease(clamp01((k.t - prev.t) / prev.dur));
          const at = {};
          JOINTS.forEach((j) => (at[j] = mix(prev.from[j], prev.target[j], p)));
          cur = at;
        }
        k.from = { ...cur };
        k.target = { ...cur, ...k.pose };
        prev = k;
      }
      resolved = true;
    }
    function poseAt(t) {
      if (!resolved) resolve();
      let p = { ...start };
      for (let i = keys.length - 1; i >= 0; i--) {
        const k = keys[i];
        if (t >= k.t) {
          const q = k.ease(clamp01((t - k.t) / k.dur));
          JOINTS.forEach((j) => (p[j] = mix(k.from[j], k.target[j], q)));
          break;
        }
      }
      for (const L of loops) {
        if (t < L.t0 || t > L.t1) continue;
        const fade = clamp01(Math.min(t - L.t0, L.t1 - t) / 0.15);
        const off = LOOPS[L.name](t, L.k * fade);
        for (const j in off) p[j] += off[j];
      }
      return p;
    }
    fig.poseAt = poseAt;

    // forward kinematics, in frame pixels
    function solve(p) {
      const s = p.s, dir = (a, len) => [Math.sin(a * RAD) * len, Math.cos(a * RAD) * len];
      const up = (a, len) => [Math.sin(a * RAD) * len, -Math.cos(a * RAD) * len];
      const hip = [0, 0];
      const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
      const neckBase = add(hip, up(p.torso, B.torso));
      const shoulder = add(hip, up(p.torso, B.torso - B.shoulder));
      const head = add(neckBase, up(p.torso + p.neck, B.neck + B.head));
      const elbowL = add(shoulder, dir(p.torso + p.shL, B.upper)), handL = add(elbowL, dir(p.torso + p.shL + p.elL, B.fore));
      const elbowR = add(shoulder, dir(p.torso + p.shR, B.upper)), handR = add(elbowR, dir(p.torso + p.shR + p.elR, B.fore));
      const kneeL = add(hip, dir(p.hipL, B.thigh)), footL = add(kneeL, dir(p.hipL + p.knL, B.shin));
      const kneeR = add(hip, dir(p.hipR, B.thigh)), footR = add(kneeR, dir(p.hipR + p.knR, B.shin));
      const low = Math.max(footL[1], footR[1]);
      const ox = p.x, oy = ground - (low + p.lift) * s;
      const T = (q) => [ox + q[0] * s, oy + q[1] * s];
      return { s, hip: T(hip), neckBase: T(neckBase), shoulder: T(shoulder), head: T(head), elbowL: T(elbowL), handL: T(handL), elbowR: T(elbowR), handR: T(handR),
        kneeL: T(kneeL), footL: T(footL), kneeR: T(kneeR), footR: T(footR), angle: p.torso + p.neck };
    }
    fig.at = (t, joint = "head") => solve(poseAt(t))[joint];

    const P = (pts) => "M" + pts.map((q) => q[0].toFixed(2) + " " + q[1].toFixed(2)).join(" L");
    fig.draw = (t) => {
      const J = solve(poseAt(t));
      fig.joints = J;
      g.setAttribute("stroke-width", (lw * J.s).toFixed(2));
      parts.body.setAttribute("d", P([J.hip, J.neckBase]));
      parts.armL.setAttribute("d", P([J.shoulder, J.elbowL, J.handL]));
      parts.armR.setAttribute("d", P([J.shoulder, J.elbowR, J.handR]));
      parts.legL.setAttribute("d", P([J.hip, J.kneeL, J.footL]));
      parts.legR.setAttribute("d", P([J.hip, J.kneeR, J.footR]));
      parts.head.setAttribute("cx", J.head[0].toFixed(2)); parts.head.setAttribute("cy", J.head[1].toFixed(2));
      parts.head.setAttribute("r", (B.head * J.s).toFixed(2));
      for (const h of holds) {
        const on = t >= h.t0 && t <= h.t1, q = J[h.joint];
        h.el.style.display = on ? "" : "none";
        if (on && q) h.el.setAttribute("transform", `translate(${(q[0] + (h.dx || 0) * J.s).toFixed(2)} ${(q[1] + (h.dy || 0) * J.s).toFixed(2)}) rotate(${h.rot || 0}) scale(${(J.s * (h.scale || 1)).toFixed(3)})`);
      }
    };
    fig.draw(0);
    ALL.push(fig);
    return fig;
  }

  // one linear proxy tween redraws every figure from the timeline's time (seek-exact)
  function drive(tl, duration, figs = ALL) {
    const proxy = { t: 0 };
    tl.fromTo(proxy, { t: 0 }, { t: duration, duration, ease: "none", onUpdate: () => figs.forEach((f) => f.draw(proxy.t)) }, 0);
    figs.forEach((f) => f.draw(0));
  }

  // ------------------------------------------------------------------ props: ink line drawings (unit size ~ a hand-held object at scale 1)
  const props = {
    // a desk seen from the front: top at y, from x to x + w
    desk(svg, x, y, w, h = 150) {
      const g = svgEl("g", { fill: "none", stroke: INK, "stroke-width": 9, "stroke-linecap": "round" }, svg);
      svgEl("path", { d: `M${x} ${y} L${x + w} ${y}`, "stroke-width": 11 }, g);
      svgEl("path", { d: `M${x + 24} ${y} L${x + 24} ${y + h} M${x + w - 24} ${y} L${x + w - 24} ${y + h}` }, g);
      return g;
    },
    // a monitor standing on a surface at y (bottom of the stand), screen w x h; returns { g, screen } (draw content in screen)
    monitor(svg, x, y, w, h) {
      const g = svgEl("g", {}, svg);
      const top = y - 46 - h;
      svgEl("path", { d: `M${x + w / 2} ${y - 46} L${x + w / 2} ${y} M${x + w / 2 - 54} ${y} L${x + w / 2 + 54} ${y}`, stroke: INK, "stroke-width": 9, "stroke-linecap": "round", fill: "none" }, g);
      svgEl("rect", { x, y: top, width: w, height: h, rx: 18, fill: "#ffffff", stroke: INK, "stroke-width": 9 }, g);
      const clip = svgEl("clipPath", { id: "smscr" + (++CLIPS) }, g);                // deterministic ids (no Math.random)
      svgEl("rect", { x: x + 14, y: top + 14, width: w - 28, height: h - 28, rx: 8 }, clip);
      const screen = svgEl("g", { "clip-path": `url(#${clip.id})` }, g);
      return { g, screen, x: x + 14, y: top + 14, w: w - 28, h: h - 28 };
    },
    keyboard(svg, x, y, w = 150) {
      return svgEl("rect", { x, y: y - 14, width: w, height: 14, rx: 5, fill: INK }, svg);
    },
    // held props are drawn around (0, 0) = the hand; pass them to fig.hold()
    cup() {
      const g = document.createElementNS(NS, "g");
      svgEl("path", { d: "M-16 -26 L16 -26 L12 8 L-12 8 Z", fill: "#fff", stroke: INK, "stroke-width": 7, "stroke-linejoin": "round" }, g);
      svgEl("path", { d: "M16 -18 Q30 -14 14 0", fill: "none", stroke: INK, "stroke-width": 6, "stroke-linecap": "round" }, g);
      svgEl("path", { d: "M-6 -36 Q-12 -46 -6 -56 M6 -38 Q0 -48 6 -58", fill: "none", stroke: MUTE, "stroke-width": 4, "stroke-linecap": "round" }, g);
      return g;
    },
    file(label = "") {
      const g = document.createElementNS(NS, "g");
      svgEl("path", { d: "M-26 -70 L12 -70 L28 -54 L28 0 L-26 0 Z", fill: "#fff", stroke: INK, "stroke-width": 6, "stroke-linejoin": "round" }, g);
      svgEl("path", { d: "M-6 -46 L-6 -22 L14 -34 Z", fill: ACC }, g);
      if (label) svgEl("text", { x: 1, y: 22, "text-anchor": "middle", "font-family": "Inter, sans-serif", "font-weight": 700, "font-size": 18, fill: INK }, g).textContent = label;
      return g;
    },
    // a box with a lid (the "magic prompt box"); returns { g, lid }
    box(svg, x, y, w = 220, h = 150) {
      const g = svgEl("g", { stroke: INK, "stroke-width": 9, "stroke-linejoin": "round" }, svg);
      svgEl("rect", { x, y: y - h, width: w, height: h, rx: 10, fill: "#fff" }, g);
      const lid = svgEl("rect", { x: x - 12, y: y - h - 30, width: w + 24, height: 30, rx: 8, fill: ACC }, g);
      return { g, lid };
    },
  };

  // ------------------------------------------------------------------ emotes (accent marks near the head)
  // Returns the INNER group: animate it freely with GSAP (scale, y, opacity); its parent holds the position, so tweens
  // never overwrite where it sits.
  function emote(svg, kind, x, y, size = 1) {
    const pos = svgEl("g", { transform: `translate(${x} ${y}) scale(${size})` }, svg);
    const g = svgEl("g", { "stroke-linecap": "round", "stroke-linejoin": "round" }, pos);
    if (kind === "exclaim") {
      svgEl("path", { d: "M0 -60 L0 -14", stroke: ACC, "stroke-width": 14, fill: "none" }, g);
      svgEl("circle", { cx: 0, cy: 8, r: 8, fill: ACC }, g);
    } else if (kind === "question") {
      svgEl("path", { d: "M-18 -44 Q-18 -66 2 -66 Q22 -66 22 -48 Q22 -34 4 -26 L4 -10", stroke: ACC, "stroke-width": 12, fill: "none" }, g);
      svgEl("circle", { cx: 4, cy: 10, r: 7, fill: ACC }, g);
    } else if (kind === "sweat") {
      svgEl("path", { d: "M0 -34 Q16 -10 14 2 Q12 16 0 16 Q-12 16 -14 2 Q-16 -10 0 -34 Z", fill: "#ffffff", stroke: INK, "stroke-width": 5 }, g);
    } else if (kind === "spark") {
      svgEl("path", { d: "M0 -40 L9 -9 L40 0 L9 9 L0 40 L-9 9 L-40 0 L-9 -9 Z", fill: ACC }, g);
    } else if (kind === "shock") {
      svgEl("path", { d: "M-52 -40 L-30 -22 M0 -62 L0 -34 M52 -40 L30 -22", stroke: ACC, "stroke-width": 9, fill: "none" }, g);
    } else if (kind === "bulb") {
      svgEl("path", { d: "M-20 0 Q-34 -22 -26 -40 Q-14 -62 0 -62 Q14 -62 26 -40 Q34 -22 20 0 Z", fill: "#fff6d8", stroke: ACC, "stroke-width": 7 }, g);
      svgEl("path", { d: "M-14 12 L14 12 M-10 24 L10 24", stroke: INK, "stroke-width": 7, fill: "none" }, g);
    } else if (kind === "check") {
      svgEl("circle", { r: 34, fill: OK }, g);
      svgEl("path", { d: "M-15 1 L-4 12 L17 -11", stroke: "#fff", "stroke-width": 8, fill: "none" }, g);
    } else if (kind === "cross") {
      svgEl("circle", { r: 34, fill: ACC }, g);
      svgEl("path", { d: "M-12 -12 L12 12 M12 -12 L-12 12", stroke: "#fff", "stroke-width": 8, fill: "none" }, g);
    } else if (kind === "zz") {
      svgEl("text", { x: 0, y: 0, "font-family": "Inter, sans-serif", "font-weight": 800, "font-size": 44, fill: MUTE }, g).textContent = "z z";
    }
    return g;
  }

  root.Stickman = { create, drive, props, emote, POSES, LOOPS, COLORS: { INK, PAPER, ACC, MUTE, OK }, BONES: B };
})(typeof window !== "undefined" ? window : globalThis);
