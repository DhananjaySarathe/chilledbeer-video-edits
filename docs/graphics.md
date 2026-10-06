# Writing a graphics template

A template is one reusable animated graphic. Jev picks it by its description, Claude fills its words, and the
renderer turns it into a scene video (1080×1920, 30 fps) that is laid over, or replaces, the speaker.


## Files

```
kit/graphics/<id>/
  template.html   markup + <style> + <script>, inserted into the body of the host page
  meta.json       what it is (Jev reads `description`), its params, duration, kind, captions, sound cues
  example.json    params used for the library preview and checks
```

The host page already loads `kit/graphics/_runtime/theme.css` (tokens, fonts, components) and
`_runtime/runtime.js` (the `GFX` object), and sets `window.__GFX__` with params, duration and speaker frames.
Put your `<script>` last in `template.html`, and wrap it in an IIFE: `(() => { ... })();`.

Read the three reference templates before you write one: `title_behind` (speaker kind + cutout), `stat_chart`
(fullscreen data) and `chat_thread` (fullscreen mockup).

## Kinds

| kind | background | use |
|---|---|---|
| `overlay` | transparent: never paint the whole frame | sits on top of the speaker (badges, pills, stickers, camera UI) |
| `fullscreen` | cream `--bg` is painted for you | replaces the picture while the voice continues (mockups, charts, cards) |
| `speaker` | cream `--bg` is painted for you | a fullscreen scene that contains the speaker: bind an `<img>` with `GFX.speaker(img)` |

Speaker frames are 720×1280 (9:16) JPEGs of the edited video, or PNGs with a transparent background when
`meta.cutout` is `true`. Show them with `object-fit: cover` (class `speaker`), scaled and moved however you like
(cards, phones, tilts, grayscale filters, rounded corners).

## The clock: every change must be seekable

The renderer seeks frames in any order and reuses frames where nothing moves. Therefore:
- **Allowed motion:** only `GFX.anim` / `GFX.in` / `GFX.out` (Web Animations), `GFX.each` / `GFX.tween` / `GFX.count` / `GFX.type`
  (per-frame callbacks), or CSS `@keyframes` animations (they start at scene time 0).
- **Never use** `setTimeout`, `setInterval`, `requestAnimationFrame`, `Date`, `Math.random` or CSS `transition`. Use `GFX.rand(seed)`.
- **Time units:** milliseconds from the scene start. `GFX.duration` is the scene length.
- **Infinite animations** (`iterations: Infinity`) make every frame "moving"; use them only for tiny loops like a blinking dot.

## Runtime API (`GFX`)

| call | what it does |
|---|---|
| `GFX.params` | params from meta defaults merged with the scene's values |
| `GFX.duration`, `GFX.fps`, `GFX.kind`, `GFX.face` | scene length (ms), 30, kind, speaker face box `{x,y,w,h}` in 1080×1920 space or `null` |
| `GFX.$(sel)`, `GFX.$$(sel)` | query helpers |
| `GFX.h(tag, attrs, ...kids)` | build elements; `attrs.text` sets text safely, `attrs.html` sets markup |
| `GFX.esc(s)` | escape text before putting it in `innerHTML` |
| `GFX.in(el, how, {at, dur, ease, stagger})` | entrance; `how` is fade, pop, rise, drop, left, right, zoom, blur, wipe, wipeUp, stamp or flip; returns the end time |
| `GFX.out(el, how, {at, dur})` | exit (preset reversed); defaults to the last 260 ms |
| `GFX.anim(el, keyframes, {at, dur, ease, fill, iterations, direction})` | any Web Animation; ease is out, in, inOut, back, snap, expo, linear or a CSS easing |
| `GFX.tween(fn, {at, dur, ease, from, to})` | eased number each frame |
| `GFX.count(el, from, to, {at, dur, decimals, prefix, suffix, group})` | count-up text |
| `GFX.compact(v)` | 48213 → "48.2K" |
| `GFX.type(el, text, {at, cps, caret})` | typewriter; returns the end time |
| `GFX.each(fn, from, to)` | raw per-frame callback, `fn(t)`; `[from, to]` is when it can change pixels |
| `GFX.fit(el, {width, height, max, min, lines})` | largest font size that fits `width` (default: the parent's width), `height` and at most `lines` lines |
| `GFX.fitLine(el, {width, max, min})` | one-line label: shrink, then cut with "…" |
| `GFX.layout(fn)` | run `fn` after fonts load; animations are switched off while layouts run, so measurements ignore entrance transforms |
| `GFX.track(el, [{at, ...css}], {ease})` | one element through several stops at set times (per-stop `ease` allowed) |
| `GFX.draw(path, {at, dur, ease})` | draw an SVG stroke from nothing (no dot from round caps) |
| `GFX.sfx(name, at, gain_db)` | sound cue at `at` ms; if a template emits any cues, they replace the `meta.json` cues (use it when timing depends on params) |
| `GFX.EASE` | the named CSS easings (out, in, inOut, back, snap, expo, linear) |
| `GFX.speaker(img)` | bind an `<img>` to the speaker frames; `GFX.hasSpeaker` tells whether frames exist |
| `GFX.still(img, {at})` | show the speaker frame at `at` ms and hold it (a freeze frame) |
| `GFX.pip({x, y, w, h, at})` | a face window of the live speaker (rounded portrait box, white rim, head and shoulders) over a mockup; speaker kind only |
| `GFX.cursor([{x, y, at, click}])` | animated pointer with a click ripple |
| `GFX.icon(name, {size, stroke, fill, width})` | inline SVG markup |
| `GFX.rand(seed)` | deterministic random numbers |

Icons: check, x, plus, minus, arrowRight, arrowUp, arrowDown, upload, download, folder, file, film, image, play, pause,
star, heart, user, users, chat, send, bell, search, clock, bolt, fire, trendUp, trendDown, chart, camera, mic, eye,
thumbUp, share, lock, gear, home, sparkle, dollar, calendar, link, battery, wifi, pointer, rec, dot, refresh,
scissors, wand, target, trophy, alert.

## Design language (from the reference, `Video-60259.mp4`)

- **Surfaces.** A clean cream background (`--bg`), white cards with soft deep shadows (`.card`, `--shadow`), and ONE loud accent (`--accent`, a hot orange-red) used for the key word, number or button. Ink is near-black.
- **Type.**
  - Titles: huge, condensed, uppercase (`.display` = Anton, `.condensed` = Oswald 700).
  - Small spaced mono labels: `.kicker` / `.label` = JetBrains Mono.
  - App UI: Inter.
  - Hand notes: `.hand` = Caveat.
  - Numbers use `font-variant-numeric: tabular-nums`.
- **Mockups are generic, clean and believable:** windows (`.window`, `.window.dark`), a phone (`.phone`, `.screen`, `.notch`), chips (`.chip`, `.chip.on`), pills (`.pill` with `.num`), badges (`.badge`), strike-throughs (`.strike`) and a cursor that clicks things. **No real logos or brand names:** say "Drive", not a trademark.
- **Motion.**
  - Things arrive snappy and settle: 350–600 ms, `back`, `expo` or `snap` easing.
  - Lists stagger by 80–160 ms, numbers count up, lines draw themselves, and a cursor acts on the UI.
  - The main content is in within the first ~600 ms, then something keeps developing (a count, a check, a click), so the scene never feels frozen.
  - Don't animate out unless it means something: scenes are cut hard.
- **Legibility at phone size.** Labels ≥ 20 px, body ≥ 32 px, headline numbers 120–220 px. Keep strong contrast.
- **Counting numbers:** Anton and Oswald have no fixed-width digits, so wrap counting digits in fixed-width cells or they wobble.
- **Avoid film grain and noise textures:** they make every captured frame about 3x larger, roughly double render time, and don't survive H.264.

## Layout rules (1080×1920)

- **Fullscreen and speaker kinds:**
  - Key content goes inside x 64–1016 and y 270–1090. Captions are drawn at about y 1120–1250 on top of every scene, so leave that band clear.
  - The `.stage` class gives you that box.
- **Overlays sit on top of the speaker's face and body.**
  - Use the top band (y 270–700) or the sides.
  - Never cover the mouth. If `GFX.face` is set, place things relative to it.
  - The right edge (x > 950, y 900–1600) holds the platform's like and comment buttons.
- **Every text param can be longer than the example.** Use `GFX.fit`, wrapping, or `max_len` in meta so nothing overflows. The checker flags clipped or off-frame text; mark deliberate bleeds with `data-bleed`.

## meta.json

```json
{
  "id": "folder_name", "name": "Human name", "category": "title|mockup|data|list|speaker|brand|overlay",
  "kind": "overlay|fullscreen|speaker",
  "description": "What the viewer sees, concretely (Jev reads this to choose; 1-2 sentences).",
  "use_when": "Which kind of spoken line it illustrates.",
  "params": {"name": {"type": "text|number|list|bool|color|object", "required": false, "default": null,
                      "max_len": 24, "help": "shape and advice"}},
  "duration": {"min": 1.2, "default": 2.5, "max": 5.0},
  "captions": "show|dark|hide",
  "cutout": false,
  "sfx": [{"at": 0.0, "name": "whoosh", "gain_db": -16}],
  "tags": ["..."]
}
```

- **`captions_by`:** lets a param pick the mode, e.g. `{"param": "dark", "values": {"true": "show", "false": "dark"}}`.
- **`captions`:**
  - `dark`: fullscreen scenes on cream, so captions switch to ink.
  - `hide`: the scene already shows the words.
  - `show`: over the speaker.
- **Sound names:** whoosh, pop, click, tick, typing, ding, stamp, swipe, riser, thud, rewind, scratch, boom.

## Checking your work

```bash
uv run shorts library check <id> [<id> ...]
```

This renders each template with `example.json` and prints JSON: `issues` lists param problems, JavaScript errors and clipped or off-frame text.
- **Preview strip** (four frames): `kit/graphics/_previews/<id>.png`. Look at it with the Read tool.
- **Full clip:** `output/temp/cache/graphics/<id>.mp4`. Overlays are shown on real speaker footage when a take exists; on a machine with no takes yet they sit on a grey stand-in, and then the tracked strip is left alone (the new strip goes next to the clip).

**Done means:**
- no issues;
- it looks polished at every point of the strip;
- it matches the reference's standard;
- odd params (long words, empty optional params, max-length lists) don't break it.
