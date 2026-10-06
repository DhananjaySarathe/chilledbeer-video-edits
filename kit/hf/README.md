# kit/hf — reusable scene components for HyperFrames films

The long-form building blocks behind `preset_paper_studio`, extracted from `films/how-i-edit` so that a new film is a
**plan plus scene calls**, not 700 lines of hand-written HTML. Everything is free, local, deterministic and seekable.

**Showcase** (every component in one 73 s film): `showcase/showcase.mp4`, with source in `showcase/src/template.html`.
**Previews**: `previews/*.jpg`. **Registry**: `registry.json`. **How to choose scenes**: `kit/refs/SCENES.md`.

| | |
|---|---|
| ![](previews/diagram_focus.jpg) living diagram | ![](previews/screen.jpg) annotated screen demo |
| ![](previews/code_diff.jpg) code walkthrough (diff) | ![](previews/terminal.jpg) terminal |
| ![](previews/compare.jpg) before / after | ![](previews/chat.jpg) chat explainer |

## What's in the kit

| File | What it gives you |
|---|---|
| `paper.css` | the paper-studio tokens and component styles (inlined into the page) |
| `core.js` | `HF.kit()`: frame-quantised motion (`enter`, `exit`, `fade`, `drift`, `words` + `rise`, `typeText`, `countUp`), icons, named SFX cues, `K.onFrame()` for time-pure state, `K.finish()` |
| `scenes.js` | `HF.stage` (the layer stack), `HF.camera` (speaker framing: W/M/C/SR/SL/PIP/OFF, or `mode: "panel"` for 9:16), `side`, `insert`, `card`, `pill`, `win` + `scroll`, `phone`, `lowerThird`, `chapter`, `compare`, `chat`, `endCard` |
| `diagram.js` | **the living diagram**: `reveal`, `connect`, `focus` (camera zoom with the rest dimmed), `overview`, `flow` (dots travel an edge), `done`, `note`, `highlight`. Its state carries across `show()` windows, so it develops over the video and returns for the recap |
| `screen.js` | **annotated screen demos** on a real recording or screenshot: `zoom`, `pan`, `reset`, `highlight` (spotlight + label), `arrow` (drawn on), `cursor` (eased path + click ripples), `callout`, `blur` (privacy). Coordinates are in the recording's own pixels |
| `code.js` | **code walkthroughs**: syntax colouring in the palette, `typeIn`, `highlight` (+ note), `focus`, `add` / `remove` (real diffs that move the lines below), `scrollTo`. Plus a **terminal**: `cmd`, `out`, `spinner` |
| `vendor.py` | puts the kit into a film: copies fonts and gsap, and inlines the CSS and JS at `<!--HF:KIT-->` |
| `plan_check.py` | validates `visual_plan.json` (types, techniques, fallbacks, ratios, timing, stickman budget, assets); `--key` prints a cache key |
| `registry.json` | every component: version, what it explains, inputs, timing limits, ratios, assets, fallback, preview, rules |
| `tools/locate.py` | **find on-screen text** in a recording ("Render", "Pull requests") → `[x, y, w, h]`, using Apple Vision on-device |
| `tools/grid.py` | a frame with a labelled pixel grid (`--ocr` boxes every text line) for picking coordinates |
| `tools/ocrboxes.swift` | the Vision text recogniser behind `locate.py`; build with `swiftc -O -o kit/bin/ocrboxes kit/hf/tools/ocrboxes.swift` |
| `examples/visual_plan.example.json` | a filled plan (labelled sample: "how an AI video editor reuses assets") |
| `showcase/` | the showcase film (16:9) plus `vertical/` (the 9:16 check) |

The stickman rig (`kit/stickman/stickman.js`) is inlined too. `K.finish()` drives it.

## A film in five steps

1. **Plan**: write `visual_plan.json` from the beat sheet (`kit/refs/SCENES.md`), then `python3 kit/hf/plan_check.py visual_plan.json`.
2. **Template**: start from `showcase/src/template.html`, with `<!--HF:KIT-->` in `<head>`, the A-roll `<video id="aroll" class="clip" …>` in the root, and these two literal lines (the HyperFrames linter looks for them):
   ```js
   const tl = gsap.timeline({ paused: true });
   window.__timelines = window.__timelines || {}; window.__timelines["<composition-id>"] = tl;
   ```
3. **Scenes**: one block per passage:
   ```js
   const K = HF.kit({ tl, id: "<composition-id>", width: 1920, height: 1080, words: D.words, pieces: D.pieces });
   const st = HF.stage(K, document.getElementById("root"), { aroll: "aroll" });
   HF.camera(K, st, { framing: { intro: "W", hook: "SR", demo: "PIP", ... } });
   HF.lowerThird(K, st.top, { name: "Your Name", line: "Building with Claude Code, every weekend", t: 0.3 });
   const I = HF.insert(K, st, a, b);
   const sd = HF.screen(K, I, { x: 110, y: 110, w: 1360, h: 860, src: "assets/rec.mp4", start: a, dur: b - a, srcW: 1920, srcH: 1080 }).show(a);
   sd.zoom(K.W(212), [1260, 190, 620, 250]).highlight(K.W(214), [1288, 236, 268, 60], { label: "What it is", until: K.W(230) });
   ...
   K.finish(D.total);
   ```
   Time everything to words with `K.W(i)` (word start) or `K.span(tag)`.
4. **Build**: in `build.py`, `F = Film(__file__)` (`kit/paths.py`), then `F.stage()`, `vendor.copy_assets(F.hf)`, `html = vendor.inline(html)` and write `F.hf / "index.html"`. The HyperFrames project lives in `output/temp/films/<name>/hf`, so `films/<name>/` keeps only the recipe. Then `npx hyperframes lint <F.hf>`.
5. **Render and gate**: `npx hyperframes render <F.hf> -o <F.renders>/raw.mp4 --quality delivery`, mux with `-aac_pns 0` (see gotchas) into `F.final`, then `kit/qa/qa.py`.

## Annotating a real screen recording

1. Record the screen separately (OBS / QuickTime, 1920x1080 or the native resolution). Hold still for a moment wherever you'll point at something.
2. Find targets: `python3 kit/hf/tools/locate.py rec.mp4 12.5 "Render"` → `{"box": [x, y, w, h]}`, or `grid.py rec.mp4 12.5 --ocr` and read them off the grid.
3. Annotate only while the screen is still (coordinates are per frame of the recording). Use `mediaStart` to choose the part of the recording to play.
4. Blur anything private with `sd.blur([[x, y, w, h], ...])`. The blur moves with zooms.

## Rules baked into the components

- **Never still**: inserts and diagram windows carry a slow push; the camera pushes in on long pieces (QA flags holds over 0.6 s).
- **Seek-exact**: camera moves, flowing dots, cursors, spinners and stickman poses are pure functions of time (`K.onFrame`). No `Math.random` anywhere (the linter checks).
- **Readable**: code ≥ 26 px, terminal ≥ 28 px; narrow windows (9:16) put code notes in a footer so they never cover code.
- **Real data only**: the terminal and code show real commands and output. Numbers come from real runs and pages.

## Gotchas (found while building this)

- **AAC spikes**: ffmpeg's native AAC encoder's noise substitution (PNS) can add +9 dB spikes on sparse noisy SFX (typing). Always mux with `-aac_pns 0`. It's set in every film, reel, the shorts renderer and normalisation.
- **Fonts**: never name a family after a CSS generic ("Serif", "Mono"). Use InstrumentSerif and JBMono.
- **Timelines**: register `window.__timelines[id]` literally in the page (the linter doesn't see `K.finish`).
- **Tweens after a set**: use `fromTo` with explicit start values (`immediateRender: false`); a plain `to` can capture stale values on seeks.
- **Puppeteer screencast**: `stop()` can hang after the file is complete; `showcase/make_screen.mjs` races it with a timeout.

## Status

v1.0.0 (2026-10-03, branch version_6). Verified:
- the 16:9 showcase renders and passes QA (−14.3 LUFS, TP −1.6, no freezes);
- the 9:16 check works: panel camera, card diagram, zoomed screen crop, 34 px code;
- the project tests pass (185).

Not built yet (add when a video needs them): animated timelines, network-flow presets, narrative charts, icon morphs, the rough.js sketch treatment (see the ranking in the session notes, and SCENES.md for fallbacks).

## v8 motion: springs, motion tokens and kinetic type (`kinetic.js`, 2026-10-07)

Why: the research behind it (Remotion vs HyperFrames, what makes top motion reels look premium) found that designer
motion differs from programmatic motion in its curves, not its renderer: no stock eases, several properties animating
with offsets, springs that settle instead of tweens that stop, staggers with a capped total, exits designed like
entrances, and sound landing on the motion's landing frame. `kinetic.js` is that vocabulary. It is **opt-in**: `core.js`
keeps preset_paper_studio's calm defaults (no bounce), so approved looks don't change.

| API | What |
|---|---|
| `HF.E.in` / `.emph` / `.out` / `.move` | ease-out-expo `(0.16,1,0.3,1)` for entrances, Material 3 emphasized `(0.05,0.7,0.1,1)` for hero reveals, ease-in-expo `(0.7,0,0.84,0)` for exits, in-out `(0.65,0,0.35,1)` for moves. Never use GSAP's stock `power*`/`back`/`elastic` in new work |
| `HF.spring(HF.SPRING.ui)` | a closed-form damped spring as a GSAP ease → `{ ease, duration, land, overshoot }`. Presets (Apple's ratio + response): `ui` 1.0/0.4 s (no overshoot), `snappy` 0.82/0.32 s (~1 %), `thrown` 0.68/0.42 s (~5 %), `soft` 1.0/0.65 s. Bounce only for things with momentum. Remotion's default spring overshoots 16 %: that's the "generic AI video" look |
| `HF.stagger(n, per, cap)` | offsets 2 frames apart, the whole run capped at 0.5 s; the first item leads |
| `HF.land(K, el, t, { from, spring, sfx })` | entrance: opacity (fast), scale (spring), x/y/rotation (spring, one frame later), blur (expo). Returns the landing time; `sfx` fires one frame before it |
| `HF.leave(K, el, t, { to })` | exit: 0.26 s ease-in-expo with blur, shorter than the entrance |
| `HF.kinetic(K, parent, o)` | kinetic type. `text: "Most people spend *4 hours* editing"` (`*span*` = stressed, `|` = line break) at `at` with a capped stagger, or `from`/`to` word ids of the cut (+ `stress: [ids]`) so each word lands on its spoken time minus a frame. `style`: `slam` (Anton, scale 1.9 → 1 on the snappy spring, blur clears, the line takes a 7 px impact), `pop` (Montserrat 900, thrown spring), `rise` (serif in a mask, expo), `track` (Montserrat 800, tracking 0.32 em → 0 with blur). Stressed words share one accent box that draws after they land; `split: "char"` staggers letters. `sfx`: `"stress"` (default), `"each"`, `"first"` or `null`. `kt.out(t)` exits word by word |

Fonts: Anton and Montserrat 800/900 are declared in `paper.css` (so the render waits for them) and copied by `vendor.py`.
Exact: everything is a pure function of timeline time (no requestAnimationFrame, no randomness); tests in
`tests/test_kinetic.py`.

**Demo**: `uv run python kit/hf/demos/kinetic/build.py` renders the same 12 s beat sheet with the v7 vocabulary and with
`kinetic.js` → `output/final/kit-hf-demos-kinetic/kinetic_compare.mp4` (before, then after, with sound) and
`kinetic_side_by_side.mp4`.

## v7 styles: sketch, marker notes, scribble outline, paper collage

Four hand-made looks for explainers (16:9) and Reels/Shorts (9:16) about AI and coding tools, added in version 7.
Each is one module inlined by `vendor.py` like the rest of the kit, plus its library in the film's `vendor/`.
**Demo**: `demos/styles/`: `styles_demo.mp4` (9:16) and `styles_demo_16x9.mp4` (`--land`), 25 s, one beat per style
in the order scribble (the face is the hook), sketch, marker notes, collage. `python3 build.py --clip`, then the commands
in its docstring. Both pass `kit/qa/qa.py` (−14.2 LUFS, TP −1.9, no freezes); a render takes 42–150 s depending on load.
Media there stays local (`work/`, `assets/`).

| File | What it gives you |
|---|---|
| `sketch.js` | `HF.sketch`: Excalidraw-look diagrams on rough.js that draw themselves (strokes on, fills fade, labels write) and boil while they hold |
| `annotate.js` | `HF.annotate`: marker strokes on perfect-freehand over screenshots, code and windows: circle, underline, highlight, scribble-out, strike, box, arrow, handwritten note |
| `scribble.js` + `tools/scribble.py` | a hand-drawn outline that follows the speaker: built offline from the person matte, picked per 12 fps step |
| `collage.js` | `HF.collage`: torn-paper screenshots, tape, shadows, halftone, paper grain, motion on twos, a 2.5D parallax camera |

All four share three helpers (defined by whichever module loads first): `HF.rng(seed)` (mulberry32, for build time),
`HF.handFont()` (the Excalifont / Caveat `@font-face`, and a `document.fonts.load` so the renderer's `fonts.ready`
waits for it) and `HF.drawOn(tl, path, t, dur)` (DrawSVG when vendored, a dash offset otherwise).

**Rules for all four**
- **One hand-made style per passage, two or three per video.** They are seasoning, like the stickman: the speaker,
  the real screen and the cards stay the meal. Never stack two of them on the same frame (marker notes on a collage
  piece is fine; a scribble outline plus a collage is not).
- **Ink, one orange, plus green for "done".** Hand strokes in `C.acc` (or `C.ink`), fills only as hachure or a pale
  tint; no extra colours, no clip-art icons, no emoji.
- **Exact or nothing**: geometry is built once from a seed; per frame you only select or slice it. No `Math.random`,
  no `requestAnimationFrame`, no real-time physics. Anything "boiling" steps at 12 fps (`floor(t * 12)`).
- **Never at time 0**: a layer that must show on the first frame gets no `tl.set` at 0 (GSAP's zero-time sets can
  render in reverse on the runtime's first seek; the demo's first beat came out blank until this was fixed).

### 1. Sketch diagrams (`sketch.js`)

**When to use (the rule)**: a flow, a loop or an architecture you *explain while it builds*: agent loops, "prompt
→ plan → edit → check", request paths, before/after pipelines. Three to six boxes. Use the living diagram
(`diagram.js`) instead when the same diagram must come back across the video with focus/zoom, and a card when it's
a list, not a flow.

```js
const sk = HF.sketch(K, layer, { x: 60, y: 440, w: 960, h: 1060, seed: 7 });   // view box in the layer; options: roughness, strokeWidth, dark
sk.node("read", { x: 480, y: 130, w: 300, h: 140, label: "Read", fill: "#f0a98d" });  // centre x/y in view px; shape: rect|ellipse|diamond; fillStyle
sk.arrow("a1", "read", "plan", { bend: -0.2 });          // node ids or [x, y]; bend < 0 bows outward on a clockwise loop; dashed, label
sk.text("mid", 480, 496, "loop until\nthe tests pass", { size: 42, color: C.ink2 });
sk.ring("ring", "check", { color: C.acc });               // an emphasis loop around a node
sk.line("l", [[x, y], ...]);                              // a free rough curve
const end = sk.draw(["read", "a1", "plan"], 0.1, { stagger: 0.4 });   // returns when the last label is written
sk.boil(3.9, 6.3);                                        // 12 fps line boil, only on items already drawn
sk.hide(Object.keys(sk.items), 6.0);  sk.show(a, b);
```

**How it stays exact**: each shape is generated by rough.js three times with fixed seeds (`seed`, `+1000`, `+2000`);
variant 0 is drawn on with DrawSVG tweens (an arrow's shaft, then its head); fills (hachure or solid) only fade;
labels write on with a clip wipe. During a boil window a `K.onFrame` shows variant `floor(t*12) % 3` and nudges the
labels by a fixed table. rough.js only calls `Math.random` when a seed is 0, which the module never passes.

**Cheap-look risks**: boil while something is still drawing (strobing); roughness above ~1.6 (looks broken, not
hand-made); more than one fill colour family; long labels (keep to one or two words, 52–64 px); arrows that touch
labels. Hand labels at 9:16 need ≥ 40 px.

### 2. Marker notes (`annotate.js`)

**When to use (the rule)**: to point at *one thing* on a real screenshot, code window or recording that the
narration names: a number, a line of code, a button. One to four marks per shot, each landing on its word.
`screen.js` (spotlight + label) stays the choice for a moving recording you zoom into; marker notes are for a still or
held frame. **Never on a face**: pass the face box as `avoid` and any mark that touches it throws at build time.

```js
const an = HF.annotate(K, group, { x, y, w, h, srcW: 1728, avoid: [faceBox] });   // over the image; boxes in its pixels (locate.py)
an.underline([419, 295, 92, 15], t);         // { double: true }
an.circle([815, 516, 72, 24], t, { pad: 14 });
an.highlight([x, y, w, h], t);               // highlighter sweep, multiply blend
an.scribble([x, y, w, h], t);                // scratch it out    an.strike(box, t)   an.box(box, t)
an.arrow([x0, y0], [x1, y1], t, { bend: 0.22 });
an.note(x, y, "split 2 ways", t, { size: 56, rotate: -3 });                    // Excalifont, written on
// every call: { dur, size, color, seed, until, sfx: false }; an.clear(t)
```
Put the annotated element and the `annotate` view in one parent and give neither a z-index or opacity of its own,
or the highlighter's multiply has nothing to multiply with (in the demo: `G1` holds the window and the marks).

**How it stays exact**: every mark is an authored point list (seeded wobble, a pressure curve: quick press, slight
swell, lift). At time t the visible part is `getStroke(points.slice(0, n(t)) + one interpolated point, { last: done })`,
a filled outline polygon (so no dash-offset), recomputed in `K.onFrame` only while it is drawing.

**Cheap-look risks**: perfect circles (use the default overshoot), marks wider than 12 px at 1080 wide, more than one
colour on one screenshot, notes longer than three words, highlighter on a dark theme (multiply vanishes: use an
underline), marks on text that is too small to read anyway (zoom first).

### 3. Scribble outline (`scribble.js` + `tools/scribble.py`)

**When to use (the rule)**: to make the speaker the subject of a beat for 2–4 s: the hook, a strong opinion, "this
is me", a reaction. One or two per video. Pick a clip with stable framing (1–3 s of one position is ideal); fast head
turns and hands near the face cost quality. Not over a busy screen recording, never with captions over the face.

```sh
python3 kit/hf/tools/scribble.py work/clip.mp4 work/outline.json --expand 14 --amp 5 --passes 2 --preview work/outline_sheet.jpg
```
Look at the preview sheet (every 4th step drawn on its frame) before using it: blobs at hair or hands show there.
`--open N` removes protrusions thinner than N px (fingers, hair wisps); `--temporal union` (default) keeps the line
outside the person through a whole 12 fps step, so a fast turn never puts it on the face. If the line still touches a
cheek on a fast turn (motion blur shrinks the matte), raise `--expand` (the demo uses 20).

```js
// build.py inlines the JSON: const S = {...}
HF.scribble(K, panel, S, { at: clipStart, box: [x, y, w, h], from: clipStart + 0.25, until: end, width: 8, draw: 0.75, erase: 0.3 });
// box = where the clip's full source frame sits in `panel` (the same box as the <video>); color "#fff" on dark footage
```

**How it stays exact**: everything is offline: personseg mattes at 12 fps (taken mid-step), union over neighbouring
steps, blur, largest blob, holes filled, a round expansion of 10–16 px, `findContours`, the runs along the frame
border removed (the line stays open where the body leaves the frame), resampled, smoothed, then a seeded jitter per
step (three low-frequency sines + a little grain) and slight overshoot at the ends. The page builds every step's
path once (Catmull-Rom → cubic) and a `K.onFrame` sets the path of `floor((t - at) * 12)` and the DrawSVG range
(draw on, hold, draw off), with the pen also on the 12 fps grid.

**Cheap-look risks**: an outline that hugs the matte (looks like a bad cut-out: keep `--expand` ≥ 10); a line
crossing the face on fast moves (`--temporal union`, or pick a calmer clip); a thick single line (two passes at
8 px + a thin second pass read as drawn); holding it longer than ~4 s (it stops being an accent).

### 4. Paper collage (`collage.js`)

**When to use (the rule)**: a comparison or a "here is the evidence" beat built from *real* screenshots: two app
screens side by side, a headline and its source, a before/after. One collage per video, 5–8 s, 3–7 pieces. Not for
a live demo (use `screen.js`) and not for code (unreadable when torn and tilted).

```js
const cg = HF.collage(K, layer, { w: 1080, h: 1920, seed: 23 });   // options: perspective, board, mottle, grain, grainOpacity
const A = cg.piece({ x, y, w, h, z: 20, rot: -5, img: "assets/low.jpg", torn: "tb", tape: ["top"], print: 0.22 });  // torn: t|r|b|l|all; tape sides top|bottom|tl|tr|bl|br
const s1 = cg.strip("Same prompt.", { x, y, size: 100, rot: -3, z: 120, w: 560, h: 146 });    // a torn strip with words; italic, color, font, bg
const d = cg.halftone({ x: 800, y: 760, r: 330, z: -120, color: C.acc });
cg.enter(A, t, { from: "drop" });            // drop | pop | left | right | up | down, on twos
cg.move(t, { x: 0, y: -14, z: 55, ry: -2.5, rx: 1.5, dur: 7, ease: "sine.inOut" });           // the camera
cg.show(a, b);  cg.exit(A, t);
```

**How it stays exact**: torn edges (an outer paper outline and an inner printed face, so a white fibre rim shows on
torn edges), tape ends and halftone dot sizes are generated once from the seed; the grain and board mottling are SVG
`feTurbulence` with fixed seeds (static). Piece entrances live on a child timeline that a `K.onFrame` drives with
`child.time(floor(t*12)/12)` (motion on twos); resting pieces get a sub-pixel nudge per step from a prebuilt table.
The camera rig is moved by `fromTo` tweens on the main timeline (smooth), so the pieces at different `z` parallax
against each other and the oversized board behind them.

**Cheap-look risks**: too many pieces or tapes (clutter); all pieces at the same angle; stock-looking textures (keep
grain under ~0.5 opacity and the board mottle subtle); upscaled small screenshots (keep scale ≤ 1.2, the `print` dots
hide a little softness); a camera push so deep the outer pieces leave the frame (the demo ends at `z: 55`).

### Libraries and licences

| What | Licence | Where |
|---|---|---|
| rough.js 4.6.6 | MIT | `npm i` at the repo root; `vendor/rough.js` (external file: it contains `Math.random`, unused with a seed) |
| perfect-freehand 1.2.3 | MIT | `npm i`; vendored as `vendor/perfect-freehand.js` (the CJS build wrapped to set `window.PerfectFreehand`) |
| GSAP DrawSVGPlugin 3.15 | GSAP standard licence (free, including plugins, since 2025) | `node_modules/gsap/dist`; `vendor/DrawSVGPlugin.min.js` |
| Excalifont (Latin subset) | SIL OFL 1.1 | `kit/fonts/Excalifont-Regular.woff2`, from excalidraw's GitHub; licence in `kit/fonts/Excalifont-OFL.txt` |
| Caveat 700 (fallback hand) | SIL OFL 1.1 | `kit/fonts/Caveat-700.ttf` (already in the kit) |

Excalifont's Latin file covers U+20–7E and Latin-1 (no arrows or ✓: draw those as strokes). `vendor.py` copies the
libraries with `copy_libs()` and skips (with a warning) any that isn't installed.

## v7 camera: motion vocabulary, director, motion blur (`motion.js`, `HF.camera`, `kit/motion/camera.py`)

The speaker's camera used to put a new framing on every cut (1.0 / 1.08 A/B/A/B) with a constant drift. Version 7
replaces it with a small vocabulary of moves used the way top editors use them, and a **director** that picks them
from the edit. `HF.camera` keeps its call signature; the old camera is `HF.camera.v1`.

**Demo**: `demos/motion/` (`build.py` docstring has the commands): `demo_motion.mp4` (16:9, 45 s of the raw jobs/ew2
take, every move named on screen as it happens), `demo_before_after.mp4` (v1 above v2, same edit) and `demo_reel.mp4`
(9:16 panel with the full-screen hook, reel rules). The demo loosens the punch budget to 7 s so every move fits in
45 s; real films keep 16 s.

### The vocabulary (`HF.motion.RULES.long`; `reel` in brackets)

| Move | Scale | Timing | Easing | Blur | The director uses it |
|---|---|---|---|---|---|
| reframe (hard cut) | W 1.00 ↔ 1.15 (panel 1.00 ↔ 1.15) | 0 f, held ≥ 3 s (1.5 s) | none | none | at a new thought: a sentence start or a scene change; never mid-sentence; never on every cut |
| punch (hard cut) | 1.22-1.32 (1.28-1.40), and ≥ 1.1x every framing it cuts from or to | 2 f before the stressed word, held to the end of the line (0.8-3.2 s) | none | none | `punch`/`punchline` tags, then guesses (numbers, $/%, "never", "best", a word said three times); 1 per 16 s (6 s) |
| ease (eased punch) | x1.18 (x1.2) | 15 f (12 f) | power3.out | 180°, ≤ 8 samples | `ease` tags, and the second of two punches in a row |
| snap (crash zoom) | 1.4 (1.5) + 3% overshoot | 5 f (4 f), settles in 8 f | expo out (.16,1,.3,1) | 270°, ≤ 24 samples | `joke` tags (a reaction beat), with a swish; ≥ 25 s apart (10 s) |
| landing shake | 1% of the height (1.2%), ≤ 0.4° (0.5°) | 7 f, exponential decay | 9 / 11.3 / 7.4 Hz sines, zero phase | as the snap | on every snap's landing, clamped to the slack so no edge shows |
| push (slow push) | +5-10% (~1.2 %/s) | the thought, 4-14 s | sine in-out (.37,0,.63,1) | none | `story` tags, then the longest thoughts, ≥ 30 s apart (15 s); then a hard cut back out |
| zoomx (zoom transition) | 100 → 300% → 100% | 6 f out + 6 f in | expo in / expo out | 330°, ≤ 32 samples | `section` tags only (a chapter change), with a swish |
| drift | +0.6 %/s easing out at +3% | every held framing | exponential ease-out | none | always (a held shot is never a still) |

**Director rules**: framings change only at new thoughts and only after a hold; consecutive cuts inside a thought keep
the framing (a plain jump cut, face-locked); no hard cut between framings less than 1.1x apart (it reads as a glitch:
the punch goes further or the cut back picks the other framing); a punch that starts within 0.6 s of a cut moves onto
the cut, and one that would end within 0.6 s of the next cut ends on it (no double cuts); an ease or snap that opens a
thought starts from the framing before it (one move, not a cut plus a move); never the same move twice in a row
(punch ↔ ease, a second snap eases, a second push is dropped); moves stay 0.7 s clear of layout changes and 3 s clear
of zoom transitions; side layouts (SR/SL) get reframes, pushes and gentle punches (x1.12) only; PIP/OFF get none.
`P.log` (and `window.__camera` in the page) lists every decision with its reason.

**Composition**: the face anchor is the eyes (YuNet: 0.20 head widths above the box centre); the eyes sit on the upper
third unless that would crop the hair (top of the hair 1.1 head widths up, plus 3% headroom), at the layout's x (W/M/C
centre, SR right, SL left), clamped so the picture always covers the frame. Scale is interpolated in log space and
the eyes move in a straight line, so the face never swims during a zoom.

**Tags** (word ids, the film's own numbering): `{ punch: [...], punchline: [...], ease: [...], joke: [...],
story: [[first, last], ...], section: [...] }`. `auto: false` keeps only tagged moves. Sentence starts come from the
transcript's punctuation, so fix run-on transcripts (`.` per thought) before directing.

### Motion blur: baked in Python (measured)

A fast move needs motion blur: the average of N sub-frame transforms of the same source frame (sample times
t + (k/(N-1) - 0.5) x shutter/360/fps, never across a cut; N = ceil(largest on-screen travel / 1.5 px), capped per move,
none under 1 px). Two ways were built and measured on the same 4 s test (a snap and an eased punch, 26 blur frames,
1080p, against an exact float reference):

| | luma PSNR | mean / p99.9 error | cost | |
|---|---|---|---|---|
| (a) in the page: N stacked copies of the A-roll, copy k at opacity 1/(k+1) | 45.5 dB | 1.00 / 6.0 | +40% capture time for the clip (~0.45 s extra per blur frame); one `<video>` per sample per window (65 for 2 windows) | 8-bit blending; DOM grows with N x windows |
| (b) **baked**: `kit/motion/camera.py`, cv2.warpAffine (bilinear, sub-pixel) + float32 sum | **47.1 dB** | **0.81 / 4.8** | ~11 ms CPU per sample (≈ 1.5 s for a snap); one small all-intra clip per film (6 MB for the demo's 37 frames) and one `<video>` per window | exact |
| no blur (for scale) | 32.7 dB | 4.29 / 50.6 | | |

(b) is the camera's path: as exact as the reference allows, cheap, and it keeps the page small. The page and the bake
run the same `motion.js` (Node runs it in a sandbox through `kit/motion/plan.cjs`), so the baked frames continue the
browser's frames exactly. Without a bake the moves still play, unblurred, and `HF.camera` warns in the console.

### Adopting it in a film

```python
# build.py
sys.path.insert(0, str(ROOT / "kit/motion")); import camera
P = camera.plan({"pieces": pieces, "words": words, "fps": 30, "view": [1920, 1080], "framing": framing,
                 "format": "long", "tags": {"punchline": [2512], "joke": [2427], "story": [[2471, 2502]], "section": [2593]}})
blur = camera.bake(HERE / "assets/aroll.mp4", P, HERE / "assets/aroll_motion")   # after the A-roll asset is final
D["camera"] = camera.for_page(P, blur)                                              # src paths are "assets/..."
print("\n".join(P["log"]))
```
```js
// template.html
HF.camera(K, st, { plan: D.camera, pipRadius: 158 });
// 9:16: camera.plan({..., mode: "panel", top: 880, width: 1080, height: 1920, format: "reel", hook: [0, hookEnd]})
```
- Pieces need `face` = [cx, cy, size] from a YuNet track (films/expensewaale/face_track.py); words need `i, text, t, e`.
- Don't tween `st.wrap` (or `cam` top/height in panel mode) in the template: the camera writes them every frame. To own
  the wrap for a while (a custom hook), pass `active: [a, b]`.
- Re-run the bake whenever the A-roll or the plan changes (the clip holds finished frames).
- Old films are not rebuilt; if one is, switch it to `HF.camera.v1(...)` to keep its look (its reel tweens the wrap).

**Gotchas found here**: HyperFrames picks a clip frame as floor(time x fps), and `77/30` printed as `2.56667` is past
the frame, so a clip starting off a whole second repeats its 2nd frame (the camera gives windows a 0.1-frame lead).
A rawvideo pipe into ffmpeg must carry the output's colour tags on the input, or swscale converts the matrix (luma
-1.5 levels). The repo's `package.json` is `"type": "module"`, so Node helpers that load browser scripts are `.cjs`.

**The shorts CLI** follows the same rules (`shorts/plan/zoom.py`): `zoom_jump` 1.15 (was 1.08), `zoom_punch` 1.3
(was 1.15); a new framing only at a new sentence after 1.5 s (or after 4 s at any cut), never A/B on every cut; the cut
back out of a punch is never within 1.1x; zoomed framings put the eyes on the upper third with headroom; sharpening is
per segment after the Lanczos scale and grows with the zoom (0.22 at 1.0, 0.29 at 1.15, 0.36 at 1.3, grade 0.5).
