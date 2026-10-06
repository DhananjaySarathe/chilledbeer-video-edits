/* ChilledBeer Video Edits graphics runtime: a deterministic clock for HTML templates.

   Rules for templates (the renderer depends on them):
   - All motion comes from GFX.anim / GFX.in / GFX.out (Web Animations) or GFX.each / GFX.tween / GFX.count /
     GFX.type (per-frame callbacks). CSS @keyframes animations are allowed too (they start at scene time 0).
   - Never use setTimeout, setInterval, requestAnimationFrame, Date, Math.random, or CSS transitions for motion:
     the renderer seeks frames out of order and must get the same picture every time. Use GFX.rand(seed).
   - Times are milliseconds from the start of the scene; GFX.duration is the scene length.
*/
(() => {
  const cfg = window.__GFX__ || {};
  const layouts = [];    // run once after fonts load (text measuring), before the first frame
  const cues = [];       // sound cues the template emits: {at (s), name, gain_db}
  const hooks = [];      // per-frame callbacks {fn, from, to}
  const decodes = [];    // image decodes the current frame must wait for

  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const E = {
    linear: (t) => t,
    out: (t) => 1 - Math.pow(1 - t, 3),
    in: (t) => t * t * t,
    inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    back: (t) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
    expo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),
  };
  const CSS_EASE = {
    linear: "linear",
    out: "cubic-bezier(.22,1,.36,1)",
    in: "cubic-bezier(.55,0,1,.45)",
    inOut: "cubic-bezier(.65,0,.35,1)",
    back: "cubic-bezier(.34,1.56,.64,1)",
    snap: "cubic-bezier(.2,1.5,.35,1)",
    expo: "cubic-bezier(.16,1,.3,1)",
  };
  const list = (x) => (Array.isArray(x) ? x : x instanceof NodeList ? [...x] : [x]);

  // Entrance presets: [from keyframe, to keyframe]. Exits play them in reverse.
  const PRESETS = {
    fade: [{ opacity: 0 }, { opacity: 1 }],
    pop: [{ opacity: 0, transform: "scale(.55)" }, { opacity: 1, transform: "scale(1)" }],
    rise: [{ opacity: 0, transform: "translateY(70px)" }, { opacity: 1, transform: "translateY(0)" }],
    drop: [{ opacity: 0, transform: "translateY(-90px)" }, { opacity: 1, transform: "translateY(0)" }],
    left: [{ opacity: 0, transform: "translateX(-140px)" }, { opacity: 1, transform: "translateX(0)" }],
    right: [{ opacity: 0, transform: "translateX(140px)" }, { opacity: 1, transform: "translateX(0)" }],
    zoom: [{ opacity: 0, transform: "scale(1.35)" }, { opacity: 1, transform: "scale(1)" }],
    blur: [{ opacity: 0, filter: "blur(24px)", transform: "scale(1.06)" }, { opacity: 1, filter: "blur(0)", transform: "scale(1)" }],
    wipe: [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)" }],
    wipeUp: [{ clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0% 0 0 0)" }],
    stamp: [{ opacity: 0, transform: "scale(2.4) rotate(-14deg)" }, { opacity: 1, transform: "scale(1) rotate(-8deg)" }],
    flip: [{ opacity: 0, transform: "perspective(900px) rotateX(-70deg)" }, { opacity: 1, transform: "perspective(900px) rotateX(0)" }],
  };
  const DEFAULT_EASE = { pop: "back", stamp: "snap", drop: "back", zoom: "expo", blur: "out", wipe: "inOut", wipeUp: "inOut" };

  const GFX = {
    params: cfg.params || {},
    duration: cfg.duration || 3000,
    fps: cfg.fps || 30,
    kind: cfg.kind || "overlay",
    face: cfg.face || null,             // {x, y, w, h} of the speaker's face in 1080x1920 space, if known
    ease: E,
    clamp,

    $: (sel, root = document) => root.querySelector(sel),
    $$: (sel, root = document) => [...root.querySelectorAll(sel)],
    /** Build an element: GFX.h("div", {class: "card", style: "left:10px"}, child, "text"). */
    h(tag, attrs = {}, ...kids) {
      const el = tag.startsWith("svg:") ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
      for (const [k, v] of Object.entries(attrs || {})) {
        if (v === false || v == null) continue;
        if (k === "html") el.innerHTML = v; else if (k === "text") el.textContent = v; else el.setAttribute(k, v);
      }
      for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
      return el;
    },
    /** Escape text for innerHTML. */
    esc: (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]),
    /** Deterministic pseudo-random generator: const r = GFX.rand(7); r() -> [0, 1). */
    rand(seed = 1) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); },

    EASE: CSS_EASE,
    /** Run fn once fonts are loaded (measure text there, not at script time). Animations are switched off
     *  while layouts run, so measurements ignore entrance transforms. */
    layout(fn) { layouts.push(fn); },
    /** Largest font-size (max..min) at which the element fits `width` (default: its parent's width), `height`
     *  and at most `lines` lines. Runs after fonts load. */
    fit(el, { width, height = Infinity, max = 400, min = 16, lines } = {}) {
      layouts.push(() => {
        const w = width ?? el.parentElement.clientWidth;
        const keep = [el.style.width, el.style.maxWidth];
        el.style.maxWidth = "none";
        el.style.width = w + "px";
        // decorations positioned on top of the text (strikes, rings, badges) must not count as overflow
        const decor = [...el.querySelectorAll("*")].filter((d) => ["absolute", "fixed"].includes(getComputedStyle(d).position));
        const shown = decor.map((d) => d.style.display);
        decor.forEach((d) => { d.style.display = "none"; });
        const fits = () => {
          if (el.scrollWidth > w + 1 || el.scrollHeight > height + 1) return false;
          if (!lines) return true;
          const cs = getComputedStyle(el), fs = parseFloat(cs.fontSize);
          const lh = parseFloat(cs.lineHeight) || fs * 1.2;
          return el.scrollHeight <= lh * lines + fs * 0.5;
        };
        let lo = min, hi = max;
        for (let k = 0; k < 18; k++) {
          const mid = (lo + hi) / 2;
          el.style.fontSize = mid + "px";
          if (fits()) lo = mid; else hi = mid;
        }
        el.style.fontSize = Math.floor(lo) + "px";
        [el.style.width, el.style.maxWidth] = keep;
        decor.forEach((d, i) => { d.style.display = shown[i]; });
      });
    },
    /** One-line label: shrink to fit (down to min), then cut with "…" if it still does not fit. */
    fitLine(el, { width, max = 60, min = 18 } = {}) {
      el.style.whiteSpace = "nowrap";
      GFX.fit(el, { width, max, min });
      layouts.push(() => {
        const w = width ?? el.parentElement.clientWidth;
        const full = el.textContent;
        if (el.scrollWidth <= w + 1) return;
        let lo = 0, hi = full.length;
        while (lo < hi) {
          const mid = Math.ceil((lo + hi) / 2);
          el.textContent = full.slice(0, mid).trimEnd() + "…";
          if (el.scrollWidth <= w + 1) lo = mid; else hi = mid - 1;
        }
        el.textContent = full.slice(0, lo).trimEnd() + "…";
      });
    },
    /** One element through several stops at set times: GFX.track(el, [{at: 0, transform: "..."}, {at: 400, ...}]). */
    track(el, stops, { ease = "inOut" } = {}) {
      const t0 = stops[0].at, span = Math.max(1, stops[stops.length - 1].at - t0);
      const kf = stops.map(({ at, ease: e, ...css }) => ({ ...css, offset: clamp((at - t0) / span), easing: CSS_EASE[e || ease] || e || ease }));
      return el.animate(kf, { delay: t0, duration: span, fill: "both" });
    },
    /** Draw an SVG stroke from nothing (no dot from round caps before it starts). */
    draw(path, { at = 0, dur = 500, ease = "inOut" } = {}) {
      path.setAttribute("pathLength", "1");
      path.style.strokeDasharray = "1 1.1";
      return GFX.anim(path, [{ strokeDashoffset: 1.04 }, { strokeDashoffset: 0 }], { at, dur, ease })[0];
    },
    /** Sound cue at `at` ms (overrides the meta.json cues when a template emits any). */
    sfx(name, at = 0, gain_db = -14) { cues.push({ at: at / 1000, name, gain_db }); },
    /** Web Animation on one or many elements, starting `at` ms into the scene. Returns the animations. */
    anim(el, keyframes, { at = 0, dur = 500, ease = "out", fill = "both", iterations = 1, direction = "normal" } = {}) {
      return list(el).filter(Boolean).map((t) => t.animate(keyframes, {
        delay: at, duration: dur, easing: CSS_EASE[ease] || ease, fill, iterations, direction,
      }));
    },
    /** Entrance: GFX.in(el, "pop", {at: 200}). Many elements + stagger (ms) animate one after another. */
    in(el, how = "rise", { at = 0, dur = 520, ease, stagger = 0 } = {}) {
      const kf = PRESETS[how] || PRESETS.rise;
      list(el).filter(Boolean).forEach((t, i) => GFX.anim(t, kf, { at: at + i * stagger, dur, ease: ease || DEFAULT_EASE[how] || "out" }));
      return at + (list(el).length - 1) * stagger + dur;
    },
    /** Exit: plays the preset backwards. Defaults to the last 260 ms of the scene. */
    out(el, how = "fade", { at, dur = 240, ease = "in", stagger = 0 } = {}) {
      const kf = [...(PRESETS[how] || PRESETS.fade)].reverse();
      const start = at ?? GFX.duration - dur - 20;
      list(el).filter(Boolean).forEach((t, i) => GFX.anim(t, kf, { at: start + i * stagger, dur, ease, fill: "forwards" }));
    },
    /** Per-frame callback fn(t). [from, to] is when it can change the picture (lets still frames be reused). */
    each(fn, from = 0, to = Infinity) { hooks.push({ fn, from, to }); },
    /** Eased value from `from` to `to` over [at, at+dur]: fn(value). */
    tween(fn, { at = 0, dur = 1000, ease = "out", from = 0, to = 1 } = {}) {
      const f = E[ease] || E.out;
      GFX.each((t) => fn(from + (to - from) * f(clamp((t - at) / dur))), at, at + dur);
      return at + dur;
    },
    /** Count-up number in an element: GFX.count(el, 0.4, 11.8, {decimals: 1, suffix: "%"}). */
    count(el, from, to, { at = 0, dur = 1200, ease = "out", decimals = 0, prefix = "", suffix = "", group = true } = {}) {
      const fmt = (v) => prefix + (group
        ? v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
        : v.toFixed(decimals)) + suffix;
      return GFX.tween((v) => { el.textContent = fmt(v); }, { at, dur, ease, from, to });
    },
    /** Compact number formatter: 48213 -> "48.2K". */
    compact(v) {
      const a = Math.abs(v);
      if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
      if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "K";
      return String(Math.round(v));
    },
    /** Typewriter into an element. Returns the time the typing ends. */
    type(el, text, { at = 0, cps = 30, caret = false } = {}) {
      const s = String(text);
      const dur = (s.length / cps) * 1000;
      GFX.each((t) => {
        const n = Math.round(clamp((t - at) / dur) * s.length);
        el.textContent = s.slice(0, n) + (caret && t >= at && n < s.length ? "|" : "");
      }, at, at + dur);
      return at + dur;
    },
    /** Bind an <img> to the speaker's frames (only for kind "speaker"). */
    speaker(img, { offset = 0 } = {}) {
      const frames = (cfg.speaker && cfg.speaker.frames) || [];
      if (!frames.length) { img.style.visibility = "hidden"; return; }
      img.decoding = "sync";
      GFX.each((t) => {
        const i = clamp(Math.floor((t * GFX.fps) / 1000 + 1e-6) + offset, 0, frames.length - 1);
        if (img.dataset.i !== String(i)) {
          img.dataset.i = String(i);
          img.src = frames[i];
          decodes.push(img.decode().catch(() => {}));
        }
      }, 0, Infinity);
    },
    /** Show one speaker frame and hold it (a freeze frame): `at` is ms from the scene start. */
    still(img, { at = 0 } = {}) {
      const frames = (cfg.speaker && cfg.speaker.frames) || [];
      if (!frames.length) { img.style.visibility = "hidden"; return; }
      img.decoding = "sync";
      img.src = frames[clamp(Math.floor((at * GFX.fps) / 1000 + 1e-6), 0, frames.length - 1)];
      decodes.push(img.decode().catch(() => {}));
    },
    hasSpeaker: !!(cfg.speaker && cfg.speaker.frames && cfg.speaker.frames.length),
    /** A face window (picture-in-picture) of the live speaker: a rounded portrait box framed on head and
     *  shoulders (the face fills ~46% of its width), so little of him is cropped; returns the box. */
    pip({ x = 726, y = 272, w = 290, h = 340, at = 0, parent = document.body } = {}) {
      const img = GFX.h("img", { alt: "" });
      const pip = GFX.h("div", { class: "pip", style: `left:${x}px;top:${y}px;width:${w}px;height:${h}px` }, img);
      parent.append(pip);
      if (!GFX.hasSpeaker) { pip.style.display = "none"; return pip; }
      GFX.speaker(img);
      const f = GFX.face || { x: 340, y: 520, w: 400, h: 460 };
      const iw = Math.max(w, (h * 1080) / 1920, (w * 0.46) / (f.w / 1080)), ih = (iw * 1920) / 1080;
      const fx = ((f.x + f.w / 2) / 1080) * iw, fy = ((f.y + f.h * 0.5) / 1920) * ih;
      img.style.cssText = `position:absolute;width:${iw}px;height:${ih}px;max-width:none;` +
        `left:${clamp(w / 2 - fx, w - iw, 0)}px;top:${clamp(h * 0.44 - fy, h - ih, 0)}px`;
      GFX.in(pip, "pop", { at, dur: 420, ease: "back" });
      return pip;
    },

    /** Move a pointer cursor through points [{x, y, at}] and click at the ones with click: true. */
    cursor(points, { parent = document.body } = {}) {
      const c = GFX.h("div", { class: "cursor", html: GFX.icon("pointer", { size: 54, fill: "#111", stroke: "#fff", width: 1.6 }) });
      parent.append(c);
      const t0 = points[0].at ?? 0, t1 = points[points.length - 1].at ?? t0 + 1000;
      const span = Math.max(1, t1 - t0);
      const kf = points.map((p, i) => ({
        transform: `translate(${p.x}px, ${p.y}px)`,
        offset: points.length === 1 ? 1 : clamp(((p.at ?? t0 + (i * span) / (points.length - 1)) - t0) / span),
        easing: CSS_EASE.inOut,
      }));
      c.animate(kf, { delay: t0, duration: span, fill: "both" });
      GFX.in(c, "fade", { at: Math.max(0, t0 - 150), dur: 150 });
      for (const p of points.filter((p) => p.click)) {
        const r = GFX.h("div", { class: "ripple", style: `left:${p.x + 8}px;top:${p.y + 8}px` });
        parent.append(r);
        GFX.anim(r, [{ opacity: 0, transform: "scale(.2)" }, { opacity: 0.9, transform: "scale(.3)", offset: 0.08 },
          { opacity: 0, transform: "scale(1.3)" }], { at: p.at, dur: 440, ease: "out" });
        const arrow = c.firstElementChild;
        arrow.style.transformOrigin = "10px 6px";
        GFX.anim(arrow, [{ transform: "scale(1)" }, { transform: "scale(.82)" }, { transform: "scale(1)" }],
          { at: p.at - 40, dur: 200, ease: "inOut", fill: "none" });
      }
      return c;
    },

    /** Inline SVG icon markup. GFX.icon("check", {size: 40, stroke: "#fff"}). */
    icon(name, { size = 40, stroke = "currentColor", fill = "none", width = 2.4 } = {}) {
      const d = ICONS[name] || ICONS.dot;
      const filled = FILLED.has(name);
      return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${filled ? (fill === "none" ? stroke : fill) : fill}" ` +
        `stroke="${filled && fill !== "none" ? stroke : filled ? "none" : stroke}" stroke-width="${width}" stroke-linecap="round" ` +
        `stroke-linejoin="round">${d}</svg>`;
    },
  };

  const FILLED = new Set(["play", "star", "heart", "pointer", "bolt", "dot", "rec"]);
  const ICONS = {
    check: '<path d="M4.5 12.5l5 5 10-11"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    arrowRight: '<path d="M4 12h15M13 6l6 6-6 6"/>',
    arrowUp: '<path d="M12 20V5M6 11l6-6 6 6"/>',
    arrowDown: '<path d="M12 4v15M6 13l6 6 6-6"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>',
    play: '<path d="M8 5.5v13l11-6.5z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    heart: '<path d="M12 20s-7.5-4.6-9.3-9.2C1.5 7.4 3.7 4.5 7 4.5c2 0 3.4 1.1 5 3 1.6-1.9 3-3 5-3 3.3 0 5.5 2.9 4.3 6.3C19.5 15.4 12 20 12 20z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.3c2.2.7 3.5 2.8 3.5 5.7"/>',
    chat: '<path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z"/>',
    send: '<path d="M21 3L10 14M21 3l-7 18-4-7-7-4z"/>',
    bell: '<path d="M6 9a6 6 0 1 1 12 0c0 5 2 6.5 2 6.5H4S6 14 6 9zM10 19a2 2 0 0 0 4 0"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
    bolt: '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
    fire: '<path d="M12 22c4 0 7-2.7 7-6.8 0-3.9-2.7-6-4-9.2-1.3 2.4-2.6 3.3-4 3.6C11 6.6 9.8 4.4 8 2c-.3 4.2-3 6.7-3 11.7C5 18.8 8 22 12 22z"/>',
    trendUp: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    trendDown: '<path d="M3 7l6 6 4-4 8 8M15 17h6v-6"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    camera: '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    thumbUp: '<path d="M7 11v10H4V11zM7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5.5a2 2 0 0 1 2 2.3l-1.2 7.4A2 2 0 0 1 17.8 20H7"/>',
    share: '<path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M12 3v12M7 8l5-5 5 5"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    home: '<path d="M3 11l9-8 9 8M5 9.5V20h14V9.5"/>',
    sparkle: '<path d="M12 3l1.8 5.4L19 10l-5.2 1.6L12 17l-1.8-5.4L5 10l5.2-1.6zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    dollar: '<path d="M12 2v20M17 6.5C16 5 14.3 4.5 12 4.5c-3 0-5 1.4-5 3.6 0 5 10 2.6 10 7.8 0 2.2-2 3.6-5 3.6-2.5 0-4.3-.8-5.3-2.5"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    battery: '<rect x="2" y="7" width="18" height="10" rx="2"/><path d="M22 11v2M5 10h9v4H5z"/>',
    wifi: '<path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01"/>',
    pointer: '<path d="M5 3l14 8.5-6.2 1.3L16.5 20l-2.8 1.3-3.6-7.3L5 18.2z"/>',
    rec: '<circle cx="12" cy="12" r="7"/>',
    dot: '<circle cx="12" cy="12" r="4"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/>',
    scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.5 7.5L20 18M8.5 16.5L20 6"/>',
    wand: '<path d="M4 20L16 8M14 4v3M17 7h3M18.5 3.5l-2 2M11 5.5h2"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
    trophy: '<path d="M7 4h10v5a5 5 0 0 1-10 0zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v4M8 21h8M9 18h6"/>',
    alert: '<path d="M12 3l10 18H2zM12 10v5M12 18h.01"/>',
  };

  window.GFX = GFX;

  /** Called by the renderer before the first frame. */
  window.__ready = async () => {
    await Promise.all([...document.fonts].map((f) => f.load().catch(() => {})));
    await document.fonts.ready;
    const all = document.getAnimations();
    for (const a of all) a.cancel();          // measure the settled layout, not entrance transforms
    for (const fn of layouts) fn();
    for (const a of all) a.pause();           // revive them; __seek sets the real time
    await window.__seek(0);
    return true;
  };
  /** What the template reports back to the renderer after __ready (sound cues). */
  window.__out = () => ({ cues });
  /** Draw the scene at time t (ms). */
  window.__seek = async (t) => {
    for (const a of document.getAnimations()) { a.pause(); a.currentTime = t; }
    for (const h of hooks) h.fn(t);
    if (decodes.length) await Promise.all(decodes.splice(0));
  };
  /** Quality check: visible text that is clipped or runs off the frame (elements with data-bleed are exempt). */
  window.__overflow = () => {
    const out = [];
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest("[data-bleed]")) continue;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      let o = 1;
      for (let p = el; p && p !== document.body; p = p.parentElement) o *= Number(getComputedStyle(p).opacity);
      if (o < 0.05) continue;
      const r = el.getBoundingClientRect();
      const clipped = (el.scrollWidth > el.clientWidth + 2 && cs.overflowX !== "visible")
        || (el.scrollHeight > el.clientHeight + 2 && cs.overflowY !== "visible");
      const off = r.left < -2 || r.right > 1082 || r.top < -2 || r.bottom > 1922;
      if (clipped || off) out.push({ text: el.textContent.trim().slice(0, 48), clipped, off,
        rect: [r.left, r.top, r.right, r.bottom].map(Math.round) });
    }
    return out;
  };
  /** Could anything on screen change between t0 and t1? False means the frame at t1 equals the frame at t0. */
  window.__changes = (t0, t1) => {
    for (const a of document.getAnimations()) {
      const tm = a.effect.getTiming();
      const iters = tm.iterations ?? 1;
      if (iters === Infinity) return true;
      const start = tm.delay || 0, end = start + (Number(tm.duration) || 0) * iters;
      if (end > t0 && start < t1) return true;
    }
    for (const h of hooks) if (h.to > t0 && h.from < t1) return true;
    return false;
  };
})();
