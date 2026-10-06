# kit/look — grading, light and looks

Everything here is local and free: numpy, OpenCV, ffmpeg, plus Apple Vision for the head track. There's no Resolve and no MCP.

| File | What it does |
|---|---|
| `grade.py` | grades a clip: measured tone targets → a soft key light that follows the face → the look's colour (LUT) → halation, sharpening, grain. `--look=name`, `--looks=switches.json` (looks per scene, with "lights dim" fades), `--sheet=<t>` (one frame in every look, measured), `--test=` (before/after) |
| `looks.py` | the looks (`LOOKS`): `natural` (the channel's look, v2), `bright`, `cinematic`, `moody`, `film`, `noir`, plus `natural_v1` (the old grade). `bake` exports a look as a `.cube`; `match` makes a look from a reference frame (Monge-Kantorovich colour transfer); `switches` turns plan looks into a `--looks` file |
| `scopes.py` | waveform + vectorscope (with the skin-tone line) + the numbers: black and white points, clipping, skin luma, hue and saturation (on the face region), wall level and colour cast. `qa`: the look v2 pass/warn table for any graded clip |
| `v2.py`, `faces.py` | look v2 (`grade.py --v2`, below): per-shot balance from the face, sigmoid tone curve, subtractive saturation, skin secondaries, halation, grain. `faces.py`: YuNet face detection, the skin region scopes read, face tracks |
| `luts/paper_studio_*.cube` | each look's colour stage as a 33³ LUT (works in Resolve, Premiere, ffmpeg `lut3d`). The light stage (tone targets, key light, vignette) is measured per clip and spatial, so it lives in `grade.py`, not in the LUT |
| `looks_demo.mp4` | a 14 s demo: natural → lights dim into moody on "gone" → lights up on "achieved" → a cut to bright on "15–20 minutes" |

## Grading a film

```
python3 kit/look/grade.py <take> <take> --track-only                                  # head track (once per take)
python3 kit/look/looks.py switches visual_plan.json edl.json work/looks.json          # looks from the plan
python3 kit/look/grade.py work/aroll.mp4 work/aroll_graded.mp4 --track=<take>.face.json --map=work/aroll.map.json --looks=work/looks.json
python3 kit/look/grade.py <take> sheet.jpg --sheet=<t> --track=<take>.face.json       # compare looks + numbers before committing
```

## How the looks were tuned (the numbers matter more than the eye)

- **Skin**: the hue is measured on the cheeks and forehead from the head track, not by a skin-colour mask (a mask shifts with the grade, so it lies). Keep the hue within about ±4° of the source's own, and saturation between 0.09 and 0.14. `natural_v1` was 0.149, which read slightly orange; v2 is 0.132.
- **Filmic curves**: AgX (Sobotka, after MrLixm/AgXc) is in `looks.agx()`, but it is made for scene-linear camera data. On phone Rec.709 footage it pins whites near 0.75, so the looks use monotone S-curves on display luminance instead.
- **Teal and orange**: done by tinting only the low-chroma colours (walls, greys) cool, so skin keeps its warmth. Shadow tints alone turned the cream wall yellow-green.
- **The dim room**: the tone targets put the wall near the face's level (moody: wall 0.28, skin 0.40), and the key light keeps the face lit. It's a lamp-lit room, not a darker exposure.

Speed: about 3 fps on the M1 Pro with 8 workers (crossfade frames grade twice).

## Rooms and portrait mode (2026-10-04, films/expensewaale)

The looks' tone targets assume the channel's cream wall. For another room pass a **room profile**:

    python3 kit/look/grade.py cut.mp4 graded.mp4 --track=face.json --room=shelf --matte=<mattes dir> --looks=looks.json

- `--room=<name>` (`looks.ROOMS`): per-look light targets, per-look colour tweaks and the portrait background. `shelf` is
  a bookshelf room whose background (~0.45 luma) is as bright as the face.
- `--matte=<dir>`: person mattes (`kit/bin/personseg <frames> <out> --mask`, files f00001.png…) for **portrait mode**:
  the room is defocused with a normalised masked blur and an eroded matte (no halo), and calmed (`bg.sat`). Darkening
  the room is done with light (tone + key), not the matte: matte-based darkening drew a rim (hard) or an aura (soft).
- With a matte the key light lands on the person (blurred matte weight), not on tan book spines.
- Use a real face track for the key (the mask head track can sit on the hairline): see films/expensewaale/face_track.py.
- Check with scopes on the face box: skin_sat ≤ 0.14, skin_off within a few degrees.

## Look v2 (2026-10-05, opt-in: `--v2`)

The old engine bends display luma with measured tone targets and clamps skin saturation. v2 grades in linear light the
way a colourist's node tree does: per-shot balance from the **face** (YuNet), then one fixed look per look name, then
texture. Same looks, rooms, mattes, `--looks` plans (with "lights dim" crossfades), `--test` and `--sheet`; the old engine
is untouched without `--v2`.

```
python3 kit/look/faces.py <take> <take>.face.json            # YuNet face track (or: grade.py <take> <take> --v2 --track-only)
python3 kit/look/grade.py cut.mp4 graded.mp4 --v2 --track=<take>.face.json --map=cut.map.json --room=shelf --matte=<mattes> --looks=looks.json
python3 kit/look/grade.py cut.mp4 sheet.jpg --v2 --sheet=12.5 --track=... --room=shelf --matte=<mattes>   # every look, v2
python3 kit/look/scopes.py qa graded.mp4 --faces=cut.mp4 --matte=<mattes> --every=1     # pass/warn table (any graded clip)
python3 kit/look/looks.py bake natural out.cube --v2 [--room=shelf]                     # v2 colour as a LUT (Resolve etc.)
```

`--shots=t1,t2` splits the clip into shots (each gets its own balance; default one shot), `--balance=<out>.balance.json`
reuses an earlier balance (written next to every v2 output, like `--levels`), `--reel` is the Reels/Shorts finish.
Files: `v2.py` (the pipeline, `V2` defaults = natural), `faces.py` (YuNet, skin region), per-look `"v2"` dicts in
`looks.LOOKS`, per-room `"v2"` dicts in `looks.ROOMS` (`paper` = the cream-wall studio and the default, `shelf`).

**Order** (per frame; steps 1-4 are solved once per shot from up to 12 sampled frames, ~4 s for a 2 min take):

| # | op | domain | natural defaults |
|---|---|---|---|
| 1 | black trim: soft flare offset `lin²/(lin+f)` so the shot's 0.5th-pct black (with vignette, bg dim, defocus) lands on target | linear | black 0.022, f ≤ 1.5× the source black |
| 2 | white balance from the skin (temperature + tint at constant luminance): half the face's hue error, half its chroma error; the room's bright neutrals keep ≥ 60 % of their cast (85 % in `paper`), so walls never go lilac | linear | hue_k 0.5, chroma_k 0.5 toward 0.25, ±0.35/0.15 stop |
| 3 | exposure: the face's mean Y' through the whole look | linear | skin_y 0.505 (paper 0.55): faces measure ~0.535, halfway between v2's first grade (~0.50) and the old engine (~0.58), the creator's choice (2026-10-05) |
| 4 | skin rotation: what WB left of the hue error, applied in step 9 | — | ≤ ±12° |
| 5 | light: masked defocus of the room, room set back through a heavily feathered (eroded + blurred) matte, room saturation, soft key / far-cheek falloff, elliptical vignette centred on the face | linear | bg −0.5 stop (shelf −0.7, paper 0), bg sat 0.85, feather σ 3.5 % H, key +0.12 / fall −0.08 stop, vignette −0.3 stop |
| 6 | halation (utility-dctls): blur of (R + 0.1G + 0.1B)/1.2, σ 0.3 % W, add R·2⁻³ G·2⁻⁴·⁴ B·2⁻⁵·⁸, gain-normalised | linear | ×0.6 |
| 7 | subtractive saturation `n·(rgb/n)^γ`, n = max | linear | γ 1.15, 40 % of it on skin |
| 8 | tone curve: generalised log-logistic sigmoid (darktable's model, reimplemented), per channel on inset/rotated primaries ("smooth": inset 0.10/0.10/0.15, rotate +2/−1/−3°), grey 0.1845 → 0.1845 | linear → display | contrast 1.4, skew −0.1, white 1.6 |
| 9 | skin: hue compression toward 123° (≤ 5° pull at ~18° off) + shot rotation, soft-knee chroma compressor | Y'CbCr | pull 0.35, σ 25°, knee 0.27, 2:1 |
| 10 | split tone: warm highlights, cool shadows (skin spared, blacks neutral) | Y'CbCr | 1.6 % @ 140°, 1.0 % @ 320° |
| 11 | texture: band-pass local contrast (σ 2 px → 1.5 % H; fine skin texture untouched), fine sharpening; both soft-capped at strong edges (no rim around hair on plain walls), darkening soft-limited to 35 % of the pixel (no crushed gaps) | display | +15 % room/clothes, −6 % skin, sharpen 0.22 |
| 12 | grain: mono, σ 0.7 px at 1080p, × 4Y(1−Y), seeded by frame index, half on skin | display | 0.8 % |
| 13 | dither ±0.5 LSB, quantise | display | on |

`white` is the sigmoid's asymptote in display-linear: darktable's 1.0 suits scene-referred raw, but on phone Rec.709 it
pins source white at ~0.88 and greys a cream wall; 1.6 puts it at ~0.93 with the same mid contrast. Skin weights come
from an adaptive classifier (this shot's own face CbCr) inside the person matte. `--reel`: shadow lift 0.02, half grain,
vignette ×0.6. Per look (`LOOKS[*]["v2"]`): bright (skin 0.55, contrast 1.25, bg −0.25), cinematic (0.47, 1.6, bg −0.8,
halation 1.0, sat 1.22), moody (0.44, 1.55, bg −1.2, sat 0.88, key +0.35), film (0.50, lift 0.05, halation 1.6, grain 1.6 %),
noir (0.51, mono mix 0.42/0.48/0.10, contrast 1.7). Plain room desaturation (moody/film `sat`) reaches skin at only
`sat_skin` 0.3 of its strength, so a calm room never greys the face.

**Targets** (`scopes.py qa`, measured on the YuNet face box: upper cheeks + forehead strip, minus hair/beard and the top
2 %): skin hue 123 ± 4° (shot medians within 2°), skin chroma 2|CbCr| 0.20-0.32, skin Y' 0.40-0.55 with p90 ≤ 0.70,
0.5th-pct Y' 0.01-0.07, clipped blobs < 1 % of the frame, face − room Y' ≥ 0.08, room chroma ≤ skin chroma. In the
cream-wall room the wall is brighter than the face by design (sep fails there; that's the channel's look, not a fault).

**Evaluation** (kit/look/eval, gitignored: `run.py`, `contact_sheet.png`, `contact_faces.png`, `scopes.txt`, `clip/`):
8 frames, both rooms. Shelf room, v2 natural vs the old natural: skin Y' 0.46-0.55 (old 0.54-0.62, hot), skin chroma
0.27-0.28 (old 0.29-0.34), face − room 0.10-0.15 (source ≈ 0), black 0.024-0.036 (source 0.04-0.06, milky). Cream-wall
room: skin hue 124-126° (source 132-133°, old 134-136°), chroma 0.27-0.29 (old 0.38-0.39, orange). Shot-to-shot drift of
the skin hue 2.1° (source 10.7°, old 11.6°); hue variation inside the face kept at ~75 % of the source's (no plastic
skin). In motion (10 s, `clip/compare_source_old_v2.mp4`): no added flicker (room luma moves 0.34 LSB frame to frame vs 0.32 in
the source). Banding: after x264 the ±0.5 LSB dither alone barely survives; the grain is what breaks up contours in dim
gradients, so keep grain on for long-form.

Speed (1080p, M1 Pro, 8 workers, shared machine): v2 ~0.25 s per frame in one process (old ~0.30-0.45), 9 fps for the
10 s clip vs 4.4 fps for the old engine with the same pool (frames now stream through a bounded window, so decode,
grade and encode overlap; one OpenCV thread per worker).
