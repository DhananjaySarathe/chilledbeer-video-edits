/* kit/hf/diagram.js — the living diagram: one diagram that develops across passages (needs core.js).
 *
 *   const dg = HF.diagram(K, layer, { title: "My whole workflow", layout: "row",
 *     nodes: [{ id: "rec", label: "Record", sub: "one take", icon: "cam" }, ...], edges: [["rec", "clean"], ...] });
 *   dg.show(a1, b1); dg.show(a2, b2);             // visible windows; its state carries over between them
 *   dg.reveal("rec", t)  dg.connect("rec", "clean", t)  dg.focus("clean", t)  dg.overview(t)
 *   dg.flow("rec", "clean", t, { dur: 1.2, dots: 3 })  dg.done("rec", t)  dg.note("clean", t, "skill file", until)
 *
 * Nodes are placed in a world (layout "row" | "column" | "grid", or explicit x/y); the camera (focus/overview) and the
 * flowing dots are pure functions of time (K.onFrame), node and edge reveals are timeline tweens. Works in 16:9 and
 * 9:16 (use layout "column" for vertical).
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/diagram.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";

  HF.diagram = function (K, parent, o) {
    const tl = K.tl, Q = K.Q;
    const vx = o.x || 0, vy = o.y || 0, vw = o.w || K.width, vh = o.h || K.height;
    const view = K.el(parent, `left:${vx}px;top:${vy}px;width:${vw}px;height:${vh}px;overflow:hidden`);
    const world = K.el(view, `left:0;top:0;width:${vw}px;height:${vh}px;transform-origin:0 0`);
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", vw); svg.setAttribute("height", vh); svg.style.cssText = "position:absolute;left:0;top:0;overflow:visible";
    world.append(svg);
    const shape = o.shape || "circle", R = shape === "circle" ? 60 : 0, CW = o.cardW || 300, CH = o.cardH || 120;
    // ---- layout (world coordinates = viewport pixels at zoom 1)
    const N = o.nodes.length, pad = o.pad != null ? o.pad : 0.12;
    o.nodes.forEach((n, i) => {
      if (n.x != null && n.y != null) return;
      if ((o.layout || "row") === "row") { n.x = vw * pad + (vw * (1 - 2 * pad) * (N === 1 ? 0.5 : i / (N - 1))); n.y = vh * (o.rowY || 0.47); }
      else if (o.layout === "column") { n.x = vw / 2; n.y = vh * pad + (vh * (1 - 2 * pad) * (N === 1 ? 0.5 : i / (N - 1))); }
      else { const cols = o.cols || Math.ceil(Math.sqrt(N)), r = Math.floor(i / cols), c = i % cols, rows = Math.ceil(N / cols);
        n.x = vw * pad + (vw * (1 - 2 * pad)) * (cols === 1 ? 0.5 : c / (cols - 1)); n.y = vh * 0.25 + (vh * 0.55) * (rows === 1 ? 0.5 : r / (rows - 1)); }
    });
    const byId = {};
    const kick = (n, i) => (n.kicker != null ? n.kicker : o.steps === false ? "" : "Step " + (i + 1));   // the small label above a node
    o.nodes.forEach((n, i) => {
      byId[n.id] = n;
      const box = K.el(world, `left:${n.x - (shape === "circle" ? 130 : CW / 2)}px;top:${n.y - (shape === "circle" ? 60 : CH / 2)}px;width:${shape === "circle" ? 260 : CW}px;text-align:center;opacity:0`);
      if (shape === "circle") {
        box.innerHTML = `<div class="ic" style="position:relative;margin:0 auto;width:120px;height:120px;border-radius:50%;background:#fff;box-shadow:0 14px 40px rgba(60,40,20,.14);display:flex;align-items:center;justify-content:center">` +
          `<span class="i1" style="display:flex">${HF.icon(n.icon || "spark", 50, C.acc, 2.2)}</span><span class="i2" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0;border-radius:50%;background:${C.okTint}">${HF.icon("check", 52, C.ok, 2.6)}</span>` +
          `<span class="ring" style="position:absolute;inset:-10px;border-radius:50%;border:4px solid ${C.acc};opacity:0"></span></div>` +
          (kick(n, i) ? `<div class="hf-lbl" style="margin-top:24px;font-size:16px;color:${C.mute}">${HF.esc(kick(n, i))}</div>` : "") +
          `<div class="hf-serif" style="margin-top:8px;font-size:${o.labelSize || 54}px">${HF.esc(n.label)}</div>` +
          (n.sub ? `<div style="margin-top:8px;font:500 21px Inter,sans-serif;color:${C.ink2};white-space:nowrap">${HF.esc(n.sub)}</div>` : "");
      } else {
        box.className = "hf-abs hf-card"; box.style.height = CH + "px"; box.style.textAlign = "left";
        box.innerHTML = `<div style="display:flex;align-items:center;gap:20px;height:100%;padding:0 26px"><div class="ic" style="position:relative;width:64px;height:64px;border-radius:18px;background:${C.accTint};display:flex;align-items:center;justify-content:center;flex:none">` +
          `<span class="i1" style="display:flex">${HF.icon(n.icon || "spark", 36, C.acc, 2.2)}</span><span class="i2" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0;border-radius:18px;background:${C.okTint}">${HF.icon("check", 36, C.ok, 2.6)}</span></div>` +
          `<div><div class="hf-serif" style="font-size:42px">${HF.esc(n.label)}</div>${n.sub ? `<div style="margin-top:4px;font:500 20px Inter,sans-serif;color:${C.ink2}">${HF.esc(n.sub)}</div>` : ""}</div></div>` +
          `<span class="ring" style="position:absolute;inset:-8px;border-radius:32px;border:4px solid ${C.acc};opacity:0"></span>`;
      }
      n.el = box;
    });
    // ---- edges
    const edges = {};
    const anchor = (a, b) => {
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
      if (shape === "circle") return [a.x + (dx / d) * (R + 22), a.y + (dy / d) * (R + 22)];
      return Math.abs(dx) * CH > Math.abs(dy) * CW ? [a.x + Math.sign(dx) * (CW / 2 + 16), a.y] : [a.x, a.y + Math.sign(dy) * (CH / 2 + 16)];
    };
    (o.edges || []).forEach((e) => {
      const [f, t] = Array.isArray(e) ? e : [e.from, e.to], A = byId[f], B = byId[t];
      if (!A || !B) throw new Error("HF.diagram: edge " + f + " -> " + t + " has an unknown node");
      const p0 = anchor(A, B), p1 = anchor(B, A), bend = (Array.isArray(e) ? e[2] : e.curve) || 0;
      const mx = (p0[0] + p1[0]) / 2 - (p1[1] - p0[1]) * bend, my = (p0[1] + p1[1]) / 2 + (p1[0] - p0[0]) * bend;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", `M${p0[0]} ${p0[1]} Q${mx} ${my} ${p1[0]} ${p1[1]}`);
      path.setAttribute("fill", "none"); path.setAttribute("stroke", C.ink); path.setAttribute("stroke-opacity", "0.28");
      path.setAttribute("stroke-width", "4"); path.setAttribute("stroke-linecap", "round");
      svg.append(path);
      const len = path.getTotalLength();
      path.style.strokeDasharray = len; path.style.strokeDashoffset = len;
      const head = document.createElementNS(NS, "path");
      const ang = Math.atan2(p1[1] - my, p1[0] - mx), hx = p1[0], hy = p1[1], s = 14;
      head.setAttribute("d", `M${hx - s * Math.cos(ang - 0.5)} ${hy - s * Math.sin(ang - 0.5)} L${hx} ${hy} L${hx - s * Math.cos(ang + 0.5)} ${hy - s * Math.sin(ang + 0.5)}`);
      head.setAttribute("fill", "none"); head.setAttribute("stroke", C.ink); head.setAttribute("stroke-opacity", "0.28"); head.setAttribute("stroke-width", "4");
      head.setAttribute("stroke-linecap", "round"); head.setAttribute("stroke-linejoin", "round"); head.style.opacity = 0;
      svg.append(head);
      edges[f + ">" + t] = { path, head, len };
    });
    const title = o.title ? K.el(view, `left:0;width:${vw}px;top:${o.titleY || vh * 0.17}px;text-align:center;opacity:0`, HF.esc(o.title), "hf-lbl hf-abs") : null;
    // ---- camera (pure function of time)
    const cams = [];
    const cam = { cx: vw / 2, cy: vh / 2, z: 1 };
    let camAt = null;
    K.onFrame((t) => {
      if (!camAt) camAt = HF.keyed(cams, cam);
      const c = camAt(t);
      world.style.transform = `translate(${(vw / 2 - c.cx * c.z).toFixed(2)}px, ${(vh / 2 - c.cy * c.z).toFixed(2)}px) scale(${c.z.toFixed(4)})`;
    });
    const flows = [];
    K.onFrame((t) => {
      for (const f of flows) {
        f.dots.forEach((d, k) => {
          const p = (t - f.t) / f.dur - k * f.gap;
          const on = p > 0 && p < 1;
          d.setAttribute("opacity", on ? Math.min(1, Math.min(p, 1 - p) * 8).toFixed(3) : "0");
          if (on) { const q = f.path.getPointAtLength(p * f.len); d.setAttribute("cx", q.x.toFixed(2)); d.setAttribute("cy", q.y.toFixed(2)); }
        });
      }
    });
    const ids = (x) => (Array.isArray(x) ? x : [x]);
    const dg = { nodes: byId, view, world };
    // show() may be called several times: later windows must not re-hide at 0
    let shown = false;
    view.style.transformOrigin = "50% 50%";
    dg.show = (a, b) => {
      if (!shown) { tl.set(view, { autoAlpha: 0 }, 0); shown = true; }
      tl.set(view, { autoAlpha: 1 }, Q(a)); if (b != null) tl.set(view, { autoAlpha: 0 }, Q(b));
      if (title) K.fade(title, a, 0.3);
      if (b != null && o.drift !== false) K.drift(view, a, b, 1.03);         // a slow push while it's up: never a still
      return dg;
    };
    dg.reveal = (x, t, stagger = 0.14) => { ids(x).forEach((id, k) => { K.enter(byId[id].el, t + k * stagger, { y: 30 }); }); K.sfx("click", t); return dg; };
    dg.connect = (f, to, t, dur = 0.5) => {
      const e = edges[f + ">" + to]; if (!e) throw new Error("HF.diagram: no edge " + f + " -> " + to);
      tl.fromTo(e.path, { strokeDashoffset: e.len }, { strokeDashoffset: 0, duration: dur, ease: "power2.inOut" }, Q(t));
      tl.to(e.head, { opacity: 1, duration: 0.15 }, Q(t + dur - 0.1));
      return dg;
    };
    dg.connectAll = (t, dur = 0.5, stagger = 0.15) => { Object.keys(edges).forEach((k, i) => { const [f, to] = k.split(">"); dg.connect(f, to, t + i * stagger, dur); }); return dg; };
    dg.focus = (x, t, opt = {}) => {
      const ns = ids(x).map((id) => byId[id]);
      const bw = shape === "circle" ? 300 : CW + 60, bh = shape === "circle" ? 360 : CH + 80;
      const x0 = Math.min(...ns.map((n) => n.x)) - bw / 2, x1 = Math.max(...ns.map((n) => n.x)) + bw / 2;
      const y0 = Math.min(...ns.map((n) => n.y)) - bh / 3, y1 = Math.max(...ns.map((n) => n.y)) + (bh * 2) / 3;
      const z = Math.min(opt.zoom || 1.7, vw / (x1 - x0), vh / (y1 - y0));
      cams.push({ t, dur: opt.dur || 0.8, ease: opt.ease || "power3.inOut", v: { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, z } }); camAt = null;
      o.nodes.forEach((n) => tl.to(n.el, { opacity: ns.includes(n) ? 1 : (opt.dim != null ? opt.dim : 0.3), duration: 0.4 }, Q(t)));
      if (title) tl.to(title, { opacity: 0, duration: 0.3 }, Q(t));
      return dg;
    };
    dg.overview = (t, opt = {}) => {
      cams.push({ t, dur: opt.dur || 0.8, ease: opt.ease || "power3.inOut", v: { cx: vw / 2, cy: vh / 2, z: 1 } }); camAt = null;
      o.nodes.forEach((n) => tl.to(n.el, { opacity: 1, duration: 0.4 }, Q(t)));
      if (title) tl.to(title, { opacity: 1, duration: 0.3 }, Q(t + 0.3));
      return dg;
    };
    dg.done = (x, t, stagger = 0.12) => { ids(x).forEach((id, k) => { const e = byId[id].el; tl.to(e.querySelector(".i2"), { opacity: 1, duration: 0.3 }, Q(t + k * stagger)); tl.fromTo(e.querySelector(".ic"), { scale: 1 }, { scale: 1.08, duration: 0.15, yoyo: true, repeat: 1 }, Q(t + k * stagger)); }); K.sfx("check", t); return dg; };
    dg.highlight = (id, t, until) => { const r = byId[id].el.querySelector(".ring"); tl.fromTo(r, { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.3, ease: "power3.out" }, Q(t)); if (until != null) tl.to(r, { opacity: 0, duration: 0.3 }, Q(until)); return dg; };
    dg.note = (id, t, text, until) => {
      const n = byId[id], nt = K.el(world, `left:${n.x - 200}px;top:${n.y + (shape === "circle" ? 220 : CH / 2 + 24)}px;width:400px;display:flex;justify-content:center;opacity:0`,
        `<span class="hf-pill" style="position:relative;font-size:22px;padding:10px 18px;background:${C.ink};color:#fff">${HF.esc(text)}</span>`);
      K.enter(nt, t, { y: 12 }); if (until != null) K.exit(nt, until);
      return dg;
    };
    dg.flow = (f, to, t, opt = {}) => {
      const e = edges[f + ">" + to]; if (!e) throw new Error("HF.diagram: no edge " + f + " -> " + to);
      const n = opt.dots || 3, dots = [];
      for (let k = 0; k < n; k++) { const d = document.createElementNS(NS, "circle"); d.setAttribute("r", opt.r || 9); d.setAttribute("fill", opt.color || C.acc); d.setAttribute("opacity", "0"); svg.append(d); dots.push(d); }
      flows.push({ path: e.path, len: e.len, t, dur: opt.dur || 1.0, gap: opt.gap || 0.18, dots });
      return dg;
    };
    return dg;
  };
})(typeof window !== "undefined" ? window : globalThis);
