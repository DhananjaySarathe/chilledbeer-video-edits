/* kit/hf/screen.js — annotated screen demonstrations (needs core.js).
 *
 *   const sd = HF.screen(K, layer, { x: 120, y: 110, w: 1340, h: 860, chrome: "browser", url: "github.com/...",
 *     src: "assets/screen.mp4", start: a, dur: b - a, mediaStart: 12.0,     // a screen recording (or img: "assets/x.png")
 *     srcW: 1920, srcH: 1080 });                                           // the recording's pixel size
 *   sd.zoom(t, [x, y, w, h])           // camera eases so that source rect fills the view (sd.reset(t) to fit again)
 *   sd.highlight(t, [x, y, w, h], { until, label: "Render", dim: true })
 *   sd.arrow(t, [x1, y1], [x2, y2], { until, label })
 *   sd.cursor([{ t, x, y }, ...], { clicks: [t, ...] })
 *   sd.callout(t, [x, y], "Click Render", { until, side: "right" })
 *   sd.blur([[x, y, w, h], ...], { from, until })                         // privacy
 *
 * Every coordinate is in SOURCE pixels (pick them with kit/hf/grid.py or find text with kit/hf/locate.py), so the
 * annotations stick to the content through every zoom and pan. The camera and all overlays are pure functions of time
 * (K.onFrame); fades are computed in the same pass.
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/screen.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";
  const clamp01 = (v) => Math.max(0, Math.min(1, v));
  const fadeAt = (t, a, b, f = 0.25) => (t < a || (b != null && t > b + f) ? 0 : Math.min(clamp01((t - a) / f), b != null ? clamp01((b + f - t) / f) : 1));

  HF.screen = function (K, parent, o) {
    const chromeH = o.chrome === "none" ? 0 : 46;
    const box = o.chrome === "none" ? K.el(parent, `left:${o.x}px;top:${o.y}px;width:${o.w}px;height:${o.h}px;border-radius:18px;overflow:hidden;background:#fff;box-shadow:0 40px 110px rgba(60,40,20,.22);opacity:0`)
      : HF.win(K, parent, o.x, o.y, o.w, o.h, o.url || o.title || "", null, { dark: o.dark });
    const view = o.chrome === "none" ? box : box.view;
    view.style.overflow = "hidden";
    const vw = o.w, vh = o.h - chromeH, SW = o.srcW, SH = o.srcH;
    const base = o.fit === "contain" ? Math.min(vw / SW, vh / SH) : vw / SW;   // default: fit the width (tall captures scroll)
    const world = K.el(view, `left:0;top:0;width:${SW}px;height:${SH}px;transform-origin:0 0;background:#fff`);
    if (o.src) world.innerHTML = `<video id="${K.vid("scr")}" class="clip" src="${o.src}" muted playsinline data-start="${(o.start || 0).toFixed(3)}" data-duration="${(o.dur || 10).toFixed(3)}" data-media-start="${o.mediaStart || 0}" data-track-index="${o.track || 4}" style="position:absolute;left:0;top:0;width:${SW}px;height:${SH}px"></video>`;
    else if (o.img) world.innerHTML = `<img src="${o.img}" style="position:absolute;left:0;top:0;width:${SW}px;height:${SH}px" alt="">`;
    const over = K.el(view, `left:0;top:0;width:${vw}px;height:${vh}px;pointer-events:none`);
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", vw); svg.setAttribute("height", vh); svg.style.cssText = "position:absolute;left:0;top:0;overflow:visible";
    // ---- camera: {cx, cy} = the source point at the view centre, z = zoom over the fit scale
    const cam0 = { cx: SW / 2, cy: Math.min(SH / 2, vh / base / 2), z: 1 };
    const cams = [];
    let camAt = null;
    const camera = (t) => {
      if (!camAt) camAt = HF.keyed(cams, cam0);
      const c = camAt(t), s = base * c.z;
      const hw = vw / s / 2, hh = vh / s / 2;                                 // keep the view inside the source
      c.cx = SW <= 2 * hw ? SW / 2 : Math.max(hw, Math.min(SW - hw, c.cx));
      c.cy = SH <= 2 * hh ? SH / 2 : Math.max(hh, Math.min(SH - hh, c.cy));
      c.s = s; c.tx = vw / 2 - c.cx * s; c.ty = vh / 2 - c.cy * s;
      return c;
    };
    const map = (c, x, y) => [c.tx + x * c.s, c.ty + y * c.s];
    const ann = [];                                                          // overlays redrawn every frame
    K.onFrame((t) => {
      const c = camera(t);
      world.style.transform = `translate(${c.tx.toFixed(2)}px, ${c.ty.toFixed(2)}px) scale(${c.s.toFixed(5)})`;
      ann.forEach((a) => a(t, c));
    });
    over.append(svg);

    const sd = { box, view, world };
    sd.show = (a, b) => { K.enter(box, a, { y: 40 }, 0.6); if (b != null) K.exit(box, b); return sd; };
    sd.zoom = (t, r, opt = {}) => {
      const pad = opt.pad != null ? opt.pad : 0.1, [x, y, w, h] = r;
      const z = Math.min(opt.max || 4, (vw * (1 - pad)) / (w * base), (vh * (1 - pad)) / (h * base));
      cams.push({ t, dur: opt.dur || 0.8, ease: opt.ease || "power3.inOut", v: { cx: x + w / 2, cy: y + h / 2, z: Math.max(opt.min || 1, z) } });
      camAt = null;
      return sd;
    };
    sd.pan = (t, cx, cy, opt = {}) => { cams.push({ t, dur: opt.dur || 1.2, ease: opt.ease || "power1.inOut", v: { cx, cy } }); camAt = null; return sd; };   // scroll a tall capture
    sd.reset = (t, opt = {}) => { cams.push({ t, dur: opt.dur || 0.7, ease: opt.ease || "power3.inOut", v: { ...cam0 } }); camAt = null; return sd; };

    // highlight: an accent box on the rect (optionally dimming the rest) with an optional label pill
    sd.highlight = (t, r, opt = {}) => {
      const hl = K.el(over, `left:0;top:0;border:4px solid ${C.acc};border-radius:12px;opacity:0;${opt.dim !== false ? "box-shadow:0 0 0 4000px rgba(27,24,21,.42);" : ""}`);
      const lab = opt.label ? K.el(over, `left:0;top:0;opacity:0;padding:8px 16px;border-radius:999px;background:${C.acc};color:#fff;font:700 22px Inter,sans-serif;white-space:nowrap`, HF.esc(opt.label)) : null;
      ann.push((tt, c) => {
        const k = fadeAt(tt, t, opt.until), [x, y] = map(c, r[0], r[1]), w = r[2] * c.s, h = r[3] * c.s, m = 6;
        hl.style.opacity = k.toFixed(3);
        hl.style.transform = `translate(${(x - m).toFixed(1)}px, ${(y - m).toFixed(1)}px)`; hl.style.width = (w + 2 * m).toFixed(1) + "px"; hl.style.height = (h + 2 * m).toFixed(1) + "px";
        if (lab) { lab.style.opacity = k.toFixed(3); const below = y + h + 60 < vh; lab.style.transform = `translate(${(x - m).toFixed(1)}px, ${(below ? y + h + 14 : y - 52).toFixed(1)}px)`; }
      });
      K.sfx("click", t);
      return sd;
    };
    // a hand-drawn accent arrow from one source point to another; it draws on over 0.5 s
    sd.arrow = (t, p0, p1, opt = {}) => {
      const path = document.createElementNS(NS, "path"), head = document.createElementNS(NS, "path");
      [path, head].forEach((e) => { e.setAttribute("fill", "none"); e.setAttribute("stroke", C.acc); e.setAttribute("stroke-width", 7); e.setAttribute("stroke-linecap", "round"); e.setAttribute("stroke-linejoin", "round"); svg.append(e); });
      const lab = opt.label ? K.el(over, `left:0;top:0;opacity:0;font:400 44px InstrumentSerif,serif;font-style:italic;color:${C.acc};white-space:nowrap`, HF.esc(opt.label)) : null;
      ann.push((tt, c) => {
        const k = fadeAt(tt, t, opt.until), draw = clamp01((tt - t) / 0.5);
        const [x0, y0] = map(c, ...p0), [x1, y1] = map(c, ...p1), bend = opt.bend != null ? opt.bend : 0.25;
        const mx = (x0 + x1) / 2 - (y1 - y0) * bend, my = (y0 + y1) / 2 + (x1 - x0) * bend;
        path.setAttribute("d", `M${x0} ${y0} Q${mx} ${my} ${x1} ${y1}`);
        const len = path.getTotalLength();
        path.style.strokeDasharray = len; path.style.strokeDashoffset = (len * (1 - draw)).toFixed(1);
        const a = Math.atan2(y1 - my, x1 - mx), s = 22;
        head.setAttribute("d", `M${x1 - s * Math.cos(a - 0.45)} ${y1 - s * Math.sin(a - 0.45)} L${x1} ${y1} L${x1 - s * Math.cos(a + 0.45)} ${y1 - s * Math.sin(a + 0.45)}`);
        path.setAttribute("opacity", k.toFixed(3)); head.setAttribute("opacity", (draw > 0.92 ? k : 0).toFixed(3));
        if (lab) { lab.style.opacity = (k * clamp01((tt - t - 0.3) / 0.25)).toFixed(3); lab.style.transform = `translate(${(x0 - 10).toFixed(1)}px, ${(y0 + (y0 < y1 ? -64 : 12)).toFixed(1)}px)`; }
      });
      K.sfx("swish", t, -24);
      return sd;
    };
    // a synthetic cursor following keyframes (eased per segment) with click ripples
    sd.cursor = (keys, opt = {}) => {
      const cur = document.createElementNS(NS, "g");
      cur.innerHTML = `<path d="M0 0 L0 34 L9 26 L15 40 L21 37 L15 24 L27 24 Z" fill="#fff" stroke="${C.ink}" stroke-width="2.5" stroke-linejoin="round"/>`;
      const rip = document.createElementNS(NS, "circle");
      rip.setAttribute("fill", "none"); rip.setAttribute("stroke", C.acc); rip.setAttribute("stroke-width", 4);
      svg.append(rip); svg.append(cur);
      const ks = keys.slice().sort((a, b) => a.t - b.t), ease = gsap.parseEase("power2.inOut"), clicks = opt.clicks || [];
      const t0 = ks[0].t, t1 = opt.until != null ? opt.until : ks[ks.length - 1].t + 1.5;
      ann.push((tt, c) => {
        let p = ks[0];
        for (let i = 0; i < ks.length - 1; i++) if (tt >= ks[i].t) { const a = ks[i], b = ks[i + 1]; const q = ease(clamp01((tt - a.t) / Math.max(0.01, b.t - a.t))); p = { x: a.x + (b.x - a.x) * q, y: a.y + (b.y - a.y) * q }; }
        if (tt >= ks[ks.length - 1].t) p = ks[ks.length - 1];
        const [x, y] = map(c, p.x, p.y), k = fadeAt(tt, t0 - 0.2, t1);
        const ck = clicks.find((ct) => tt >= ct && tt < ct + 0.5), press = ck != null ? 1 - 0.12 * Math.sin(clamp01((tt - ck) / 0.18) * Math.PI) : 1;
        cur.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${(1.15 * press).toFixed(3)})`); cur.setAttribute("opacity", k.toFixed(3));
        if (ck != null) { const q = clamp01((tt - ck) / 0.5); rip.setAttribute("cx", x); rip.setAttribute("cy", y); rip.setAttribute("r", (8 + 34 * q).toFixed(1)); rip.setAttribute("opacity", (1 - q).toFixed(3)); }
        else rip.setAttribute("opacity", "0");
      });
      clicks.forEach((ct) => K.sfx("click", ct, -20));
      return sd;
    };
    // a callout pill with a leader line to a source point
    sd.callout = (t, pt, text, opt = {}) => {
      const lab = K.el(over, `left:0;top:0;opacity:0;padding:12px 20px;border-radius:16px;background:#fff;box-shadow:0 14px 40px rgba(60,40,20,.2);font:600 26px Inter,sans-serif;color:${C.ink};white-space:nowrap`, HF.esc(text));
      const ln = document.createElementNS(NS, "path"), dot = document.createElementNS(NS, "circle");
      ln.setAttribute("stroke", C.ink); ln.setAttribute("stroke-width", 3); ln.setAttribute("fill", "none"); dot.setAttribute("r", 7); dot.setAttribute("fill", C.acc);
      svg.append(ln); svg.append(dot);
      const side = opt.side || "right", off = opt.offset || 120;
      ann.push((tt, c) => {
        const k = fadeAt(tt, t, opt.until), [x, y] = map(c, ...pt);
        const lw = lab.offsetWidth || 260, lx = side === "right" ? x + off : side === "left" ? x - off - lw : x - lw / 2, ly = side === "below" ? y + off : side === "above" ? y - off - 50 : y - 70;
        lab.style.opacity = k.toFixed(3); lab.style.transform = `translate(${lx.toFixed(1)}px, ${ly.toFixed(1)}px)`;
        const ax = side === "right" ? lx : side === "left" ? lx + lw : lx + lw / 2, ay = side === "below" ? ly : side === "above" ? ly + 50 : ly + 25;
        ln.setAttribute("d", `M${x} ${y} L${ax} ${ay}`); ln.setAttribute("opacity", k.toFixed(3));
        dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("opacity", k.toFixed(3));
      });
      K.sfx("pop", t);
      return sd;
    };
    // privacy blur over source rects (moves with the camera)
    sd.blur = (rects, opt = {}) => {
      rects.forEach((r) => {
        const b = K.el(over, `left:0;top:0;border-radius:10px;backdrop-filter:blur(${opt.amount || 14}px);-webkit-backdrop-filter:blur(${opt.amount || 14}px);background:rgba(243,238,230,.25)`);
        ann.push((tt, c) => {
          const on = (opt.from == null || tt >= opt.from) && (opt.until == null || tt <= opt.until), [x, y] = map(c, r[0], r[1]);
          b.style.display = on ? "" : "none";
          b.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`; b.style.width = (r[2] * c.s).toFixed(1) + "px"; b.style.height = (r[3] * c.s).toFixed(1) + "px";
        });
      });
      return sd;
    };
    return sd;
  };
})(typeof window !== "undefined" ? window : globalThis);
