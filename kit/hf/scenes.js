/* kit/hf/scenes.js — reusable paper-studio scene components (needs core.js).
 *
 *   const st = HF.stage(K, document.getElementById("root"), { aroll: "aroll" });   // layers + the speaker video
 *   HF.camera(K, st, { framing: { intro: "W", hook: "SR", demo: "PIP", ... } });     // a framing per tagged piece (+ motion.js)
 *   const L = HF.side(K, st, a, b);  HF.card(K, L, x, y, w, h, html);  HF.pill(K, L, x, y, html)
 *   const I = HF.insert(K, st, a, b);  HF.win(K, I, x, y, w, h, url, img); HF.scroll(K, win, 0, -900, t, dur)
 *   HF.lowerThird(K, st.top, { name, line, t });  HF.chapter(K, st.top, a, b, 1, "Record")
 *   HF.compare(K, L, {...});  HF.chat(K, L, {...});  HF.endCard(K, st.full, {...})
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/scenes.js needs core.js first");
  const C = HF.C;
  HF.COLS = { LEFT: 110, RIGHT: 1150, COLW: 680 };                         // side-content columns in 16:9

  // ---------------------------------------------------------------- stage: the layer stack every film uses
  HF.stage = function (K, rootEl, o = {}) {
    const el = K.el, W = K.width, H = K.height;
    el(rootEl, "", "", "hf-fill hf-paper");
    el(rootEl, "", "", "hf-fill hf-grain");
    const cam = el(rootEl, `left:0;top:0;width:${W}px;height:${H}px;z-index:2;filter:drop-shadow(0 22px 40px rgba(50,30,15,.28))`, "", "hf-abs");
    const wrap = el(cam, `left:0;top:0;width:1920px;height:1080px;transform-origin:0 0`, "", "hf-abs");
    if (o.aroll) { const v = document.getElementById(o.aroll); if (v) { v.style.cssText = "position:absolute;left:0;top:0;width:1920px;height:1080px"; wrap.append(v); } }
    const ring = el(rootEl, "border-radius:26px;border:5px solid #fff;z-index:5;opacity:0;pointer-events:none", "", "hf-abs");
    const layer = (z) => el(rootEl, `left:0;top:0;width:${W}px;height:${H}px;z-index:${z}`, "", "hf-abs");
    return { root: rootEl, cam, wrap, ring, ins: layer(3), cards: layer(5), top: layer(6), full: layer(8) };
  };

  // ---------------------------------------------------------------- the speaker: camera v2 (kit/hf/motion.js)
  // Layouts (16:9): W wide, M medium, C close, SR speaker right (content left), SL speaker left (content right), PIP corner
  // window, OFF hidden under a full-screen insert. mode "panel" (9:16): the face fills a lower panel (o.top), with an
  // optional full-screen hook (o.hook = [a, b]). A director picks the moves from the edit (HF.motion.direct: reframes at
  // new thoughts, punches, eased punches, snap zooms, slow pushes, zoom transitions, budgets); the transform is a pure
  // function of time (K.onFrame), and the motion-blurred frames of fast moves are baked by kit/motion/camera.py.
  //   HF.camera(K, st, { framing: { intro: "W", demo: "PIP" }, tags: { punch: [ids], joke: [ids], story: [[a, b]], section: [ids] } })
  //   HF.camera(K, st, { plan: D.camera })     // a plan from kit/motion/camera.py (same director, plus the baked blur)
  // Other options: format "long" | "reel", rules (override HF.motion.RULES), scales, pip, pipRadius, pipScale,
  // mode "panel" + top + hook, auto (false: tagged moves only), active [a, b] (only drive the camera inside), blur
  // (false: ignore baked frames), sfx (false: no swish cues). Returns the plan (P.log lists every decision).
  // HF.camera.v1 is the old camera (a new framing on every cut, 1.0/1.08 ...), kept for old templates and comparisons.
  HF.camera = function (K, st, o = {}) {
    if (!HF.motion) throw new Error("HF.camera needs kit/hf/motion.js (vendor.py MODULES)");
    const tl = K.tl, Q = K.Q, { wrap, cam, ring } = st, SMALL = HF.motion.SMALL;
    const P = o.plan || HF.motion.direct(Object.assign({ pieces: o.pieces || K.pieces, words: K.words_, fps: K.fps,
      width: K.width, height: K.height, view: o.mode === "panel" ? undefined : [K.width, K.height] }, o));
    if (P.mode === "panel") Object.assign(cam.style, { overflow: "hidden", filter: "none", top: P.top + "px", height: P.view[1] + "px" });
    // the corner face's ring, z-order and the OFF fades (the transform itself is per frame, below)
    const B = P.pip;
    Object.assign(ring.style, { left: B.x - 5 + "px", top: B.y - 5 + "px", width: B.s + 10 + "px", height: B.s + 10 + "px", borderRadius: B.radius + 5 + "px" });
    P.shots.forEach((sh, i) => {
      const pv = P.shots[i - 1];
      if (!pv) {
        if (SMALL[sh.layout]) tl.set(cam, { zIndex: 4 }, 0);
        if (sh.layout === "PIP") tl.set(ring, { opacity: 1 }, 0);
        if (sh.layout === "OFF") tl.set([cam, ring], { opacity: 0 }, 0);
        return;
      }
      const T0 = Q(sh.t0 - 0.22);
      if (SMALL[sh.layout] && !SMALL[pv.layout]) { tl.set(cam, { zIndex: 4 }, T0); if (sh.layout === "PIP") tl.to(ring, { opacity: 1, duration: 0.2 }, Q(T0 + 0.62)); }
      else if (!SMALL[sh.layout] && SMALL[pv.layout]) { tl.set(ring, { opacity: 0 }, T0); tl.set(cam, { zIndex: 2 }, Q(T0 + 0.6)); }
      if (sh.layout === "OFF" && pv.layout !== "OFF") tl.to([cam, ring], { opacity: 0, duration: 0.25 }, Q(sh.t0 - 0.2));
      if (pv.layout === "OFF" && sh.layout !== "OFF") { tl.to(cam, { opacity: 1, duration: 0.25 }, Q(sh.t0 - 0.2)); if (sh.layout === "PIP") tl.to(ring, { opacity: 1, duration: 0.25 }, Q(sh.t0 - 0.2)); }
    });
    if (o.hideAt != null) tl.to([cam, ring], { opacity: 0, duration: 0.2 }, Q(o.hideAt));
    // the motion-blurred frames of the fast moves, baked by kit/motion/camera.py: a clip over the A-roll for exactly
    // those frames (all-intra, so every frame seeks exactly)
    if (P.blur && o.blur !== false) P.blur.windows.forEach((w) => {
      const v = document.createElement("video");
      v.id = K.vid("mb"); v.className = "clip"; v.src = w.src; v.muted = true;
      v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
      // a tenth of a frame of slack both ways: HF picks the frame as floor(time * fps), and 77/30 printed as 2.56667 is
      // later than the frame itself (measured: the window's 2nd frame repeated, everything after it one frame late)
      v.dataset.start = ((w.f0 - 0.1) / P.fps).toFixed(5); v.dataset.duration = ((w.f1 - w.f0) / P.fps).toFixed(5);
      v.dataset.mediaStart = ((w.at + 0.1) / P.fps).toFixed(5); v.dataset.trackIndex = "3";
      v.style.cssText = `position:absolute;left:0;top:0;width:${w.view[0]}px;height:${w.view[1]}px;z-index:1`;
      cam.append(v);
    });
    if (!P.blur && P.moves.some((m) => m.kind === "snap" || m.kind === "ease" || m.kind === "zoomx"))
      console.warn("HF.camera: fast moves without motion blur; bake them with kit/motion/camera.py and pass { plan: D.camera }");
    window.__camera = P;                                                  // the director's decisions, for inspection
    const act = o.active || [-1, 1e9];
    K.onFrame((t) => {
      if (t < act[0] || t >= act[1]) return;
      const c = HF.motion.at(P, t);
      wrap.style.transform = `matrix(${c.m.map((v) => +v.toFixed(5)).join(",")})`;
      wrap.style.clipPath = c.clipCss;
      if (P.mode === "panel") { cam.style.top = c.top + "px"; cam.style.height = c.view[1] + "px"; }
    });
    if (o.sfx !== false) P.cues.forEach((c) => K.sfx(c.name, c.t, c.db));
    return P;
  };
  // ---------------------------------------------------------------- camera v1 (version 6): a new framing on every cut
  // W wide, M medium, C close, SR speaker right (content left), SL speaker left (content right), PIP corner window,
  // OFF hidden under a full-screen insert. Vertical films use mode "panel": the face fills a lower panel.
  const cameraV1 = function (K, st, o) {
    const tl = K.tl, Q = K.Q, P = o.pieces || K.pieces, framing = o.framing;
    const SC = Object.assign({ W: [1.0, 1.08], M: [1.14, 1.22], C: [1.3, 1.22], SR: [1.2, 1.28], SL: [1.32, 1.38] }, o.scales || {});
    const PIPBOX = Object.assign({ x: 1556, y: 716, s: 316 }, o.pip || {}), PIPS = o.pipScale || 0.5;
    const PR = o.pipRadius != null ? o.pipRadius : 26;                     // corner radius of the corner face (PIPBOX.s / 2 = a circle)
    const SW = 1920, SH = 1080, VW = K.width, VH = K.height;
    const { wrap, cam, ring } = st;
    if (o.mode === "panel") {                                              // 9:16: face panel from y = top to the bottom
      const top = o.top != null ? o.top : 880, ph = VH - top;
      cam.style.top = top + "px"; cam.style.height = ph + "px"; cam.style.overflow = "hidden"; cam.style.filter = "none";
      P.forEach((p, i) => {
        const [cx, cy] = p.face, s = i % 2 ? 1.12 : 1.0;
        const x = Math.min(0, Math.max(VW - SW * s, VW / 2 - cx * s)), y = Math.min(0, Math.max(ph - SH * s, ph * 0.45 - cy * s));
        const end = i + 1 < P.length ? P[i + 1].out_a : (o.until || p.out_b);
        tl.fromTo(wrap, { x, y, scale: s }, { x: x - (VW / 2) * s * 0.03, y: y - ph * 0.43 * s * 0.03, scale: s * 1.03, duration: Math.max(0.3, end - p.out_a), ease: "none", immediateRender: i === 0 }, Q(p.out_a));
      });
      return;
    }
    function place(lay, f, v) {
      const [cx, cy] = f;
      if (lay === "PIP" || lay === "OFF") {
        const s = PIPS, half = PIPBOX.s / 2 / s, fy = cy + 70;
        const clip = `inset(${(fy - half).toFixed(1)}px ${(SW - cx - half).toFixed(1)}px ${(SH - fy - half).toFixed(1)}px ${(cx - half).toFixed(1)}px round ${(PR / s).toFixed(1)}px)`;
        return { x: PIPBOX.x + PIPBOX.s / 2 - cx * s, y: PIPBOX.y + PIPBOX.s / 2 - fy * s, scale: s, clipPath: clip };
      }
      const s = SC[lay][v];
      const tx = lay === "SR" ? 1250 : lay === "SL" ? 640 : 960, ty = lay === "W" ? cy : 470;
      return { x: Math.min(0, Math.max(SW * (1 - s), tx - cx * s)), y: Math.min(0, Math.max(SH * (1 - s), ty - cy * s)), scale: s, clipPath: "inset(0px 0px 0px 0px round 0px)" };
    }
    Object.assign(ring.style, { left: PIPBOX.x - 5 + "px", top: PIPBOX.y - 5 + "px", width: PIPBOX.s + 10 + "px", height: PIPBOX.s + 10 + "px", borderRadius: PR + 5 + "px" });
    let prev = null, v = 0;
    const small = (l) => l === "PIP" || l === "OFF";
    P.forEach((p) => {
      const lay = framing[p.tag];
      if (!lay) throw new Error("HF.camera: no framing for tag " + p.tag);
      // same framing again: alternate the punch-in, except on very short pieces (an in-out flick reads worse than a jump)
      v = prev === lay ? (o.minToggle && p.out_b - p.out_a < o.minToggle ? v : 1 - v) : 0;
      const stt = place(lay, p.face, v), T = Q(p.out_a);
      const moved = !(prev === null || small(prev) === small(lay));
      if (!moved) tl.set(wrap, stt, T);
      else {
        const T0 = Q(p.out_a - 0.22);
        tl.to(wrap, { ...stt, duration: 0.6, ease: "power3.inOut" }, T0);
        if (small(lay)) { tl.set(cam, { zIndex: 4 }, T0); if (lay === "PIP") tl.to(ring, { opacity: 1, duration: 0.2 }, Q(T0 + 0.62)); }      // the ring after the face has landed
        else { tl.set(ring, { opacity: 0 }, T0); tl.set(cam, { zIndex: 2 }, Q(T0 + 0.6)); }
      }
      if (lay === "OFF" && prev !== "OFF") tl.to([cam, ring], { opacity: 0, duration: 0.25 }, Q(p.out_a - 0.2));
      if (prev === "OFF" && lay !== "OFF") { tl.to(cam, { opacity: 1, duration: 0.25 }, Q(p.out_a - 0.2)); if (lay === "PIP") tl.to(ring, { opacity: 1, duration: 0.25 }, Q(p.out_a - 0.2)); }
      if (!small(lay) && !moved && p.out_b - p.out_a > 2.2)                 // slow push-in: a held shot is never a still
        tl.fromTo(wrap, { scale: stt.scale, x: stt.x, y: stt.y }, { scale: stt.scale * 1.025, x: stt.x - 960 * stt.scale * 0.025, y: stt.y - 500 * stt.scale * 0.025,
          duration: p.out_b - p.out_a - 0.25, ease: "none", immediateRender: false }, T);
      prev = lay;
    });
    if (o.hideAt != null) tl.to([cam, ring], { opacity: 0, duration: 0.2 }, Q(o.hideAt));
  };

  HF.camera.v1 = cameraV1;

  // ---------------------------------------------------------------- layers
  HF.side = (K, st, a, b) => { const L = K.el(st.cards, `left:0;top:0;width:${K.width}px;height:${K.height}px`); K.show(L, a - 0.05, b + 0.45); return L; };
  HF.insert = (K, st, a, b, o = {}) => {
    const L = K.el(st.ins, `left:0;top:0;width:${K.width}px;height:${K.height}px;opacity:0`);
    K.el(L, "", "", o.dark ? "hf-fill hf-ink" : "hf-fill hf-paper"); if (!o.dark) K.el(L, "", "", "hf-fill hf-grain");
    K.tl.fromTo(L, { opacity: 0, y: 60 }, { opacity: 1, y: 0, duration: 0.55, ease: "power3.out" }, K.Q(a - 0.2));
    if (!o.keep) K.tl.to(L, { opacity: 0, duration: 0.35, ease: "power2.in" }, K.Q(b - 0.1)); else K.tl.set(L, { opacity: 0 }, K.Q(b + 0.5));
    if (o.sfx !== false) K.sfx("swish", a - 0.22);
    if (o.drift !== false) { L.style.transformOrigin = "50% 50%"; K.drift(L, a, b + 0.3, o.drift || 1.03); }   // never a still: QA flags holds > 0.6 s
    return L;
  };
  HF.card = (K, parent, x, y, w, h, html = "", extra = "") => K.el(parent, `left:${x}px;top:${y}px;width:${w}px;${h ? `height:${h}px;` : ""}opacity:0;${extra}`, html, "hf-card");
  HF.pill = (K, parent, x, y, html, extra = "") => K.el(parent, `left:${x}px;top:${y}px;opacity:0;${extra}`, html, "hf-pill");
  HF.win = (K, parent, x, y, w, h, url, img, o = {}) => {
    const d = K.el(parent, `left:${x}px;top:${y}px;width:${w}px;height:${h}px;opacity:0`, "", "hf-win" + (o.dark ? " dark" : ""));
    d.innerHTML = `<div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><div class="url">${HF.esc(url || "")}</div></div>` +
      `<div class="view">${img ? `<img src="${img}" style="position:absolute;left:0;top:0;width:100%;display:block" alt="">` : ""}</div>`;
    d.view = d.querySelector(".view");
    return d;
  };
  HF.scroll = (K, win, y0, y1, t, dur, ease = "power1.inOut") => K.tl.fromTo(win.querySelector(".view img"), { y: y0 }, { y: y1, duration: dur, ease }, K.Q(t));
  HF.phone = (K, parent, src, cx, cy, h, start, dur, media = 0, rot = 0) => {
    const w = Math.round((h * 9) / 16), p = K.el(parent, `left:${cx - w / 2}px;top:${cy - h / 2}px;width:${w}px;height:${h}px;border-radius:${Math.round(h * 0.07)}px;transform:rotate(${rot}deg)`, "", "hf-phone");
    p.innerHTML = `<video id="${K.vid("ph")}" class="clip" src="${src}" muted playsinline data-start="${start.toFixed(3)}" data-duration="${dur.toFixed(3)}" data-media-start="${media}" data-track-index="5"></video>`;
    return p;
  };

  // ---------------------------------------------------------------- the name title (intro) and chapter tags
  HF.lowerThird = (K, parent, o) => {
    const x = o.x != null ? o.x : 96, y = o.y != null ? o.y : K.height - 294, t0 = Math.max(0.25, o.t), hold = o.hold || 4.2;
    const lt = K.el(parent, `left:${x}px;top:${y}px;padding:26px 34px 24px 30px;border-radius:22px;background:rgba(255,255,255,.94);box-shadow:0 20px 50px rgba(60,40,20,.16);opacity:0`);
    lt.innerHTML = `<div style="display:flex;align-items:center;gap:22px"><div class="bar0" style="width:6px;height:96px;border-radius:3px;background:${C.acc};transform-origin:50% 100%"></div>` +
      `<div><div class="hf-serif" style="font-size:66px;line-height:1">${o.name.split(" ").map((n) => `<span class="hf-m"><span class="hf-wi">${HF.esc(n)}</span></span>`).join(" ")}</div>` +
      `<div class="sb" style="margin-top:10px;font:600 25px Inter,sans-serif;color:${C.ink2}">${HF.esc(o.line || "")}</div></div></div>`;
    K.tl.fromTo(lt, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.6, ease: "power3.out" }, K.Q(t0));
    K.tl.fromTo(lt.querySelector(".bar0"), { scaleY: 0 }, { scaleY: 1, duration: 0.5, ease: "power3.out" }, K.Q(t0 + 0.1));
    K.rise([...lt.querySelectorAll(".hf-wi")], [t0 + 0.15, t0 + 0.25]);
    K.fade(lt.querySelector(".sb"), t0 + 0.45);
    K.tl.to(lt, { opacity: 0, x: -20, duration: 0.4, ease: "power2.in" }, K.Q(t0 + hold));
    K.sfx("swish", t0, -22);
    return lt;
  };
  HF.chapter = (K, parent, a, b, num, name) => {
    const c = K.el(parent, `left:64px;top:56px;opacity:0;display:flex;align-items:center;gap:14px;padding:10px 22px 10px 10px;border-radius:999px;background:rgba(255,255,255,.95);box-shadow:0 10px 30px rgba(60,40,20,.12);font:700 24px Inter,sans-serif;white-space:nowrap`,
      `${num ? `<span style="width:40px;height:40px;border-radius:50%;background:${C.acc};color:#fff;display:inline-flex;align-items:center;justify-content:center;font:800 19px Inter,sans-serif">${num}</span>` : `<span style="width:12px;height:12px;margin-left:12px;border-radius:50%;background:${C.acc};display:inline-block"></span>`}${HF.esc(name)}`);
    K.tl.fromTo(c, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.5, ease: "power3.out" }, K.Q(a));
    K.tl.to(c, { opacity: 0, duration: 0.3 }, K.Q(b - 0.3));
    return c;
  };

  // ---------------------------------------------------------------- before / after: two aligned panels, row by row
  // o = { x, y, w, rowH, left: {title, tone: "bad"|"mute", rows: [text]}, right: {title, tone: "ok", rows: [text]},
  //       t, stagger, verdict: {side: "right", t} }   rows align across the two sides (row k left vs row k right)
  HF.compare = (K, parent, o) => {
    const x = o.x || 160, y = o.y || 220, w = o.w || 1600, gap = 40, cw = (w - gap) / 2, rowH = o.rowH || 92;
    const n = Math.max(o.left.rows.length, o.right.rows.length), head = 110, h = head + n * rowH + 30;
    const tone = { bad: [C.bad, C.badTint, "x"], ok: [C.ok, C.okTint, "check"], mute: [C.mute, "#efe8df", null] };
    const sides = [["left", o.left, x], ["right", o.right, x + cw + gap]].map(([key, s, sx]) => {
      const [col, tint, ic] = tone[s.tone || (key === "left" ? "bad" : "ok")];
      const cd = HF.card(K, parent, sx, y, cw, h, "", "padding:0;overflow:hidden");
      cd.innerHTML = `<div style="height:${head}px;display:flex;align-items:center;justify-content:space-between;padding:0 36px;border-bottom:1px solid ${C.line}">` +
        `<span class="hf-serif" style="font-size:56px;color:${key === "left" ? C.ink2 : C.ink}">${HF.esc(s.title)}</span>` +
        (ic ? `<span class="mk" style="width:58px;height:58px;border-radius:50%;background:${tint};display:inline-flex;align-items:center;justify-content:center;opacity:0">${HF.icon(ic, 30, col, 2.8)}</span>` : "") + `</div>`;
      const rows = s.rows.map((r, k) => K.el(cd, `left:0;top:${head + 16 + k * rowH}px;width:${cw}px;height:${rowH - 12}px;display:flex;align-items:center;gap:18px;padding:0 36px;opacity:0`,
        `<span style="width:10px;height:10px;border-radius:50%;background:${col};flex:none"></span><span style="font:600 30px/1.25 Inter,sans-serif;color:${C.ink}">${HF.esc(r)}</span>`));
      return { cd, rows, key };
    });
    const t = o.t;
    sides.forEach((s, i) => K.enter(s.cd, t + i * 0.12, { y: 30 }));
    for (let k = 0; k < n; k++) sides.forEach((s, i) => { if (s.rows[k]) K.enter(s.rows[k], (o.rowsAt && o.rowsAt[k] != null ? o.rowsAt[k] : t + 0.5 + k * (o.stagger || 0.45)) + i * 0.1, { x: 20, y: 0 }, 0.45); });
    if (o.verdict) {
      const win = sides.find((s) => s.key === o.verdict.side), lose = sides.find((s) => s.key !== o.verdict.side);
      sides.forEach((s) => { const m = s.cd.querySelector(".mk"); if (m) K.tl.to(m, { opacity: 1, duration: 0.25 }, K.Q(o.verdict.t)); });
      K.tl.to(lose.cd, { opacity: 0.55, duration: 0.35 }, K.Q(o.verdict.t));
      K.tl.to(win.cd, { scale: 1.02, duration: 0.3, ease: "power2.out" }, K.Q(o.verdict.t));
      K.sfx("check", o.verdict.t);
    }
    return sides;
  };

  // ---------------------------------------------------------------- chat explainer (you <-> an AI assistant), generic, no brand
  // o = { x, y, w, h, title, msgs: [{ from: "you"|"ai", text, t, cps }], thinking: [t0, t1] }
  HF.chat = (K, parent, o) => {
    const x = o.x, y = o.y, w = o.w || 760, h = o.h || 640;
    const box = HF.card(K, parent, x, y, w, h, "", "padding:0;overflow:hidden");
    box.innerHTML = `<div style="height:64px;display:flex;align-items:center;gap:12px;padding:0 26px;border-bottom:1px solid ${C.line}"><span style="width:14px;height:14px;border-radius:50%;background:${C.acc}"></span>` +
      `<span class="hf-lbl" style="font-size:16px;color:${C.mute}">${HF.esc(o.title || "Assistant")}</span></div><div class="msgs" style="position:absolute;left:0;top:64px;width:100%;bottom:0;overflow:hidden"></div>`;
    const area = box.querySelector(".msgs");
    K.enter(box, o.t != null ? o.t : o.msgs[0].t - 0.4);
    let yy = 26;
    o.msgs.forEach((m) => {
      const you = m.from === "you", bw = Math.min(w - 120, 30 + m.text.length * 15);
      const lines = Math.ceil((m.text.length * 15) / (w - 160)), bh = 34 + lines * 40;
      const b = K.el(area, `left:${you ? w - 26 - bw : 26}px;top:${yy}px;width:${bw}px;padding:16px 22px;border-radius:22px;${you ? `background:${C.ink};color:#fff;border-bottom-right-radius:8px` : `background:#f6f2ec;color:${C.ink};border-bottom-left-radius:8px`};font:600 28px/1.35 Inter,sans-serif;white-space:normal;opacity:0`);
      const tx = document.createElement("span"); b.append(tx);
      K.tl.fromTo(b, { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.35, ease: "power3.out" }, K.Q(m.t));
      if (m.cps) K.typeText(tx, m.text, m.t + 0.1, m.cps, false); else tx.textContent = m.text;
      K.sfx(you ? "click" : "pop", m.t);
      yy += bh + 18;
    });
    if (o.thinking) {
      const th = K.el(area, `left:26px;top:${yy}px;padding:14px 22px;border-radius:22px;background:#f6f2ec;font:600 26px Inter,sans-serif;color:${C.mute};opacity:0`, "Thinking…");
      K.show(th, o.thinking[0], o.thinking[1]);
      K.tl.fromTo(th, { opacity: 0.4 }, { opacity: 1, duration: 0.5, repeat: Math.max(1, Math.floor((o.thinking[1] - o.thinking[0]) / 0.5)), yoyo: true, ease: "sine.inOut", immediateRender: false }, K.Q(o.thinking[0]));
    }
    return box;
  };

  // ---------------------------------------------------------------- end card
  HF.endCard = (K, parent, o) => {
    const t0 = o.t, S = K.el(parent, `left:0;top:0;width:${K.width}px;height:${K.height}px;opacity:0`);
    K.el(S, "", "", "hf-fill hf-paper"); K.el(S, "", "", "hf-fill hf-grain");
    K.tl.set(S, { opacity: 1 }, K.Q(t0));
    const hy = K.height / 2 - 240;
    const h = K.words(S, o.title || "Edited with *Claude.", `left:0;width:${K.width}px;top:${hy}px;font-size:${K.width < 1200 ? 140 : 190}px;text-align:center`);
    K.rise(h.ws, h.ws.map((_, i) => t0 + 0.1 + i * 0.08));
    if (o.sub) { const s1 = K.el(S, `left:0;width:${K.width}px;top:${hy + 260}px;text-align:center;font:500 34px Inter,sans-serif;color:${C.ink2};opacity:0`, HF.esc(o.sub)); K.fade(s1, t0 + 0.6); }
    const cta = K.el(S, `left:${K.width / 2 - 225}px;top:${hy + 380}px;width:450px;padding:24px 0;border-radius:999px;background:${C.acc};color:#fff;text-align:center;font:700 40px Inter,sans-serif;box-shadow:0 18px 44px rgba(226,86,43,.35);opacity:0`, HF.esc(o.cta || "Subscribe"));
    K.enter(cta, t0 + 0.9, { y: 20 });
    if (o.handle) { const hd = K.el(S, `left:0;width:${K.width}px;top:${hy + 520}px;text-align:center;font:600 32px Inter,sans-serif;color:${C.mute};opacity:0`, HF.esc(o.handle)); K.fade(hd, t0 + 1.2); }
    K.sfx("tone", t0 + 0.9);
    return S;
  };
})(typeof window !== "undefined" ? window : globalThis);
