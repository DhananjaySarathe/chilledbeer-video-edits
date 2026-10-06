# ChilledBeer Video Edits

**Drop in a talking-head recording, get back a video ready to post.** A local editor driven by
[Claude Code](https://claude.com/claude-code): it cuts the pauses and fillers without ever chopping a sentence, adds
word-by-word captions, motion graphics, music and a colour grade, then checks the result before you see it. It makes
9:16 shorts and reels, and 16:9 YouTube videos. Everything runs on your Mac: no cloud editor, no paid renderer.

## Quick start

On a Mac with Apple silicon:

```bash
xcode-select --install                                      # once, if you don't have the command line tools yet
git clone https://github.com/DhananjaySarathe/chilledbeer-video-edits.git "chilledbeer-video-edits"
cd "chilledbeer-video-edits"
./setup.sh                                                  # about 20-30 min the first time: mostly downloads
echo 'export HYPERFRAMES_NO_UPDATE_CHECK=1' >> ~/.zshrc     # keeps the video renderer on its tested version
claude                                                      # opens Claude Code in this folder
```

Then ask Claude: *"Make a short from ~/Downloads/take.mp4"*. It shows you a brief and a preview, asks before the final
render, and puts the finished video in `output/final/<video>/`.

## What gets installed

**Install these yourself first** (`setup.sh` checks for them):

| What | Why it's needed | Where it goes | How to install | Size |
|---|---|---|---|---|
| Homebrew | installs the tools below | `/opt/homebrew` | the one-line command on [brew.sh](https://brew.sh) | varies |
| Xcode Command Line Tools | builds the two Apple Vision tools | `/Library/Developer/CommandLineTools` | `xcode-select --install` | 1.3 GB |
| Google Chrome | draws the graphics and renders the compositions | `/Applications` | [google.com/chrome](https://www.google.com/chrome/) | 720 MB |
| Claude Code | runs the editing | your user folder | [claude.com/claude-code](https://claude.com/claude-code) | |

**`./setup.sh` installs the rest** (safe to re-run; anything already there is skipped):

| What | Why it's needed | Where it goes | Command it runs | Size |
|---|---|---|---|---|
| ffmpeg | cutting, encoding, loudness, checks | `/opt/homebrew` | `brew install ffmpeg` | 770 MB with its libraries |
| whisper.cpp | speech to text | `/opt/homebrew` | `brew install whisper.cpp` | 6 MB (+150 MB shared libraries) |
| uv, node | run the Python and JavaScript parts | `/opt/homebrew` | `brew install uv node` | 120 MB |
| Python packages (OpenCV, ONNX Runtime, numpy...) | the editor itself | `.venv/` in this folder | `uv sync` | 540 MB |
| Node packages (Chrome driver, GSAP, rough.js) | graphics rendering | `node_modules/` in this folder | `npm install` | 60 MB |
| HyperFrames 0.8.134 | renders long-form compositions | the global npm folder | `npm install -g hyperframes@0.8.134` | 120 MB |
| Whisper large-v3-turbo (q5) | transcription | `kit/models/` | `uv run shorts setup` | 574 MB |
| SaT sentence model + tokenizer | finds sentence ends, so no cut lands mid-sentence | `kit/models/hf/` | `uv run shorts setup` | 421 MB |
| wav2vec2 aligner (int8) | word timings to about 30 ms | `kit/models/` | `uv run shorts setup` | 95 MB |
| Smart Turn, Silero VAD, YuNet | end of a thought, speech vs pause, face detection | `kit/models/` | `uv run shorts setup` | 11 MB |
| Apple Vision tools | person cut-outs, text on screen | `kit/bin/` | built by `uv run shorts setup` | under 1 MB |
| Music and sound effects | background tracks and hits | `kit/music/`, `kit/sfx/` | `uv run python kit/assets_src/fetch.py` | 240 MB |

In total: about **1.9 GB inside this folder**, plus up to about **3 GB of system tools** if you have none of them yet,
plus room for your footage and renders in `output/`. `uv run shorts doctor` checks that everything is in place. The
fonts (3.5 MB) come with the repo.

## What it does

- **Hear:** whisper.cpp transcribes, keeping fillers. A wav2vec2 aligner and the audio envelope give word times accurate to about 30 ms. Hindi is written as romanised Hinglish.
- **Look:** ffmpeg, OpenCV and Apple Vision find the face, blur and shot changes. Claude reads timecoded contact sheets.
- **Decide:** the editing questions (false starts, fillers, pauses, retakes, zoom-ins) are answered by Claude. Cuts land only in silence, and a checker refuses any edit that chops a sentence or splices two half-sentences.
- **Graphics:** a library of 49 animated templates for shorts (`kit/graphics/`), plus a HyperFrames component kit for long-form (`kit/hf/`): a speaker camera with a director, diagrams, screen demos, code, kinetic type with springs, sketch and collage styles, a stick-figure rig.
- **Look and sound:** a face-aware colour grade, the speaker cut out for words-behind-head shots, a music and sound-effect library, mastered to −14 LUFS.
- **Check:** the final file is checked for size, frame rate, duration, loudness, true peak, black or frozen picture and cropped sentences, then a fresh Claude critic reviews it.

Why `HYPERFRAMES_NO_UPDATE_CHECK=1`: HyperFrames otherwise upgrades itself in the background, even mid-render, which
crashes that render and breaks the tested version. Claude Code runs in this folder already get it from
`.claude/settings.json`. To move to a newer HyperFrames on purpose, change `HYPERFRAMES_VERSION` in `shorts/config.py`
and re-run `./setup.sh`.


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

## Licences of what's bundled or downloaded

- **Fonts** (`kit/fonts/`, in the repo): all under the SIL Open Font License 1.1, which allows sharing them with their
  licence; each family's licence text is in `kit/fonts/licenses/`.
- **Models**: not in the repo. `uv run shorts setup` downloads them from their official sources, each under its own
  permissive licence (MIT, Apache-2.0 or BSD).
- **Music and sound effects**: not in the repo (see above). You download them from their sources yourself, and the
  track's own terms apply to your videos: credit NCS tracks as `kit/music/CREDITS.md` shows.
- **Python and npm packages**: installed from PyPI and npm under their own licences.

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
