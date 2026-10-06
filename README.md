# ChilledBeer Video Edits

A local video editor driven by Claude Code. Give it a talking-head recording and it gives back a posting-ready video:
a captioned 9:16 short or reel, or a 16:9 YouTube long-form with motion graphics. Everything runs on your Mac: no
cloud editor, no paid renderer.

## What it does

- **Hear:** whisper.cpp transcribes, keeping fillers. A wav2vec2 aligner and the audio envelope give word times accurate to about 30 ms. Hindi is written as romanised Hinglish.
- **Look:** ffmpeg, OpenCV and Apple Vision find the face, blur and shot changes. Claude reads timecoded contact sheets.
- **Decide:** the editing questions (false starts, fillers, pauses, retakes, zoom-ins) are answered by Claude. Cuts land only in silence, and a checker refuses any edit that chops a sentence or splices two half-sentences.
- **Graphics:** a library of 49 animated templates for shorts (`kit/graphics/`), plus a HyperFrames component kit for long-form (`kit/hf/`): a speaker camera with a director, diagrams, screen demos, code, kinetic type with springs, sketch and collage styles, a stick-figure rig.
- **Look and sound:** a face-aware colour grade, the speaker cut out for words-behind-head shots, a music and sound-effect library, mastered to −14 LUFS.
- **Check:** the final file is checked for size, frame rate, duration, loudness, true peak, black or frozen picture and cropped sentences, then a fresh Claude critic reviews it.

## Install (macOS, Apple silicon)

You need [Homebrew](https://brew.sh), the Xcode command line tools (`xcode-select --install`), Google Chrome and
[Claude Code](https://claude.com/claude-code). Then:

```bash
git clone https://github.com/DhananjaySarathe/chilledbeer-video-edits.git "chilledbeer-video-edits"
cd "chilledbeer-video-edits"
./setup.sh
```

`setup.sh` is safe to re-run. It:
- installs ffmpeg, whisper.cpp, uv and node with Homebrew, plus the pinned HyperFrames renderer (`HYPERFRAMES_VERSION` in `shorts/config.py`);
- runs `uv sync` and `npm install`;
- downloads the models (~1.2 GB: whisper, the aligner, YuNet, Smart Turn, Silero VAD and the SaT text model) and the fonts;
- builds the Apple Vision tools in `kit/bin`;
- creates `.env` from `.env.example` (only the optional Jev key lives there);
- runs `uv run shorts doctor`, which checks everything and prints tool versions.

Add one line to `~/.zshrc`:

```bash
export HYPERFRAMES_NO_UPDATE_CHECK=1
```

HyperFrames otherwise upgrades itself in the background, even mid-render, which crashes that render and breaks the
pinned version. Claude Code runs in this folder already get it from `.claude/settings.json`. To move to a newer
HyperFrames on purpose, change `HYPERFRAMES_VERSION` and re-run `./setup.sh`.

## Claude Code cloud sessions (Linux)

`cloud-setup.sh` is the Linux counterpart of `setup.sh`. The `SessionStart` hook in `.claude/settings.json` runs it
automatically in cloud sessions (only when `CLAUDE_CODE_REMOTE=true`, so it never fires on a Mac). Leave the cloud
environment's own setup script empty. Its output goes to `/tmp/cloud-setup.log`.

A cloud session can edit code, run the tests and build graphics. Grading, person cut-outs, OCR boxes and full renders
need macOS (Apple Vision, Chrome in `/Applications`), so they stay on the Mac. The speech and face models are skipped by
default. Run `CLOUD_MODELS=1 ./cloud-setup.sh` to download them (needs Full network access). Cloud sessions clone
from GitHub, so a push is all it takes to update them.

## Use

Open this folder in Claude Code and ask, for example:

> Make a short from ~/Downloads/take.mp4

> Edit ~/Movies/talk.mov into a YouTube video with graphics, preset paper studio

The `video-shorts` skill (`.claude/skills/video-shorts/SKILL.md`) runs the whole pipeline, shows you a brief and a
preview, and asks before the final render. The finished files land in `output/final/<video>/`.

The fast path for one vertical take, by hand:

```bash
uv run shorts probe ~/Downloads/take.mp4 --job take1
uv run shorts analyze take1
uv run shorts init-brief take1      # then fill in output/jobs/take1/brief.json and style.json
uv run shorts decide take1          # then answer what is pending in output/jobs/take1/resolutions.json
uv run shorts plan take1
uv run shorts direct take1          # beats (+ Jev's draft picks, if you have a key); then write output/jobs/take1/visuals.json
uv run shorts preview take1         # output/temp/jobs/take1/preview.mp4
uv run shorts render take1          # output/final/take1/final.mp4
uv run shorts check take1
```

Long-form films (HyperFrames compositions) follow `kit/presets/paper_studio/README.md` and `kit/hf/README.md`.

## Jev is optional

Jev (TypeSafe System One) is a fast external model the `shorts` CLI can ask two kinds of question.
It needs a `TYPESAFE_API_KEY` in `.env`. Without a key everything still works:

| Job | With a Jev key | Without one |
|---|---|---|
| Zoom-ins (`shorts decide`): which sentences get a punch-in | Jev answers in about half a second and its picks are applied | the `punch_in:*` questions join Claude's pending list, and Claude picks them with the cut questions (about one sentence in three: hooks, claims, results) |
| Graphics draft (`shorts direct`): a template per beat, English takes only | Jev drafts a pick per beat with confidences; Claude reviews and overrules | Claude directs from the beats alone (the same path Hinglish takes always use) |
| Cuts, fillers, pauses, retakes, captions, long-form films | Claude | Claude (Jev never decided these: measured over three videos it was confident on 8 of 102 cut questions) |

So a key buys speed and a first draft; leaving it out costs a few more questions for Claude to answer. `uv run shorts
doctor` reports the key as optional, and `decide` says `"jev": "off"` when it isn't set.

## Where files go

Everything the pipeline generates lands in `output/` (git-ignored), never in `films/` or `kit/`:

| Folder | What | Keep? |
|---|---|---|
| `output/final/<video>/` | the video(s) to upload, `captions.srt`, posting notes, the final contact sheet | yes |
| `output/jobs/<take>/` | one recorded take: `source.mp4` (the footage copy), `analysis.json` (transcript), the edit decisions (brief, style, resolutions, edit, visuals) | while you might re-edit it |
| `output/music_usage.json` | which track each video used, so the next videos don't repeat it | yes |
| `output/temp/` | everything else: audio extracts, whisper output, face tracks, graphics frames, previews, cut A-roll, grades, mixes, raw renders, snapshots, one-off scripts, caches | **delete any time** |

```bash
uv run shorts clean --dry-run   # what would go, and how big it is
uv run shorts clean             # delete all of output/temp
uv run shorts clean take1       # only one take's (or film's) temp files
```

Deleting `output/temp` loses nothing you need: re-running a step rebuilds what it made. `films/<video>/` keeps only a
film's recipe (edl.py, build.py, the template, edl.json and its screenshots). Film scripts find every folder through
`kit/paths.py` (`F = Film(__file__)`); run them with `uv run python`.

## Make it yours

The repo ships its author's look and identity in a few places. Change these before your first long-form video:

- **Name and handle** in the long-form preset: the lower third and end card in `kit/presets/paper_studio/templates/longform.html` and `templates/reel.html`, and the showcase (`kit/hf/showcase/src/template.html`).
- **Design tokens** (palette, fonts, motion): `kit/presets/paper_studio/preset.json` and `kit/hf/paper.css`.
- **Your films** go in `films/<video>/` (copy `kit/presets/paper_studio/example/`), one folder per video.

Claude Code builds up its own memory of your preferences as you edit.

## Music and sound effects

The audio files are not in this repository: their licences (NCS, Mixkit and others) don't allow passing them on.
`./setup.sh` downloads each track from its source (`kit/assets_src/fetch.py`, listed in `kit/music/library.json` and
`kit/sfx/library.json`; about 10 minutes the first time); a few tracks have no public download and are simply skipped. Credits are in
`kit/music/CREDITS.md`: paste the block into your video description when a track asks for one. Add your own tracks to
`kit/music/<mood>/` and `kit/music/library.json`.

## Tests

```bash
uv run pytest            # unit and slow media tests (live Jev tests are off)
uv run pytest kit/cut    # the cut checker's unit tests
uv run pytest -m live    # also call the real Jev API (needs a key)
```

## Graphics library

```bash
uv run shorts library              # list templates
uv run shorts library check        # render every template's example in parallel + checks
uv run shorts library sheet        # one image with every preview
```

How to write a template: `docs/graphics.md`.
