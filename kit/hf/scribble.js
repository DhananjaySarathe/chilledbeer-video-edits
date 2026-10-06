/* kit/hf/scribble.js — a hand-drawn outline that follows the speaker (the rotoscope look). The outlines are built
 * offline by kit/hf/tools/scribble.py (person matte -> expand -> contour -> smooth -> seeded jitter per 12 fps step);
 * this module only picks the prebuilt path for floor(t * 12) and draws it on (needs core.js; DrawSVG if vendored).
 *
 *   // build.py: inline the JSON into the page (const S = {...}), like the edit data
 *   const sc = HF.scribble(K, panel, S, { at: 13.45, box: [x, y, w, h], from: 13.7, until: 17.4 });
 *   // at: the composition time of the clip's first frame (its data-start, minus data-media-start - S.start)
 *   // box: where the clip's full source frame (S.width x S.height) is drawn in `panel` (same box as the <video>)
 *   // options: color (accent; use "#fff" on dark or busy footage), width (px on screen, 7), draw: 0.7 (draw-on seconds),
 *   //          erase: 0.35 (draw-off before until; 0 = cut), halo: true (a soft paper-white under-stroke), zoom (extra CSS scale of panel)
 *
 * Exact: every step's path is prebuilt from the JSON once (Catmull-Rom -> cubic); a K.onFrame sets the `d` of step
 * floor((t - at) * fps) and the visible fraction (DrawSVG 0% -> p) as pure functions of t.
 */
(function (root) {
  const HF = root.HF;
  if (!HF || !HF.kit) throw new Error("kit/hf/scribble.js needs core.js first");
  const C = HF.C, NS = "http://www.w3.org/2000/svg";

  // flat [x0, y0, x1, y1, ...] -> a smooth open (or closed) cubic path
  const smooth = (f, closed) => {
    const P = []; for (let i = 0; i + 1 < f.length; i += 2) P.push([f[i], f[i + 1]]);
    if (P.length < 2) return "";
    const at = (i) => (closed ? P[(i + P.length) % P.length] : P[Math.max(0, Math.min(P.length - 1, i))]);
    let d = `M${P[0][0]} ${P[0][1]}`;
    const n = closed ? P.length : P.length - 1;
    for (let i = 0; i < n; i++) {
      const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2);
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0]} ${p2[1]}`;
    }
    return closed ? d + " Z" : d;
  };
  const set = (p, a, b) => {                                                 // visible from a to b (fractions of the length)
    if (root.DrawSVGPlugin) { gsap.registerPlugin(root.DrawSVGPlugin); gsap.set(p, { drawSVG: `${(a * 100).toFixed(3)}% ${(b * 100).toFixed(3)}%` }); return; }
    const L = p.getTotalLength();
    p.style.strokeDasharray = `0 ${(a * L).toFixed(2)} ${((b - a) * L).toFixed(2)} ${L + 1}`; p.style.strokeDashoffset = "0";
  };
  const ease = (x) => 1 - Math.pow(1 - x, 2.2);

  HF.scribble = function (K, parent, S, o = {}) {
    if (!S || !S.steps || !S.steps.length) throw new Error("HF.scribble: no outline data (run kit/hf/tools/scribble.py and inline its JSON)");
    const [bx, by, bw, bh] = o.box || [0, 0, S.width, S.height];
    const u = S.width / bw / (o.zoom || 1);                                  // source units per screen px
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${S.width} ${S.height}`); svg.setAttribute("preserveAspectRatio", "none");
    svg.style.cssText = `position:absolute;left:${bx}px;top:${by}px;width:${bw}px;height:${bh}px;overflow:visible;pointer-events:none;z-index:${o.z || 3}`;
    parent.append(svg);
    const col = o.color || C.acc, wpx = o.width || 7, passes = Math.min(S.passes || 1, o.passes || 9);
    // prebuilt geometry: steps[k][pass] = d
    const D = S.steps.map((st) => st.slice(0, passes).map((runs) => runs.map((r) => smooth(r, S.closed)).join(" ")));
    const mk = (stroke, w, op) => { const p = document.createElementNS(NS, "path"); p.setAttribute("fill", "none"); p.setAttribute("stroke", stroke); p.setAttribute("stroke-width", (w * u).toFixed(2));
      p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); if (op != null) p.setAttribute("opacity", op); svg.append(p); return p; };
    const lines = [];
    for (let k = 0; k < passes; k++) {
      const w = k ? wpx * 0.55 : wpx;
      const halo = o.halo !== false ? mk(o.haloColor || "rgba(255,253,248,.85)", w + 5, k ? 0.5 : 0.8) : null;
      lines.push({ halo, ink: mk(col, w, k ? 0.8 : 1), lag: k * 0.18 });
    }
    const at = o.at || 0, from = o.from != null ? o.from : at, until = o.until != null ? o.until : at + S.steps.length / S.fps;
    const dd = o.draw != null ? o.draw : 0.7, er = o.erase != null ? o.erase : 0.35;
    let lastK = -1, lastVis = null;
    K.onFrame((t) => {
      const vis = t >= from && t < until;
      if (vis !== lastVis) { svg.style.visibility = vis ? "visible" : "hidden"; lastVis = vis; }
      if (!vis) return;
      const k = Math.max(0, Math.min(S.steps.length - 1, Math.floor((t - at) * S.fps + 1e-6)));
      const ts = Math.floor(t * S.fps + 1e-6) / S.fps;                         // the pen also moves on the 12 fps grid
      lines.forEach((L, i) => {
        if (k !== lastK) { L.ink.setAttribute("d", D[k][i]); if (L.halo) L.halo.setAttribute("d", D[k][i]); }
        const p = dd > 0 ? ease(Math.max(0, Math.min(1, (ts - from - L.lag) / dd))) : 1;
        const q = er > 0 ? Math.max(0, Math.min(1, (ts - (until - er)) / er)) : 0;
        [L.halo, L.ink].forEach((e) => e && set(e, q, Math.max(q, p)));
      });
      lastK = k;
    });
    return { svg, lines, steps: S.steps.length };
  };
})(typeof window !== "undefined" ? window : globalThis);
