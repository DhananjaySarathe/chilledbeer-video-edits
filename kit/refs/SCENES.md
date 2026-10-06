# Choosing scenes from meaning

Read this after the beat sheet and before writing the composition. Every passage of the script gets a visual that **helps the viewer understand it**, not one that looks busy. Pick by what the passage *does*, not by the words in it.

The plan is written as `visual_plan.json` and checked with `python3 kit/hf/plan_check.py visual_plan.json` before anything is built. The format and a filled example are in §5.

## 1. Two separate choices

1. **The explanation type**: what the passage does for the viewer (the table below). This picks the technique.
2. **The treatment**: how it looks. This is fixed by the preset (`preset_paper_studio`: clean vector, ink on paper, one orange accent, plus stickman accents). Change it per video, never per scene. A scene in a different style breaks the film.

## 2. Explanation types → technique

| Type | You hear… | Best technique (registry id) | Alternative (trade-off) | Fallback | Don't |
|---|---|---|---|---|---|
| **process** | steps, "first… then…", a workflow | `diagram` (living: reveal → focus the current step → tick done) | `flow_steps` / checklist (simpler, less spatial) | side `words` | a new diagram for every step |
| **comparison** | X vs Y, before/after, old way/new way | `compare` (aligned rows, verdict) | `before_after`, `split_screen` (one image per side) | two `card`s | unaligned lists |
| **quantity** | a number, growth, share | big number (`countUp` in `words`) or `stat_chart` | `people_grid` pictogram (concrete, slower) | `pill` with the number | invented or rounded-up numbers |
| **relationship** | connected parts, "talks to", data moving | `diagram` (shape `card`, edges, `flow` dots) | `stickman` roles (warmer, less exact) | `diagram` row | more than ~7 nodes on screen |
| **mechanism** | how it works inside, "under the hood" | `diagram` focus + `flow`, or `code` focus | cutaway (special case, expensive) | `card` with 3 parts | decoration without the actual parts |
| **story** | a problem, a consequence, a feeling | `stickman` moment (2–5 s) | `speaker` + side `words` (keeps the face) | `words` | stickman for facts or numbers |
| **analogy** | "it's like a…", library, factory, queue | `stickman` + props, mapped part by part | `diagram` with labelled metaphor nodes | `words` naming both sides | an analogy that isn't mapped back to the real thing |
| **chronology** | days, versions, history | `diagram` row with dates (layout row) | `calendar_page` / `streak_days` | `chapter` tags | a timeline with one event |
| **instruction** | "click", "go to", "type", a product step | `screen` (real recording: zoom, highlight, cursor) | `win` screenshot + scroll (no motion inside) | `card` with the step | a mock UI when the real screen exists |
| **code** | a function, a config, a command | `code` (highlight, diff) / `terminal` (real output) | `card` with the line | `pill` with the file name | more than ~10 visible lines; fake output |
| **conversation** | "I asked it…", it replied | `chat` | `ai_chat` (shorts) | `card` with the prompt | brand logos in mock UIs |
| **definition** | "X is…", naming a term | side `words` (2–4 words, serif) | `card` with one line | `pill` | the whole sentence on screen |
| **emphasis** | the punchline, a strong claim | side `words` or `C` framing (close) | `title_behind` (shorts) | nothing: the face | more than one per ~20 s |
| **proof** | "here it is", "you can see" | `screen` / `win` / `phone` (the real thing) | `card` with a quote | `pill` | a claim with no real artefact |
| **structure** | intro, chapters, recap, transitions | `lowerThird`, `chapter`, `diagram` recap (`show()` again) | `section_card` (shorts) | — | a title card before the speaker |
| **ask** | subscribe, comment, link | comment card, `endCard` | `comment_reply` (shorts) | `pill` | asking before giving value |

When in doubt: **process → diagram, comparison → compare, human problem → stickman, product step → real screen, number → accurate number, connected system → diagram with flow, term → restrained words.**

## 3. Rules

- **The visual adds what the narration can't**: structure, the real screen, the exact number, the relation between things. Words on screen are 2–4 key words, never the sentence being said.
- **One diagram per idea, developing across passages.** Reveal it, focus the step being discussed, tick steps done, and come back to it for the recap (`diagram.show()` again; its state carries over).
- **Vary scenes only when it serves the explanation.** The same technique 3 passages in a row is a warning, unless it's the same developing diagram.
- **The face stays the anchor**: at least a third of the talking time is the speaker (full or side layouts). The corner window keeps the face during inserts.
- **Real data only**: numbers, star counts, render times and outputs come from real pages and real runs. No invented statistics.
- **Readable on a phone**: body ≥ 26 px and labels ≥ 20 px in 16:9 (≥ 34 / 26 px in 9:16), and at most ~10 code lines.
- **Motion carries meaning**: a camera move goes *to* the thing being said. No decorative spins or bounces. Every held shot keeps a slow push (QA flags holds over ~0.6 s).
- **Stickman moments**: 2–4 per video, 2–5 s each, never back to back (`kit/stickman/README.md`).
- **Screen demos**: annotate only while the screen is still. Get coordinates from `kit/hf/tools/locate.py` (text search) or `grid.py`. Blur anything private.
- **Every scene has a fallback**: if the asset isn't there or the ratio is wrong, the fallback keeps the film working.

## 4. Ratios

- **16:9**: side layouts (content beside the speaker), wide diagrams (layout row), compare, screen demos at fit-width.
- **9:16**: top panel graphics with the face panel below (`camera` mode `panel`), diagrams in layout column, screen demos as zoomed crops (zoom into the region; a full desktop is unreadable on a phone), compare as stacked cards.

## 5. The plan (`visual_plan.json`)

```json
{
  "film": "how-ai-editor-reuses-assets", "ratio": "16:9", "preset": "preset_paper_studio", "edl": "edl.json",
  "passages": [
    { "id": "p3", "words": [210, 248], "goal": "See that every video goes through the same five steps",
      "type": "process", "technique": "diagram", "why": "five ordered steps; the diagram returns as the recap",
      "beats": [ { "at": 212, "show": "five nodes reveal left to right" }, { "at": 231, "show": "focus 'Clean up', note 'skill file'" } ],
      "assets": [], "fallback": "flow_steps", "diagram": "workflow" }
  ]
}
```

- `words` are word indices in the cut (from `edl.json`). Use `"t": [a, b]` in seconds instead when there is no EDL yet.
- `beats[].at` is a word index (or a time). `diagram` names a diagram that several passages share (develops, not redrawn).
- Required fields: `id`, `words` or `t`, `goal`, `type`, `technique`, `beats`. `fallback` is required for `screen`, `code`, `terminal`, `diagram` and `stickman`.

A full example: `kit/hf/examples/visual_plan.example.json` (the labelled sample "how an AI video editor reuses assets").

`plan_check.py` checks:
- types and techniques exist, and the technique explains the type;
- the ratio is supported and fallbacks are valid;
- timing is within each component's limits;
- stickman count and length, and no repeated runs;
- assets exist, goals are written, and at most 40 % of passages are words-only.

`--key` prints a cache key covering the plan, the component versions, the kit files, the preset and the output settings.

## 6. Light and look by meaning

The grade is part of the explanation too. Each passage may carry a `look` (kit/look/looks.py). Light changes are motivated by the story, like a cinematographer's lighting cues:

| Look | Use it for | What it does |
|---|---|---|
| `natural` | the default: talking, explaining | the channel's look: cream wall, lit face, gentle contrast |
| `bright` | payoffs, results, good news | lifted, airy, open shadows |
| `cinematic` | hooks, big claims, launch films | film S-curve, darker cool room, warm face, halation, grain |
| `moody` | setbacks, consequences, confessions | the room falls into shadow, the face keeps a warm pool of light |
| `film` | flashbacks, "how it started" | faded blacks, warm highlights, green-cyan shadows, grain |
| `noir` | rare: one dramatic line or quote | black and white, red-filter mix, hard contrast |

**Rules:**
- Most of the video is `natural`. Use at most 2–3 other looks per video, each held for at least 3 s.
- Switch on a cut (a hard change), or as a motivated "lights dim / lights up" moment: a 0.8–1.2 s fade landing on the emotional word. In the plan, set `"look_at": <word index>` (and optionally `"look_fade"`).
- Never flicker between looks passage by passage.
- Verify with `python3 kit/look/scopes.py` or `grade.py --sheet` (numbers):
  - skin hue stays within about ±4° of the source's own skin hue;
  - skin saturation stays 0.09–0.14 (above 0.14 reads orange);
  - blacks are not pinned at 0 (moody ≥ 0.008) and whites are not clipped.

`python3 kit/look/looks.py switches visual_plan.json edl.json looks.json` turns the plan's looks into `grade.py --looks=looks.json`.

