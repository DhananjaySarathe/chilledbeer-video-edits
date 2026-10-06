# Premium YouTube reference: what top channels actually do

Measured 2026-09-29 from YouTube storyboards (every 5–10 s, whole video) of 11 channels, compared with our phone
footage. Measure any video with `python3 kit/refs/measure.py video.mp4 [step]` (same metrics).

## Measured look (median per video; luma 0–255, face frames only for the right block)

| Channel | Face share | Black p1 | Mid p50 | White p99 | Sat | Centre − edge | Highlight R−B | Skin hue° | Skin chroma |
|---|---|---|---|---|---|---|---|---|---|
| MKBHD | 0.82 | 7 | 62 | 220 | 0.2 | +24 | −6 | 120 | 22 |
| Ali Abdaal | 0.83 | 19 | 142 | 240 | 0.2 | +6 | +6 | 128 | 25 |
| Johnny Harris | 0.64 | 21 | 154 | 241 | 0.1 | −99 | +1 | 123 | 25 |
| MrBeast | 0.53 | 21 | 116 | 230 | 0.2 | −1 | +11 | 132 | 22 |
| Dhruv Rathee | 0.62 | 9 | 57 | 193 | 0.3 | +46 | +34 | 107 | 36 |
| Ishan Sharma | 0.52 | 2 | 133 | 245 | 0.2 | +20 | +16 | 128 | 25 |
| ColdFusion | 0.32 | 10 | 69 | 223 | 0.3 | +2 | +17 | 127 | 26 |
| Fireship | 0.17 | 7 | 41 | 243 | 0.3 | +44 | +34 | 130 | 25 |
| Matt Wolfe | 0.41 | 23 | 98 | 211 | 0.2 | −14 | +25 | 143 | 21 |
| Iman Gadzhi | 0.78 | 10 | 75 | 188 | 0.4 | +30 | +41 | 142 | 23 |
| Mrwhosetheboss | 0.87 | 11 | 63 | 197 | 0.4 | −9 | +31 | 117 | 23 |
| **Our raw phone takes** | – | **20–30** | **162–201** | **215–221** | **0.1** | **−24 to −44** | **≈0** | 125–133 | 24–27 |

What it says:
- **The subject is the brightest thing in frame** (centre − edge positive) for most of them. Our white wall is the
  brightest thing, so the eye goes to the wall. Fix: cut the speaker out and put them on a designed dark backdrop
  (Dhruv Rathee works exactly this way, on a green screen), or keep the room and pull it down ~1.3 stops.
- **Blacks are deep (7–23), highlights warm (R−B +10…+40)**. Ours are milky (20–30) and neutral.
- **Skin is left alone**: hue 107–143°, chroma 21–26 everywhere. Ours is already in range, so the grade must not push skin.
- The skin detector also fires on warm objects, so "face share" is approximate.

## Edit grammar observed (frames + sources)

- **Long-form uses no word-by-word captions.** MKBHD has no on-screen text in the first minute; MrBeast none in the
  first 30 s. Text is selective: 1–3 bold words for a key idea (Ishan: yellow all-caps "PREMIERE PRO"; Fireship:
  "RAILS DEVELOPERS"), name labels, numbers. Full captions go up as an SRT (closed captions), which also helps search.
  Word-by-word karaoke captions are a Shorts/Reels convention. [rev.com, kapwing.com]
- **Subject integrated, never boxed.** Dhruv stands off-centre on a themed backdrop, with the cut-out photo, document
  or headline on the other side. A rectangular "webcam window" on a slide reads as amateur.
- **A visual change every few seconds** in talking stretches: B-roll, a pop-in (logo/icon next to the speaker), a
  document with the key line highlighted (Matt Wolfe: soft highlight box + face bubble), a punch-in.
- **Backgrounds:** dark studios with practical lights (MKBHD, Iman, Matt Wolfe), shallow depth of field. Graphics
  panels sit on dark, softly glowing surfaces (Iman).
- **Screen recordings:** the announcement page, the one sentence highlighted, the face in a circle bubble (Matt Wolfe).
- **Structure (MrBeast guide):** minute 1 must deliver the title/thumbnail promise at high energy; minutes 1–3 need
  "crazy progression"; a re-engagement "wow" around minute 3; minutes 3–6 carry the best content; end abruptly after
  the payoff. [creatorhandbook.net, danielscrivner.com]
- **Documentary texture (Johnny Harris):** paper textures, film burn, grain, photos that look pinned, stepped 12 fps
  cut-out animation. Use for explainers; tech channels (MKBHD, Mrwhosetheboss) stay clean.
- **Sound:** whooshes, risers, clicks on graphic moves (Dhruv). Common guidance: music 18–20 dB under speech.
  Our owner's rule for Shorts is ~12 dB (18–20 was inaudible on phones); long-form v2 used ~13–14 dB.
- **Grade:** skin on the skin line, skin 60–70 IRE, cool lift / warm gain lightly; "if the viewer notices the grade,
  it's too heavy". [infinitecreation.io, focalpool.com]

## What the pipeline does now (v3)

1. `kit/bin/personseg <frames> <out> --mask` writes 8-bit person masks (~35 KB/frame).
2. `kit/look/look.py <frames> <masks> <out>`: temporal mask smoothing, ~1 px choke, small furniture islands dropped.
   A clean plate of the empty room (per-pixel median of uncovered pixels) repairs what Vision misses on fast,
   motion-blurred hands: enclosed holes are filled unless they are visibly the room, and skin-toned pixels in
   Vision's uncertain zone that differ from the room become solid. The plate is also removed from edge pixels (no
   white halo). The grade is anchored on skin: black point → 0.035, skin → 0.45 (this also matches the takes to each
   other), a gentle luma S-curve, a soft shoulder, warm highlights / cool shadows, +16 % saturation except on skin.
   Output is RGBA WebP. `--relit` also writes the "real room pulled down 1.3 stops + warm practical" variant.
3. Composition: the speaker stands on a studio backdrop (navy, a cool glow that follows the head for shirt
   separation, a warm practical on the far side, slight parallax). Layouts: full / left third / right third / bubble.
   Heroes (big word behind the head) are a layer between backdrop and speaker.
4. Long-form: keyword pops (`kw()`) instead of captions; captions.srt for upload. Shorts keep burned-in captions.

## Result on model-compare (v2 → v3, face shots, same metrics)

Side by side at the same moments: `kit/refs/model-compare_v2_vs_v3.jpg`.

Centre − edge +21 → **+37**, highlight R−B +15 → **+33**, skin chroma 27.3 → **24.5**, black p1 15 → **12**: all
inside the reference range. The freeze check found two static holds (a still screenshot, the reveal); each got a
slow push-in, following the "never a dull moment" rule.

## Standard from 2026-10-01: HyperFrames builds and renders, our kit does the footage

- **Cut-out:** `python3 kit/look/cutout.py <clip> <out.webm> [--from= --to=]`. It extracts frames, masks and grades them into one transparent VP9 WebM, and deletes its temporary files. That's ~70–85 MB per minute kept, instead of ~1.2 GB per minute for per-frame PNGs. The WebM keeps source timing: cut it in the composition with `data-media-start`, `data-duration` and `data-playback-rate`.
- **Build and render:** a HyperFrames composition (reference: `films/model-compare-hf`). Use `npx hyperframes lint` and `snapshot` before rendering, and set `"version": 1` on audio automation.
- **After rendering:** master to −14 LUFS / −1.5 dBTP (the engine has no loudness target), then run the black/freeze and loudness checks.
