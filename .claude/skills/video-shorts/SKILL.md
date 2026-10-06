---
name: video-shorts
description: Edit talking-head footage into posting-quality video, either a 9:16 short/reel or a 16:9 YouTube long-form with motion graphics, using the local toolkit (whisper.cpp, Apple Vision cut-outs and grade, HyperFrames compositions, an HTML graphics library, ffmpeg, severity-graded QA plus a fresh critic). Use when the user gives a video file and asks for a short, a reel, a long-form edit, a clean cut, captions, graphics, or removing fillers and pauses.
---

## Read first, every edit

- `kit/refs/REFERENCE.md`: what top channels measurably do (look, captions, layouts) and the current standard: HyperFrames builds and renders, our kit does the footage.
- `kit/refs/EDITING.md`: the playbook, with stage gates, cutting rules, pacing, hooks, captions and safe zones, motion rules, sound levels, QA, the critic and the fix loop. Follow it; its numbers are the defaults.

## Presets (named, approved styles)

When the user names a preset ("preset_paper_studio", "paper studio", "the how-i-edit style"), read `kit/presets/<name>/README.md` first and follow it end to end. It has the pipeline commands, the look, the design tokens (`preset.json`), the templates (`templates/`) and a worked example (`example/`). The index is `kit/presets/README.md`. For a new talking-head long-form with no preset named, offer `preset_paper_studio` as the default.

**Scene components and planning** (`kit/hf/`, README there): for long-form, plan scenes from meaning with `kit/refs/SCENES.md`, then write `visual_plan.json` and check it with `python3 kit/hf/plan_check.py`. Then build the composition from kit components:
- the speaker camera, side cards, inserts and windows;
- the living diagram;
- annotated screen demos on real recordings (find coordinates with `kit/hf/tools/locate.py`);
- code and terminal walkthroughs, compare, chat, lower third, chapters and the end card.

`showcase/` is the worked example. Inline the kit with `kit/hf/vendor.py`, and mux audio with `-aac_pns 0`.

**Stickman moments** (`kit/stickman/`, README there): an ink stick-figure rig for 2 to 4 short moments per video (a metaphor, an emotional beat, a process acted out, a role), never a whole video. Pick the moments in the beat sheet and say which lines they illustrate.

## Version 7 defaults (2026-10-05): every new edit uses these

The owner's rules behind them:
- never cut a sentence midway or splice half-sentences;
- the grade, camera motion and animation must look premium;
- old videos are not re-edited.

Read `kit/refs/EDITING.md` §9 for the details.
1. **Cuts are sentence-safe by construction.**
   - Build the boundary map after the transcript: `uv run python -m kit.cut.sentmap <job>`.
   - Pick keep ranges with `kit/cut/boundaries.py` (`snap`; `restart_cut` on a retake).
   - Gate the edit list with `uv run python -m kit.cut.cutcheck <edl.json> --sources=...`:
     - exit 3 means a chopped or spliced sentence, so fix it;
     - REVIEW items are judged by you, with the text either side;
     - re-run with `--media=<final.mp4>` next to qa.py.
2. **Grade with look v2:** `kit/look/grade.py --v2`.
   - Make the face track with `kit/look/faces.py`, not the mask track.
   - Check with `kit/look/scopes.py qa`.
   - Use `--reel` for 9:16.
   - Face brightness is set halfway between the colourist target and the old engine; that's the owner's choice.
3. **Camera from the director** (`kit/hf/motion.js` + `kit/motion/camera.py`):
   - `camera.plan(...)` with a per-frame face track and tags (`punch`, `joke`, `story`, `section`);
   - `camera.bake(...)` for the motion-blurred moves;
   - in the template, `HF.camera(K, st, {plan: D.camera})`.
   - Reframes come only at new thoughts and are held for the whole thought. Never use A/B framing on every cut. Budgets are in kit/hf/README "v7 camera".
4. **Hand-made styles** (kit/hf/README "v7 styles"): `HF.sketch` (diagrams), `HF.annotate` (marker notes on screenshots/code), `HF.scribble` (outline around the speaker; build it with `kit/hf/tools/scribble.py`), `HF.collage` (paper cut-out).
   - Use 2–3 of these per video, one per passage, never two on the same frame. They come on top of the stickman's 2–4 moments.
5. **Every Reel gets a hook designed for it** (EDITING.md §4). There is no fixed template.
   - In the brief, write 3 candidate openings and score them. Show the user the pick and the reason.
   - Voice and face from frame 0; the number or proof on screen by ~3 s; one text line of 5 words or fewer, inside y 270–1250.
   - Then a purpose beat of at most ~2.5 s that adds the proof or the map of what's compared, never a repeat of the hook. End on the verdict line.
   - Before a shoot, suggest 2–3 hook lines for the user to say to camera with the number in them.

## Version 8 motion (2026-10-07): new reels and films

For new edits (not old videos, and not inside preset_paper_studio's calm look unless the user asks), animate with
`kit/hf/kinetic.js` (kit/hf/README "v8 motion"):
- motion tokens `HF.E.*` instead of stock eases, and springs from `HF.SPRING` (bounce only for things with momentum);
- `HF.land` / `HF.leave` for cards and panels (several properties with offsets, exits shorter than entrances);
- `HF.kinetic` for on-screen text, timed to the spoken words (`from`/`to` word ids), the stressed words boxed;
- a sound on every landing, one frame early (`sfx` options), never late.

## Premium edits and long-form (the current standard)

For long-form 16:9, for reels built from several takes, and whenever the user wants top-creator quality:
1. Ingest and glossary-fix the transcript (`shorts probe --landscape` and `shorts analyze` for the word timings), then write the brief and beat sheet, show them to the user, and score the scene plan's slideshow risk (EDITING.md §1, §8).
2. Cut-outs: `python3 kit/look/cutout.py <clip> <out.webm> [--from= --to=]` produces one transparent graded WebM (about 70–85 MB/min); its temporary files are deleted automatically.
3. Build a HyperFrames composition. `kit/presets/paper_studio/example/` (with its `templates/`) and `kit/hf/showcase/src/template.html` are the worked examples. For a studio look: the cut-out goes on a studio backdrop, heroes sit behind the head, captions use the highlight style, and shader transitions are saved for 1–2 hero moments.
   - Run `npx hyperframes lint`, then `npx hyperframes snapshot` and look at the frames.
   - Render with `npx hyperframes render --quality delivery`, then master to −14 LUFS (`build.py --master` shows how).
4. QA: `python3 kit/qa/qa.py <video> --cuts=<cuts.json> --expect-duration=<s> --expect-size=WxH [--allow-freeze=a-b]`. Exit 3 is FAIL, so fix and re-render; never deliver it. `python3 kit/qa/sheet.py <video> <dir> --cuts=...` makes the review sheets.
5. Critic: follow `kit/qa/CRITIC.md`. A fresh agent judges only the render and the brief, and the findings go into `review/ledger.md`. Only whitelist fixes may be made without asking, with at most 3 rounds.
6. Deliver the video, `captions.srt` (long-form keeps captions off the picture) and the posting notes, and list any open items.

The `shorts` CLI workflow below is still the fast path for a single vertical take.

# ChilledBeer Video Edits

The toolkit lives in the repository root (the folder Claude Code is opened in). Run every command from there as `uv run shorts …`.
- **Output:** every command prints one JSON object. Read it before the next step.
- **Errors:** they arrive as `{"error": {"code", "message", "fix"}}`. Follow the `fix`.
- **Status:** `uv run shorts status <job>` shows which steps are done.

## Where files go (2026-10-07: the user asked for zero clean-up between videos)

- Everything generated goes under `output/` (`kit/paths.py`, `shorts/config.py`). Nothing generated is written into `films/`, `kit/` or the repo root.
  - `output/final/<video>/`: what the user uploads (video, reel, `captions.srt`, posting notes, contact sheet).
  - `output/jobs/<take>/`: the footage copy (`source.mp4`), `analysis.json` and the edit decisions (brief, style, resolutions, edit, visuals).
  - `output/music_usage.json`: the music history (`shorts music` ranks recently used tracks lower).
  - `output/temp/`: everything else, deletable any time: `jobs/<take>/` (audio, whisper, face tracks, gfx frames, `contact.png`, `preview.mp4`, `preview_strip.png`, `sentmap.json`, logs), `films/<video>/` (`work/`, `hf/` = the HyperFrames project, `renders/`, `scratch/`), `cache/`.
- A film's scripts start with `F = Film(__file__)` (`kit/paths.py`) and write to `F.work`, `F.hf`, `F.renders`, `F.final`; `F.stage()` copies the film's own `assets/` and `hyperframes.json` into `F.hf`. Run HyperFrames on that folder: `npx hyperframes lint|snapshot|render <F.hf> ...`. Run film scripts with `uv run python`.
- `films/<video>/` holds only the recipe: `edl.py`, `build.py`, `src/template.html`, `visual_plan.json`, `edl.json`/`cuts.json`, and source screenshots in `assets/`. One-off fix or experiment scripts go in `F.scratch`, never in `films/`. Private raw screenshots go in `F.work`; only blurred copies go in `assets/`.
- `uv run shorts clean` empties `output/temp` (`--dry-run` lists it, a take or film name limits it). Never delete `output/final` or `output/jobs` without the user asking.
- Takes made before this layout stay in `jobs/<take>/` (old one-folder layout) and are found automatically.

## Workflow

1. **Probe:** `uv run shorts probe "<video path>" --job <name>`.
   - Job names use lowercase letters, digits, `-` and `_`.
   - Landscape and silent clips are refused. HDR, VFR, rotated and odd-sized clips are normalised automatically.
2. **Analyze:** `uv run shorts analyze <name>`.
   - It prints the sentences with ids and times, the fillers heard, loudness, face presence and warnings.
   - Read `output/temp/jobs/<name>/contact.png` (20 timecoded frames) to see the video.
3. **Brief and style:** run `uv run shorts init-brief <name>`, then fill in both files (`uv run shorts schema brief|style` shows every field).
   - `brief.json`:
     - `topic`: one line on what the video is about;
     - `target`: `min` and `max` length in seconds;
     - `visual_notes`: what you saw, for example "looks away 0:12–0:14";
     - `caption_overrides`: word index → caption text. Word indices are in `analysis.json`. Fix misheard names.
       Hindi speech is transcribed as romanized Hinglish automatically (`language: "hinglish"`); its spellings are rough,
       so respell every word into standard Hinglish ("bhout" → "bahut"). An override may hold several words when
       Whisper merged them ("increase ho gaya hai"); `""` hides a word. Graphics direction reads the overrides too.
     - `cut_words`: inclusive `[first, last]` word ranges to cut, for flubs the questions don't cover, such as a restart inside a sentence ("it's all, uh, basically we, I wanna…" → cut "it's all, uh, basically we,"). Cuts still need a clean cut point, or `plan` keeps the words and says so.
   - `style.json`: design the look for this video: template, font, colours, size, words per page, position and zoom strength.
     - Fonts in `kit/fonts`: Montserrat 800/900, Poppins 600/700/800, Anton, Oswald 500/600/700, Inter 400–800, Bebas Neue, DM Sans 700, JetBrains Mono, Caveat.
     - Keep captions readable: high contrast, and an outline on busy backgrounds.
4. **Decide:** `uv run shorts decide <name>`.
   - Jev (optional, needs `TYPESAFE_API_KEY`) picks the zoom-in (punch-in) moments in about half a second; without the key the `punch_in:*` questions come to you too (`"jev": "off"`): say yes to hooks, surprising claims, the main point and results, about one in three sentences. Every cut question (false starts, fillers, pauses, retakes) comes to you: the questions read the caption overrides, so Hinglish arrives respelt.
   - Every item under `pending` is yours. Read the question and the sentence context, then decide.
   - Write `output/jobs/<name>/resolutions.json` as `{"<id>": true|false|"<sentence id>"}`.
   - Removing content needs a clear reason. If you are still unsure, keep it (answer `false`) and list the item for the user next to the preview.
5. **Plan:** `uv run shorts plan <name>`.
   - Read `removed`, `kept_back` (removals refused because there was no clean cut point) and `warnings`.
   - Fix what you can in brief, style or resolutions, and plan again.
6. **Direct (graphics):** `uv run shorts direct <name>`.
   - The edit is split into beats of 1–3.5 s (`visuals_draft.json`). For English takes with a Jev key, Jev drafts a visual per beat (`speaker`, a template or `new`) with confidences. Without a key, and for Hinglish and other takes, it is skipped, because its picks weren't useful there, and you direct from the beats. `--jev` or `--no-jev` overrides this.
   - Write `output/jobs/<name>/visuals.json` (`uv run shorts schema visuals`). Each scene is `{id, template, start, end, params}`, with times on the edited timeline, usually a beat's start and end.
   - Fill the params with short, concrete words that show exactly what is being said: file names, chat lines, numbers, titles.
   - Treat Jev's picks as a draft and overrule weak ones. Keep roughly a third of the time on the speaker. Never use the same template twice in a row.
   - Overlays (`chapter_pill`, `camera_ui`, `feature_tabs`…) may span several beats, on top of other scenes.
   - For a `new` pick, write a template in `kit/graphics/<id>/` by following `docs/graphics.md`. Run `uv run shorts library check <id>`, look at `kit/graphics/_previews/<id>.png`, then use it. It stays in the library for next time.
   - **Per-video look:** set `visuals.theme`, e.g. `{"accent": "#FC3B00"}` for the brand colour. `captions: "box"` gives the reference caption style.
   - **Direct like an editor, not a template-filler:**
     - one graphic per story beat, about every 3-5 s; don't reuse a template back to back or too often;
     - keep the face on screen for funny or honest lines: `speaker_window` (morphs in and out of full frame; bubbles for quoted dialogue, a headline otherwise) and overlays;
     - full-screen graphics suit explanations (the punchline visual, numbers);
     - `wipe_transition` centred on a cut marks a topic change (at most one or two per video).
   - **Music:** pick from the library, not the same track every time: `uv run shorts music <name> --mood <mood> [--hit "<word>"]`.
     - Moods: chill, upbeat, tech, hype, emotional, suspense, funny, cinematic. Set `style.music_mood` for the default.
     - `--hit` lines the track's strongest drop up with that word (the key line or twist). Without it the track starts on its first loud bar.
     - Tracks used by the last 4 jobs rank lower. `--apply N` writes pick N into `visuals.music` and logs it; keep `enter`/`drops` edits after.
     - Put the pick's `credit` in the posting copy when it isn't "none required" (all credits: `kit/music/CREDITS.md`).
     - Defaults sit about 12 dB under the voice and duck while talking. Sound effects beyond the built-in ones live in `kit/sfx/<category>/` (see `kit/sfx/library.json`).
   - The planner already cuts pauses naturally and adds zoom cuts in long takes. Graphics snap to cuts within 0.2 s.
   - `uv run shorts library` lists every template with its description.
7. **Preview:** `uv run shorts preview <name>`.
   - It renders any changed graphics first (in parallel and cached, so only scenes you changed re-render), then composites everything.
   - Read `output/temp/jobs/<name>/preview_strip.png` and the `cuts` list, then send `output/temp/jobs/<name>/preview.mp4` to the user and ask for notes.
   - Turn notes into brief, style, resolutions or visuals changes, then run plan (if cuts changed) and preview again.
8. **Render:** only after the user approves the preview. Run `uv run shorts render <name>`, then `uv run shorts check <name>`.
   - Exit code 3 means a check failed. Read which one, fix it, and render again.
   - Never deliver a file that failed `check`.
9. **Deliver:** send `output/final/<name>/final.mp4` and mention `final_contact.png` next to it.

## Rules

- Never print, echo or commit `.env` (it may hold the Jev key).
- **Captions:** they show only the speaker's words (with overrides).
- **Graphics text is on-screen copy.**
  - Keep it human and specific, not generic filler.
  - Never invent numbers or results the speaker didn't say (views, money, time saved).
  - No real brand names or logos in mockups unless the speaker names them; use generic app names.
  - Mockups use generic app names, no real logos.
- **Speed matters:**
  - `analyze` ≈ 10 s, `preview` ≤ 10 s and `render` ≤ 20 s for a one-minute take;
  - `output/jobs/<name>/timings.json` shows where time went;
  - don't re-run steps whose inputs did not change.
