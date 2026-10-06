# preset_paper_studio

The look and workflow of **"I Don't Use a Video Editor. Claude Edits My Videos"** (2026-10-02), the author's first approved long-form edit.

When the user says **"use preset_paper_studio"** (or "paper studio", or "the how-i-edit style"), follow this file from top to bottom. It produces:

- a **16:9 YouTube long-form video** (2–4 min talking-head tech explainer) with a 10-second launch film at the end, captions.srt and posting notes;
- a **9:16 teaser reel** (about 30 s) for Instagram and YouTube Shorts that points to the long video.

Everything is free and local: DeepFilterNet, Apple Vision (head track only), numpy/OpenCV, HyperFrames + GSAP, ffmpeg, and library music and SFX. Nothing is paid.

---

## 1. The idea in one paragraph

Keep the real room. The speaker sits in front of a plain cream wall, so we **don't cut them out**: matte edges, hands and hair are what made the earlier version look fake. Instead the footage is **graded and lit**: the bright wall is tamed, a soft key light follows the face, plus a warm white balance, a gentle vignette, sharpening and fine grain. The graphics are designed to match that wall: **warm paper and ink, one orange accent, an elegant serif for headlines and calm motion**. There is no blue, no glitch, and no title card. The video opens on the speaker with a name title. One calm music bed runs under the talk, and an energetic track plays only for the payoff (the launch film), cut on its beats.

## 2. Files

| | |
|---|---|
| `preset.json` | every token and number below, machine-readable (palette, type, motion, framing, audio, captions, reel) |
| `templates/longform.html` | the 16:9 HyperFrames composition: helpers, framing engine, every scene type, chapter tags, launch film, end card |
| `templates/reel.html` | the 9:16 composition: top graphics panel, face panel, word captions, launch excerpt, CTA, end card |
| `example/` | the how-i-edit implementation (edl.py, build.py, audio.py, cues.mjs, capture.mjs, blur_sessions.py, youtube_notes.txt, and reel/) to copy and adapt |
| `kit/look/grade.py` | the footage grade (shared kit tool) |
| `kit/qa/qa.py` | the quality gate (shared kit tool) |

`example/` is the original film's recipe on the `output/` layout (kit/paths.py); its footage isn't included, so read it as a model rather than run it. Copy `example/` into a new `films/<name>/`, copy `templates/*.html` to `src/template.html` (and `reel/src/template.html`), then change only what the new video needs.

## 3. Pipeline (commands)

Run from the film folder (`films/<name>/`) with `uv run python`. Nothing generated is written there: every script starts
with `F = Film(__file__)` (`kit/paths.py`), so the cut, grades, mixes and renders go to `output/temp/films/<name>/`
(`$W` = work, `$HF` = the HyperFrames project, `$R` = renders) and the deliverables to `output/final/<name>/`.
`uv run python build.py --paths` prints those folders. `T` is the take's temp folder (`output/temp/jobs/<take>/`).

```
# 0. ingest (once): output/jobs/<take>/source.mp4 + analysis.json (word timings)
uv run shorts probe "<video>" --job <take> --landscape && uv run shorts analyze <take>

# 1. face track of the whole take (YuNet, the v7 default) -> $T/source.face.json
uv run python ../../kit/look/faces.py ../../output/jobs/<take>/source.mp4 $T/source.face.json

# 2. voice: DeepFilterNet3 on the take's audio
ffmpeg -i ../../output/jobs/<take>/source.mp4 -vn -ac 1 -ar 48000 $T/voice_raw.wav
~/.venvs/df/bin/deepFilter $T/voice_raw.wav -o $T/

# 3. the cut: KEEP word ranges + FIX spellings in edl.py -> edl.json, cuts.json (here); vo.wav, aroll.mp4, aroll.map.json ($W)
uv run python edl.py

# 4. grade ONLY the cut (fast: ~9 min for 160 s on the M1 Pro)
uv run python ../../kit/look/grade.py $W/aroll.mp4 $W/aroll_graded.mp4 --track=$T/source.face.json --map=$W/aroll.map.json

# 5. references: blur private screenshots (raw in $W, blurred copy in assets/), capture web pages (assets/web, light mode)
uv run python blur_sessions.py && node capture.mjs

# 6. composition + captions, sound cues, mix
uv run python build.py && uv run python build.py --cues && uv run python audio.py
npx hyperframes lint $HF
npx hyperframes snapshot $HF --at <one time per section> --no-end --describe false -o $R/snap   # look at every sheet

# 7. render, mux, gate
npx hyperframes render $HF -o $R/raw.mp4 --fps 30 --quality delivery --quiet
uv run python build.py --mux
uv run python ../../kit/qa/qa.py <output/final/<name>/out>.mp4 --expect-duration=<s> --expect-size=1920x1080 --fps=30 --cuts=cuts.json --voice=$W/vo.wav --allow-freeze=<end card>

# 8. reel (after the long render: it reuses the launch film); its $W/$HF/$R are the reel's own (build_reel.py --paths)
cd reel && uv run python reel_edl.py && uv run python ../../../kit/look/grade.py $W/aroll.mp4 $W/aroll_graded.mp4 --track=... --map=$W/aroll.map.json
uv run python build_reel.py && uv run python build_reel.py --cues && uv run python build_reel.py --audio
npx hyperframes render $HF -o $R/raw.mp4 --fps 30 --quality delivery --quiet && uv run python build_reel.py --mux
uv run python ../../../kit/qa/qa.py <output/final/<name>/reel>.mp4 --expect-size=1080x1920 --fps=30 --voice=$W/vo.wav --cuts=cuts.json --allow-freeze=<end card>
```

When the video is delivered, `uv run shorts clean` frees the temp space; `films/<name>/` and `output/final/<name>/` stay.

One-time install (already done on this Mac): `uv venv -p 3.11 ~/.venvs/df && VIRTUAL_ENV=~/.venvs/df uv pip install "torch==2.0.1" "torchaudio==2.0.2" "numpy<2" deepfilternet soundfile`. Newer torchaudio breaks DeepFilterNet (`torchaudio.backend` is missing).

## 4. Footage look (`kit/look/grade.py`)

No matte edges anywhere. The person mask is only used to find the head.

| Step | Setting |
|---|---|
| Tone curve (monotone cubic through measured points) | clip black → **0.03**, median skin → **0.50**, wall → **0.87**, soft shoulder (white ≤ 0.93) |
| Key light | gaussian at the camera-left cheek (1.05 × head width), **+20 %**, weighted to skin by colour (wall spill 45 %), slightly warm |
| Fall-off | −8 % on the far cheek, for shape |
| Vignette | −16 % at the corners, elliptical, centred a little above the middle |
| Colour | warm mids (+0.013 R, −0.012 B) and highs (+0.018 R, −0.016 B), saturation ×1.10 everywhere except skin |
| Detail | luma unsharp 0.45 (σ 1.3); grain 1 % (6 cycled plates) |
| Speed | 0.43 s/frame/worker, 8 workers, frames sent to the pool in batches of 48 (memory stays flat) |

Test before a full run: `python3 kit/look/grade.py clip.mp4 out.mp4 --test=5,40,90` writes before/after JPGs. Look at a face crop: the wall should read warm cream, not grey, and the face should be lit, not orange.

## 5. Design system

**Palette**: paper `#f3eee6` (radial to `#e9e2d7` at the edges, plus a 4 % dot grain), cards `#ffffff` with shadow `0 22px 60px rgba(60,40,20,.14)`, ink `#1b1815`, secondary `#4a443d`, muted `#8a8178`, accent `#e2562b` (tint `#fbe4dc`), success `#2f8a5b` (tint `#dcefe3`). Dark beats use ink as the background with paper text. **Never blue.**

**Type**:
- **InstrumentSerif** for headlines and big numbers, with emphasis words in *italic accent*.
- **Inter** 500–800 for UI, pills and labels.
- **JBMono** for code, URLs and step numbers.
- Labels: Inter 700, 20 px, uppercase, 0.22 em tracking, accent colour.

> ⚠ Never name a font family after a CSS generic ("Serif", "Mono"…). Previews looked right, but the HyperFrames render fell back to sans.

**Components** (all in `templates/longform.html`):
- `side(a,b)`: content over the wall next to the speaker. Columns are x 110–830 (speaker right) or 1150–1830 (speaker left).
- `insert(a,b)`: full-screen paper that rises in.
- `card`, `pill`, `win` (a macOS-style window for screenshots, with a scrolling tall capture inside).
- `words` + `rise` for masked serif text.
- `typeText`, `countUp`, `phone` (B-roll in a phone frame).
- `chapter(a,b,num,name)`: the top-left pill with a numbered orange dot.
- The name lower-third, the 5-step `flow()` diagram, the launch film and the end card.

**Motion**:
- Entrances: 0.6 s `power3.out`, travelling 28 px, blur 8 → 0.
- Exits: 0.35 s `power2.in`.
- Text: rises word by word, 0.7 s `expo.out`.
- Inserts: rise in over 0.55 s.
- Banned: bounce or back eases, glitch, RGB split, shader transitions.
- Keep holds moving. A slow linear push on anything held longer than about 0.6 s keeps QA's freeze check quiet.

### Scene components and planning (from v1.2)

New films use the reusable components in `kit/hf/`:
- speaker camera, side and insert layers, windows, lower third, chapters;
- the living diagram;
- annotated screen demos;
- code and terminal walkthroughs, compare, chat and the end card.

They replace hand-writing the scenes in `templates/longform.html`, which stays as the reference for how-i-edit. Pick scenes from what each passage explains (`kit/refs/SCENES.md`), write `visual_plan.json` and gate it with `kit/hf/plan_check.py`. The worked example is `kit/hf/showcase/`.

### Stickman moments (optional, from v1.1)

Use `kit/stickman/` for 2 to 4 short moments per video (2–5 s each), never a whole video. They suit visual metaphors, emotional story beats, processes you can act out, before/after and roles (see `kit/stickman/README.md` for the rules, API and ready ideas). Mount them as an `insert()` or a `side()`, copy `stickman.js` into the film's `vendor/`, and call `Stickman.drive(tl, total)` once. The figure uses the preset's ink, paper and accent, so it needs no extra styling.

## 6. Framing (16:9)

Use one full-frame video element and change its transform per piece. Framings are set on cuts and only animate when going into or out of the corner window.

| Code | Use | Scale (alternates per cut) |
|---|---|---|
| `W` | the intro, wide | 1.00 / 1.08 |
| `M` | plain talking, chapter starts | 1.14 / 1.22 |
| `C` | emphasis, the last line before the payoff | 1.30 / 1.22 |
| `SR` | speaker right (face x 1250), content on the left | 1.20 / 1.28 |
| `SL` | speaker left (face x 640), content on the right | 1.32 / 1.38 (the take sits right of centre, so it needs more push) |
| `PIP` | full-screen insert, with the face in a 316 px rounded square at the bottom-right (scale 0.5, 5 px white ring) | |
| `OFF` | full-screen insert with no face (B-roll walls) | |

Rules:
- Clamp the translation so frame edges never show.
- Prefer SR. Check SL against the head: it overlaps if the head is close to the lens.
- Pieces longer than 2.2 s get a 2.5 % linear push-in (`fromTo` with explicit start values).
- Source is 720p: don't go past 1.38.

## 7. Structure of the long-form (what worked)

1. **Open on the speaker**, wide. No title card. At ~0.2 s show the **name lower-third**: name in serif, a one-line descriptor, and a growing orange bar. The comments or questions being answered appear as cards on the far side.
2. **Hook line** in big serif beside the face (e.g. "No editor. / *Just Claude.*").
3. **The myth** as a prompt card ("make it viral ✨") with a ✕ result.
4. **"In this video"**: label plus a big serif title of what they'll get.
5. **Proof screen** (blurred private details, with a "Private details blurred" pill and a highlighted count).
6. **The workflow overview**: the 5-step `flow()` diagram. Then **numbered chapter tags** (01 Record … 05 Build in code), plus un-numbered tags for the later parts ("The hard part", "Why it's fast", "The repo", "The 10-second test").
7. Each step alternates side cards and full-screen inserts with the corner face (real repo and web screenshots captured in light mode, scrolling).
8. **Drama**: "2 days" → "*gone.*" with a soft hit, then the rebuilt checklist.
9. **Payoff number** ("15–20 *minutes*").
10. **Recap** (the same diagram, all ticked), **repo + an honest caveat**, then the **comment CTA**.
11. **Launch film**: 7 shots of 2 beats (9.9 s) on the payoff track. Shot 1 is the hook callback on ink, then numbered steps on alternating paper / ink / orange backgrounds. A constant linear push on each shot.
12. **End card**: "Edited with *Claude.*", a subtitle, the Subscribe pill and the @handle.

Cutting rules (`example/edl.py`, from `kit/refs/EDITING.md`):
- Pad word ends: vowel +30 ms, sibilant +120 ms, other +50 ms; lead-in 40 ms.
- Shorten pauses over 0.30 s to a 0.12 s sliver.
- Play at 1.07x, with 25 ms hsin fades on every splice.
- Drop the false start ("So hi" → "hi").
- Fix every misheard name in `FIX` (cloud → Claude, cash → cache, co-work → Cowork…).

## 8. Audio

- **Voice**: DeepFilterNet3, then the `VOICE_CLEAN` chain in `edl.py`, at −19 LUFS before the mix.
- **Bed**: one track under the whole talk, LAKEY INSPIRED – *Chill*: −13 dB under speech, −4 dB in gaps, 1.6 s fade into the launch film. Pick calm, steady tracks; **no EDM drops under talking**.
- **Payoff**: MokkaMusic – *Drive* (85 BPM, beat 0.706 s, first beat 0.385 s). It enters on a downbeat (track time = phase + 16 beats) exactly at the launch film. Each launch shot is 2 beats long, and a cinematic riser leads in 2.6 s before.
- **SFX** are quiet and functional:
  - air-woosh on inserts, −21 dB;
  - laptop typing under typed text, −23 dB;
  - bubble pop on cards, −23 dB;
  - box-check on ticks, −21 dB;
  - soft bass hit on drama and launch shots, −15 dB.
  - About 60 cues in 3 minutes.
- **Master**: −14 LUFS integrated, −1.5 dBTP (two-pass loudnorm plus a limiter), in `audio.py`.
- Credits go in the posting notes: LAKEY INSPIRED (soundcloud link), MokkaMusic – Drive, Mixkit SFX.

## 9. The reel (9:16)

- **Lines**: the strongest from the same take, in a new order: hook → what was built → the drama → the fix → the payoff number. Then 5.6 s of the long video's launch film (4 shots, beat-locked), then the comment CTA, then "Full video *on my channel*". About 30 s.
- **Layout**:
  - top panel 0–880 (paper, big serif graphics);
  - burned word captions at y 730 (Inter 800, 66 px, 3 words a page, active word orange);
  - face panel 880–1920, a 1:1 crop of the 16:9 take alternating 1.0 / 1.12 with a 3 % push.
- **First frame**: the hook text is already on screen.
- **Music**: Drive throughout, beat-locked to the excerpt (`build_reel.py` finds the bar), 12 dB under speech, +4 dB during the excerpt.
- **Posting copy**: see `example/reel/reel_notes.txt`. Link the long video as the Short's "Related video".

## 10. QA (never deliver without it)

- `kit/qa/qa.py` must report PASS or WARN; FAIL (exit 3) is never delivered. Fix every MEDIUM if time allows: static holds get a push.
- Snapshot sheets: one frame per section. Check text against the head (side layouts), the chapter pill against window bars, the corner face against tiles and cards, and code overflow.
- **Pull frames from the final render too.** The render compiler can differ from snapshots (fonts!).

## 11. Gotchas we hit (so they don't repeat)

- **Fonts named like CSS generics** fall back to sans in the render only. Use InstrumentSerif and JBMono.
- **A `tl.to` push-in after a `tl.set`** can capture stale start values on seeks (a wrong first frame). Always use `fromTo` with explicit values.
- **`Pool.imap` over a frame reader** decodes the whole clip into RAM and swaps the 16 GB Mac to death. Use bounded batches (grade.py does this now).
- **Overnight runs**: keep-awake only stops idle sleep. Keep the lid open and the charger in.
- **Not cloud-ready**: there's no git remote, footage and assets are gitignored, and Vision is macOS-only.
- **Web captures**: light mode (`capture.mjs`), decline cookie banners, 2x scale, plus a tall capture for scroll moves.
- **Privacy**: blur session titles, branch chips and conversation text in any screenshot (`blur_sessions.py`, with a review copy outlining every box).
- **Personal channel**: no brand logos of your own employer or clients, no real third-party logos in mockups, and no invented numbers (stars and repo counts come from the captured pages).

## 12. Adapting it to a new video

1. Copy `example/` → `films/<name>/` and `templates/longform.html` → `films/<name>/src/template.html` (same for the reel).
2. In `edl.py`: set `JOB`, the `KEEP` word ranges with tags, `FIX` spellings and the launch length.
3. In the template:
   - rewrite the `FR` (framing per tag) map;
   - write each section's block, keyed to `W(<word index>)`;
   - set the `chapter()` calls and the steps in `STEPS`.
   - Keep the helpers, the framing engine, the palette and the motion as they are.
4. In `audio.py`: keep the bed and payoff unless the topic needs a different mood. Re-measure BPM and phase if you change the payoff track (the snippet is in the how-i-edit session: onset autocorrelation over a 0.700–0.720 s grid).
5. Rename the lower-third descriptor, the end card subtitle, the handle and the posting notes.
