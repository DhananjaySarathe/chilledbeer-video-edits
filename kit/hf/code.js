/* kit/hf/code.js — code and terminal walkthroughs (needs core.js).
 *
 *   const cw = HF.code(K, layer, { x, y, w, h, title: "src/edit.js", lang: "js", lines: [...], theme: "light" });
 *   cw.show(t) | cw.typeIn(t, cps)        // appear all at once (staggered) or type line by line
 *   cw.highlight(t, [from, to], { until, note: "this line picks the scene" })   // 1-based line numbers
 *   cw.focus(t, [from, to], until)        // dim the rest
 *   cw.add(t, afterLine, ["new line", ...])     // diff: green "+" lines slide in, the rest moves down
 *   cw.remove(t, [from, to])              // diff: red "-" lines strike, then collapse
 *   cw.scrollTo(t, line)
 *   const term = HF.terminal(K, layer, { x, y, w, h, title: "zsh" });
 *   let e = term.cmd(t, "npx hyperframes render", 22); term.spinner(e, e + 2, "Rendering", "Rendered 174 s"); term.out(e + 2.2, ["✓ PASS"], "ok")
 *
 * Calls on one window must be made in time order (each edit moves the lines below it). Line positions are transforms
 * only; the spinner is a pure function of time (K.onFrame).
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/code.js needs core.js first");
  const C = HF.C;
  const KW = {
    js: "const let var function return if else for while do switch case break continue new class extends import from export default async await try catch finally throw of in typeof instanceof this null undefined true false yield",
    py: "def return if elif else for while in not and or import from as class try except finally raise with lambda pass None True False yield async await global",
    sh: "cd ls cp mv rm mkdir echo export sudo npm npx node python3 uv git ffmpeg brew curl cat grep sed",
    json: "true false null",
  };
  // a small, safe highlighter: comments, strings, numbers, keywords, function names, punctuation
  HF.highlight = (line, lang = "js") => {
    const kw = new Set((KW[lang] || KW.js).split(" "));
    const re = /(\/\/.*$|#.*$|\/\*.*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)(?=\s*\()|([A-Za-z_$][\w$-]*)|([{}()[\];,.=<>+\-*/:!?&|])/g;
    let out = "", last = 0, m;
    while ((m = re.exec(line))) {
      out += HF.esc(line.slice(last, m.index));
      const [tok, cm, st, nu, fn, id, pu] = m;
      if (cm && (lang !== "sh" || cm[0] === "#") && !(lang === "js" && cm[0] === "#")) out += `<span class="t-c">${HF.esc(cm)}</span>`;
      else if (cm) out += HF.esc(cm);
      else if (st) out += `<span class="t-s">${HF.esc(st)}</span>`;
      else if (nu) out += `<span class="t-n">${nu}</span>`;
      else if (fn) out += kw.has(fn) ? `<span class="t-k">${fn}</span>` : `<span class="t-f">${fn}</span>`;
      else if (id) out += kw.has(id) ? `<span class="t-k">${id}</span>` : HF.esc(id);
      else if (pu) out += `<span class="t-p">${HF.esc(pu)}</span>`;
      else out += HF.esc(tok);
      last = m.index + tok.length;
    }
    return out + HF.esc(line.slice(last));
  };

  HF.code = function (K, parent, o) {
    const tl = K.tl, Q = K.Q, LH = o.lineH || Math.round((o.size || 26) * 1.62), dark = o.theme === "dark";
    const win = HF.win(K, parent, o.x, o.y, o.w, o.h, o.title || "", null, { dark });
    const view = win.view, vh = o.h - 46, top = o.padTop || 22;
    const body = K.el(view, `left:0;top:0;width:100%;height:100%`);
    body.className = "hf-abs hf-code" + (dark ? " dark" : "");
    body.style.fontSize = (o.size || 26) + "px";                          // 26 px minimum: phones
    const band = K.el(body, `left:0;top:0;width:100%;height:${LH}px;background:${dark ? "rgba(226,86,43,.22)" : "rgba(226,86,43,.12)"};border-left:5px solid ${C.acc};opacity:0`);
    const rows = [];                                                         // current order of line elements
    const mk = (text, n) => {
      const r = K.el(body, `left:0;top:0;height:${LH}px;opacity:0`, `<span class="no">${n != null ? n : ""}</span><span class="gut"></span><span class="tx">${HF.highlight(text, o.lang)}</span>`, "ln");
      r.style.position = "absolute"; r.style.width = "100%";
      return r;
    };
    (o.lines || []).forEach((l, i) => rows.push(mk(l, i + 1)));
    const yOf = (i) => top + i * LH;
    rows.forEach((r, i) => tl.set(r, { y: yOf(i) }, 0));
    let scrollY = 0;
    const cw = { win, rows };
    cw.show = (t, stagger = 0.04) => { K.enter(win, t - 0.1, { y: 40 }); rows.forEach((r, i) => tl.to(r, { opacity: 1, duration: 0.2 }, Q(t + 0.2 + i * stagger))); return cw; };
    cw.typeIn = (t, cps = 60) => {
      K.enter(win, t - 0.1, { y: 40 });
      let tt = t + 0.3;
      rows.forEach((r) => { const tx = r.querySelector(".tx"), html = tx.innerHTML, n = tx.textContent.length;
        tl.set(r, { opacity: 1 }, Q(tt));
        const o2 = { k: 0 };                                                   // reveal by a clip on the text span (keeps highlighting)
        tl.fromTo(tx, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: Math.max(0.05, n / cps), ease: "none" }, Q(tt));
        tt += Math.max(0.05, n / cps) + 0.04; });
      K.sfx("type", t + 0.3);
      return tt;
    };
    const lineIndex = (n) => n - 1;
    cw.highlight = (t, [a, b], opt = {}) => {
      const i0 = lineIndex(a), i1 = lineIndex(b == null ? a : b);
      tl.set(band, { y: yOf(i0) - 0, height: (i1 - i0 + 1) * LH }, Q(t));
      tl.fromTo(band, { opacity: 0, scaleX: 0.96 }, { opacity: 1, scaleX: 1, duration: 0.3, ease: "power3.out", transformOrigin: "0 50%" }, Q(t));
      if (opt.until != null) tl.to(band, { opacity: 0, duration: 0.3 }, Q(opt.until));
      if (opt.note) {
        // wide windows: beside the line; narrow ones (9:16): a footer in the window, linked by colour, never over the code
        const foot = opt.notePos ? opt.notePos === "footer" : o.w < 1200;
        const pos = foot ? `left:24px;bottom:22px` : `left:${o.w - (opt.noteW || 380)}px;top:${yOf(i0) - scrollY}px`;
        const nt = K.el(view, `${pos};opacity:0;z-index:3`, `<span class="hf-pill" style="position:relative;font-size:${foot ? 28 : 22}px;padding:10px 18px;background:${C.acc};color:#fff">${HF.esc(opt.note)}</span>`);
        K.enter(nt, t + 0.15, { x: 20, y: 0 }); if (opt.until != null) K.exit(nt, opt.until);
      }
      K.sfx("click", t);
      return cw;
    };
    cw.focus = (t, [a, b], until) => {
      rows.forEach((r, i) => { const inside = i >= lineIndex(a) && i <= lineIndex(b == null ? a : b); tl.to(r, { opacity: inside ? 1 : 0.28, duration: 0.3 }, Q(t)); if (until != null) tl.to(r, { opacity: 1, duration: 0.3 }, Q(until)); });
      return cw;
    };
    cw.add = (t, after, lines, opt = {}) => {
      const at = after;                                                      // insert after this line (0 = top)
      const fresh = lines.map((l) => mk(l, ""));
      fresh.forEach((r) => { r.style.background = dark ? "rgba(143,209,158,.14)" : C.okTint; r.querySelector(".gut").textContent = "+"; r.querySelector(".gut").style.color = C.ok; });
      rows.slice(at).forEach((r, k) => tl.to(r, { y: yOf(at + lines.length + k), duration: 0.45, ease: "power3.inOut" }, Q(t)));
      fresh.forEach((r, k) => { tl.set(r, { y: yOf(at + k), x: -24 }, 0); tl.to(r, { opacity: 1, x: 0, duration: 0.4, ease: "power3.out" }, Q(t + 0.25 + k * 0.08)); });
      rows.splice(at, 0, ...fresh);
      rows.forEach((r, i) => { const no = r.querySelector(".no"); tl.set(no, { textContent: String(i + 1) }, Q(t + 0.3)); });
      if (opt.settle != null) fresh.forEach((r) => tl.to(r, { backgroundColor: "rgba(0,0,0,0)", duration: 0.6 }, Q(opt.settle)));
      K.sfx("pop", t + 0.25);
      return cw;
    };
    cw.remove = (t, [a, b]) => {
      const i0 = lineIndex(a), n = lineIndex(b == null ? a : b) - i0 + 1, gone = rows.slice(i0, i0 + n);
      gone.forEach((r) => { tl.to(r, { backgroundColor: dark ? "rgba(255,138,122,.16)" : C.badTint, duration: 0.2 }, Q(t)); tl.set(r.querySelector(".gut"), { textContent: "−", color: C.bad }, Q(t));
        tl.to(r.querySelector(".tx"), { opacity: 0.45, textDecoration: "line-through", duration: 0.2 }, Q(t + 0.1)); tl.to(r, { opacity: 0, x: 24, duration: 0.35, ease: "power2.in" }, Q(t + 0.9)); });
      rows.splice(i0, n);
      rows.slice(i0).forEach((r, k) => tl.to(r, { y: yOf(i0 + k), duration: 0.45, ease: "power3.inOut" }, Q(t + 1.05)));
      rows.forEach((r, i) => tl.set(r.querySelector(".no"), { textContent: String(i + 1) }, Q(t + 1.1)));
      K.sfx("click", t);
      return cw;
    };
    cw.scrollTo = (t, line, dur = 0.7) => {
      scrollY = Math.max(0, yOf(lineIndex(line)) - vh * 0.3);
      tl.to(body, { y: -scrollY, duration: dur, ease: "power2.inOut" }, Q(t));
      return cw;
    };
    return cw;
  };

  HF.terminal = function (K, parent, o) {
    const tl = K.tl, Q = K.Q, LH = o.lineH || Math.round((o.size || 28) * 1.6);
    const win = HF.win(K, parent, o.x, o.y, o.w, o.h, o.title || "zsh", null, { dark: true });
    const view = win.view, vh = o.h - 46, cap = Math.floor((vh - 30) / LH);
    const body = K.el(view, `left:0;top:0;width:100%;height:100%`);
    body.className = "hf-abs hf-term"; body.style.fontSize = (o.size || 28) + "px";
    let n = 0;
    const lines = [];
    const place = (t) => { const over = Math.max(0, n - cap); tl.to(body, { y: -over * LH, duration: 0.25, ease: "power2.out" }, Q(t)); };
    const line = (t, html) => {
      const l = K.el(body, `left:28px;top:${20 + n * LH}px;height:${LH}px;right:28px;opacity:0;white-space:pre`, html);
      n++; lines.push(l); place(t);
      return l;
    };
    const term = { win };
    term.show = (t) => { K.enter(win, t, { y: 40 }); return term; };
    term.cmd = (t, text, cps = 24) => {
      const l = line(t, `<span class="pr">${HF.esc(o.prompt || "$")}</span> <span class="c"></span>`);
      tl.set(l, { opacity: 1 }, Q(t));
      const end = K.typeText(l.querySelector(".c"), text, t + 0.15, cps);
      K.sfx("type", t + 0.15, -24);
      return end + 0.15;
    };
    term.out = (t, rows, tone = "", stagger = 0.07) => {
      rows.forEach((r, k) => { const l = line(t + k * stagger, `<span class="${tone === "ok" ? "ok" : tone === "err" ? "err" : tone === "mute" ? "mu" : ""}">${HF.esc(r)}</span>`); tl.to(l, { opacity: 1, duration: 0.15 }, Q(t + k * stagger)); });
      return t + rows.length * stagger;
    };
    const FR = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
    term.spinner = (t0, t1, label, done) => {
      const l = line(t0, `<span class="sp" style="color:${C.acc}"></span> <span class="lb"></span>`);
      tl.set(l, { opacity: 1 }, Q(t0));
      const sp = l.querySelector(".sp"), lb = l.querySelector(".lb");
      K.onFrame((t) => {
        if (t < t0) { sp.textContent = ""; lb.textContent = ""; return; }
        if (t < t1) { sp.textContent = FR[Math.floor((t - t0) * 12) % FR.length]; sp.style.color = C.acc; lb.textContent = label + "…"; lb.className = "lb"; }
        else { sp.textContent = "✓"; sp.style.color = "#8fd19e"; lb.textContent = done || label; lb.className = "lb ok"; }
      });
      K.sfx("check", t1, -22);
      return t1;
    };
    return term;
  };
})(typeof window !== "undefined" ? window : globalThis);
