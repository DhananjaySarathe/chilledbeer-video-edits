/* kit/hf/core.js — the shared motion vocabulary for paper-studio HyperFrames compositions.
 *
 *   const K = HF.kit({ tl, id: "myfilm", width: 1920, height: 1080, words: D.words, pieces: D.pieces });
 *   K.enter(el, t)  K.exit(el, t)  K.rise(K.words(parent, "Big *idea", style).ws, [t])  K.typeText(el, "...", t, 20)
 *   ... components (scenes.js, diagram.js, screen.js, code.js) take K as their first argument ...
 *   K.finish(totalSeconds);           // once, at the end: installs the per-frame driver and registers the timeline
 *
 * Rules baked in (preset_paper_studio): entrances 0.6 s power3.out with a short travel, exits 0.35 s power2.in, text
 * rises word by word in a mask, no bounces or glitches, every time quantised to the frame. Anything whose state is a
 * function of time (camera moves, flowing dots, cursors) registers K.onFrame(fn) and is redrawn from one linear
 * proxy tween, so seeking to any frame gives the same picture.
 */
(function (root) {
  const HF = root.HF || (root.HF = {});
  HF.version = "1.0.0";
  HF.C = { paper: "#f3eee6", card: "#ffffff", ink: "#1b1815", ink2: "#4a443d", mute: "#8a8178", acc: "#e2562b", accTint: "#fbe4dc",
    ok: "#2f8a5b", okTint: "#dcefe3", bad: "#c23b22", badTint: "#f7dcd5", line: "rgba(27,24,21,.1)" };
  HF.ICON = {
    cam: '<rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="M16 10l5-3v10l-5-3z"/>', broom: '<path d="M14 3l7 7M11 6l7 7-6 6H6v-6z"/><path d="M6 19l-3 2"/>',
    map: '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>', search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    code: '<path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/>', play: '<path d="M8 5.5v13l11-6.5z"/>', check: '<path d="M4.5 12.5l5 5 10-11"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>', bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>', music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    box: '<path d="M3 7l9-4 9 4-9 4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>', spark: '<path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6z"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>', chat: '<path d="M4 5h16v11H9l-5 4z"/>',
    film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>', layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/>', file: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>',
    cut: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.1 8.1L20 20M8.1 15.9L20 4"/>', sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    wave: '<path d="M3 12h2M7 8v8M11 5v14M15 8v8M19 10v4"/>', db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>', user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>', terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    cache: '<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  };
  HF.icon = (n, size = 32, stroke = "currentColor", width = 2.2, fill = "none") => {
    if (!HF.ICON[n]) throw new Error("HF.icon: no icon " + n);
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${fill}" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round">${HF.ICON[n]}</svg>`;
  };
  // named sound cues (kit/sfx) at the preset's levels
  HF.S = { swish: ["whoosh/whoosh__air-woosh__mixkit-1489", -21], slide: ["whoosh/whoosh__technology-transition-slide__mixkit-3120", -22],
    click: ["ui/ui__clear-mouse-clicks__mixkit-2997", -22], pop: ["ui/ui__bubble-pop-up-alert-notification__mixkit-2357", -23],
    check: ["ui/ui__modern-click-box-check__mixkit-1120", -21], type: ["typing/typing__typing-on-a-laptop-keyboard__mixkit-2531", -23],
    hit: ["impact/impact__short-bass-hit__mixkit-2299", -15], riser: ["riser/riser__cinematic-synth-riser__mixkit-645", -17],
    tone: ["ui/ui__confirmation-tone__mixkit-2867", -20], error: ["ui/ui__wrong-answer-fail-notification__mixkit-946", -20] };

  HF.esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  HF.kit = function (o) {
    const tl = o.tl, fps = o.fps || 30, W = o.width || 1920, H = o.height || 1080;
    const Wd = o.words || [], P = o.pieces || [];
    const frameFns = [];
    window.__CUES = window.__CUES || [];
    const K = { tl, fps, width: W, height: H, C: HF.C, icon: HF.icon, esc: HF.esc, words_: Wd, pieces: P };
    K.Q = (t) => Math.round(t * fps) / fps;
    K.W = (i) => { const w = Wd.find((x) => x.i === i); if (!w) throw new Error("HF: word " + i + " is not in the cut"); return w.t; };
    K.WE = (i) => { const w = Wd.find((x) => x.i === i); if (!w) throw new Error("HF: word " + i + " is not in the cut"); return w.e; };
    K.span = (tag) => { const ps = P.filter((p) => p.tag === tag); if (!ps.length) throw new Error("HF: no pieces tagged " + tag); return [ps[0].out_a, ps[ps.length - 1].out_b]; };
    K.sfx = (name, t, db) => {
      const s = HF.S[name];
      window.__CUES.push({ name: s ? s[0] : name, at: Math.round(t * 1000) / 1000, gain_db: db != null ? db : s ? s[1] : -20 });
    };
    K.el = (parent, style, html = "", cls = "hf-abs") => { const d = document.createElement("div"); d.className = cls; d.style.cssText = style; d.innerHTML = html; parent.append(d); return d; };
    K.$ = (id) => document.getElementById(id);
    // ---- motion vocabulary
    const Q = K.Q;
    K.show = (e, a, b) => { tl.set(e, { autoAlpha: 0 }, 0); tl.set(e, { autoAlpha: 1 }, Q(a)); if (b != null) tl.set(e, { autoAlpha: 0 }, Q(b)); return e; };
    K.enter = (e, t, from = {}, dur = 0.6) => tl.fromTo(e, { opacity: 0, y: 28, filter: "blur(8px)", ...from },
      { opacity: 1, x: 0, y: 0, scale: 1, rotation: 0, filter: "blur(0px)", duration: dur, ease: "power3.out" }, Q(t));
    K.exit = (e, t, to = {}) => tl.to(e, { opacity: 0, y: -16, filter: "blur(6px)", duration: 0.35, ease: "power2.in", ...to }, Q(t));
    K.fade = (e, t, dur = 0.4) => tl.fromTo(e, { opacity: 0 }, { opacity: 1, duration: dur, ease: "power1.out" }, Q(t));
    K.drift = (e, a, b, s1 = 1.035) => tl.fromTo(e, { scale: 1 }, { scale: s1, duration: Math.max(0.3, b - a), ease: "none", immediateRender: false }, Q(a));
    K.words = (parent, str, style) => {
      const box = K.el(parent, style, "", "hf-serif hf-abs"), ws = [];
      str.split("|").forEach((line, li) => {
        if (li) box.append(document.createElement("br"));
        line.trim().split(/\s+/).forEach((tok, i, arr) => {
          const m = document.createElement("span"); m.className = "hf-m";
          const w = document.createElement("span"); w.className = "hf-wi"; w.textContent = tok.replace(/^\*/, "");
          if (tok[0] === "*") { w.style.fontStyle = "italic"; w.style.color = HF.C.acc; }
          m.append(w); box.append(m); if (i < arr.length - 1) box.append(" ");
          ws.push(w);
        });
      });
      return { box, ws };
    };
    K.rise = (ws, ts, outAt) => ws.forEach((w, k) => {
      const t = ts[Math.min(k, ts.length - 1)] + (k >= ts.length ? (k - ts.length + 1) * 0.07 : 0);
      if (t <= 0) tl.set(w, { yPercent: 0 }, 0);                               // finished on frame 1
      else tl.fromTo(w, { yPercent: 115 }, { yPercent: 0, duration: 0.7, ease: "expo.out" }, Q(t));
      if (outAt != null) tl.to(w, { yPercent: -115, duration: 0.3, ease: "power2.in" }, Q(outAt + k * 0.025));
    });
    K.typeText = (e, text, t, cps, caret = true) => {
      const o = { n: 0 };
      tl.set(e, { textContent: caret ? "▍" : "" }, 0);
      tl.to(o, { n: text.length, duration: text.length / cps, ease: "none", onUpdate: () => { e.textContent = text.slice(0, Math.round(o.n)) + (caret && o.n < text.length ? "▍" : ""); } }, Q(t));
      return t + text.length / cps;
    };
    K.countUp = (e, a, b, t, dur, fmt = (v) => Math.round(v)) => {
      const o = { v: a };
      tl.set(e, { textContent: fmt(a) }, 0);
      tl.to(o, { v: b, duration: dur, ease: "power3.out", onUpdate: () => { e.textContent = fmt(o.v); } }, Q(t));
    };
    // ---- per-frame state (pure functions of time)
    K.onFrame = (fn) => { frameFns.push(fn); fn(0); };
    let vid = 0;
    K.vid = (prefix = "v") => `${prefix}${o.id || "hf"}${vid++}`;              // media need unique ids to be tracked
    K.finish = (total) => {
      const proxy = { t: 0 };
      if (frameFns.length) tl.fromTo(proxy, { t: 0 }, { t: total, duration: total, ease: "none", onUpdate: () => frameFns.forEach((f) => f(proxy.t)) }, 0);
      if (root.Stickman && root.Stickman.drive && o.stickman !== false) root.Stickman.drive(tl, total);
      window.__timelines = window.__timelines || {};
      window.__timelines[o.id] = tl;
    };
    return K;
  };

  // shared math for components with keyframed state: value of a list of {t, dur, ease, v} keys at time t
  HF.keyed = function (keys, initial) {
    const ks = keys.slice().sort((a, b) => a.t - b.t);
    let cur = initial, prev = null;
    for (const k of ks) {
      if (prev) cur = HF.lerpObj(prev.from, prev.to, prev.e(Math.max(0, Math.min(1, (k.t - prev.t) / prev.dur))));
      k.from = { ...cur }; k.to = { ...cur, ...k.v }; k.e = k.ease ? (typeof k.ease === "function" ? k.ease : gsap.parseEase(k.ease)) : gsap.parseEase("power2.inOut");
      prev = k;
    }
    return (t) => {
      for (let i = ks.length - 1; i >= 0; i--) {
        const k = ks[i];
        if (t >= k.t) return HF.lerpObj(k.from, k.to, k.e(Math.max(0, Math.min(1, (t - k.t) / k.dur))));
      }
      return { ...initial };
    };
  };
  HF.lerpObj = (a, b, p) => { const o = {}; for (const k in b) o[k] = typeof b[k] === "number" && typeof a[k] === "number" ? a[k] + (b[k] - a[k]) * p : b[k]; return o; };
})(typeof window !== "undefined" ? window : globalThis);
