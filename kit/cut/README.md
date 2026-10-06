# kit/cut: sentence-safe cutting

The creator's rule: trim freely (pauses, fillers, retakes, tangents), but every kept piece starts at a sentence or
thought start and ends at a completed thought. Never splice half of one sentence onto half of another. On a restart,
cut back to the end of the previous complete sentence. Removing a filler or a repetition inside one sentence ("your, uh,
your" -> "your") and dropping a self-correction are fine when the result reads as one fluent sentence. A pause trimmed
inside a sentence must leave a natural gap.

This package does three jobs:

1. **Map** every word gap of a take: how likely a sentence ends there (`sentmap.py`).
2. **Check** an edit's joins against that map, with an optional re-listen of the exported audio. It exits 3 on a FAIL, like `kit/qa/qa.py` (`cutcheck.py`).
3. **Snap** a wanted keep range to whole sentences, so editors cut correctly from the start (`boundaries.py`).

## Commands

```bash
uv run python -m kit.cut.sentmap ew1 ew2            # -> output/temp/jobs/<job>/sentmap.json (cached; --force rebuilds)
uv run python -m kit.cut.cutcheck films/expensewaale/reel/edl.json --sources=ew1=0,ew2=2000 \
       --media=films/expensewaale/reel/short_expensewaale_effort_levels.mp4 --json=report.json [--quiet]
uv run python -m kit.cut.boundaries ew2 2103 2141 --base=2000        # snap a keep range to whole sentences
uv run python -m kit.cut.boundaries ew2 2357 --restart --base=2000   # where to cut back to on a restart
uv run python -m kit.cut.boundaries ew1 --sentences --from=360 --to=420
uv run python -m kit.cut.evaluate [--media]          # the ExpenseWaale fixture score -> kit/cut/eval/
uv run python -m kit.cut.calibrate [--fit]           # the boundary model on the hand-labelled gaps
uv run pytest kit/cut -q                             # fast unit tests (no models)
```

The scripts also run by path: `uv run python kit/cut/cutcheck.py ...`.

`cutcheck` exit codes: **0** PASS, **2** WARN (REVIEW items or tight pauses are listed for the editor), **3** FAIL.
`--sources` maps edit word ids to takes: `id = base + word index`. Ids at or above `--wrap` (default 10000) are copies
of a word that appears twice in the edit, such as a cold open. Any edit with `words: [{i, text, t, e}]` works, and so
does a plain list of kept ranges (see Integration).

## How a join is judged

Consecutive output words are one of three kinds:

| kind | what | rule |
|---|---|---|
| continuous | the next word of the same take | If the edit shortened the pause there, it is a **pause trim**. With `--media`, the gap the viewer hears must be at least 0.12 s inside a sentence (WARN below that). Under 0.06 s the words run together: FAIL inside a sentence, WARN between two sentences. |
| repair | a short forward skip (25 words or fewer) that drops only fillers, or a restart: the right piece repeats the words that followed the left piece ("it took me a new check, it took me a proper plan"), or the words before the right piece repeat the left piece's tail ("...max effort, sorry, not ultracode, ..., when I used the max effort, because") | PASS, then confirmed by the re-listen |
| cut | anything else: content dropped, another take, a reorder | see below |

For a **cut**, `p_end` is the boundary strength after the left piece's last word and `p_start` is the boundary strength
before the right piece's first word. An edit may drop up to 3 openers before the right piece ("So,", "and", "basically")
or up to 2 tags after the left piece (", right?"); the boundary is then read past them. The checks run in this order:

1. **FAIL (lexicon).** The left piece ends on a connector, article or preposition (and, but, because, the, of, to,
   which, it's, my, aur, lekin, kyunki, jo, matlab...). Or the right piece starts on a postposition, auxiliary or
   relative (ki, ke, ka, ko, se, mein, hai, tha, wala, which, of, than).
2. **PASS.** Both sides are sentence boundaries (`p >= P_SENT = 0.5`).
3. **Inside one sentence.** If neither side, nor any gap inside the dropped stretch, is a sentence boundary, the cut
   dropped an aside:
   - **REVIEW** if the aside is a subordinate clause (if/when/because/which...) and the left half is only an opener
     ("But still,") or is at least clause level.
   - **FAIL** if the left piece stops in the middle of a clause, or if two clauses of a run-on sentence are joined
     mid-flow (`p < P_CLAUSE`).
4. **FAIL (half + half).** Both sides are below `P_HALF = 0.15` and the two sides belong to different sentences.
5. A right piece that opens with "and/but/then/aur/lekin" after a clause end counts as a clause start. A left piece
   whose source goes on with a dependent clause ("...the approach | ki ...", "...tokens | and, uh") counts as clause
   level, as long as the right side is a sentence start.
6. **FAIL** if the weaker side is below `P_CLAUSE = 0.05`: a cropped start or end. This drops to REVIEW when the words
   dropped there are garbled in the transcript (mean ASR confidence under 0.35).
7. **REVIEW** if the weaker side is between `P_CLAUSE` and `P_SENT` (a clause boundary). The report shows the text on
   both sides and the reason.

The edit's first word must start a sentence and its last word must end one, on the same scale.

Every FAIL or REVIEW cut comes with a **fix**: the nearest sentence end or start on each side (`boundaries.snap`).

**Re-listen** (with `--media`). Whisper re-transcribes the exported audio from t-8 s to t+4 s around every cut and repair. All windows go through one `whisper-cli` call with the Hinglish prompt for Hinglish takes, and results are cached in `kit/cut/eval/relisten_cache`. The join is anchored in the new transcript by its text, not by whisper's times. Then:

- A PASS cut that whisper hears as one sentence running through the join (no full stop, SaT < 0.05) becomes REVIEW.
- A clause-level REVIEW that whisper ends with a full stop (and SaT >= 0.3 on the new text agrees) becomes PASS.
- A join whose own left or right word is not heard as written, with something else heard in its place, becomes REVIEW
  ("a cropped word?").
- The re-listen never rescues a FAIL. The cold-open join 12530->12737 sounds like a clean full stop, but its right
  piece is still a cropped start.

## The boundary model (sentmap)

Features per gap. All are free and run locally; models live in `kit/models/`.

| feature | source | alone (AUC, S vs rest) |
|---|---|---|
| `sat` | wtpsplit SaT `sat-3l-sm` (MIT, ONNX, no torch) on the bare text (lowercase, no punctuation) | **0.954** |
| `sat_p` | the same on whisper's punctuated text | 0.886 |
| `pause` | silence between energy-refined word times; `vad_pause` is Silero VAD v5 (ONNX) | 0.807 |
| `punct` | whisper's mark on the word | 0.74 (.) / 0.68 (,) |
| `starter` | next word is so/but/now/first/by/if/when/toh... | 0.736 |
| `turn` | Pipecat Smart Turn v3.2 (BSD-2, 8 MB ONNX), last 8 s of audio up to the word's end + 200 ms | 0.723 |
| `f0_*` | Praat pitch (parselmouth): slope over the last 300 ms voiced, end vs speaker median, reset of the next word | 0.54-0.61 (weak for this speaker) |
| lexicon | left_hard/left_soft/right_hard/right_soft/hindi_final/tag | priors |

`p = sigmoid(bias + Σ w·f)` with hand-set weights (`sentmap.WEIGHTS`). They came from a logistic fit on 1,601
hand-labelled gaps (`fixtures/expensewaale_boundaries.json`; 86 sentence ends), then rounded and sign-constrained. The
fit transfers across takes: trained on English and tested on Hinglish, AUC 0.989; the reverse, 0.977. The shipped
weights score AUC 0.991 on ew1 (Hinglish) and 0.986 on ew2 (English).

| threshold | value | why |
|---|---|---|
| `P_SENT` | 0.5 | 91 % precision, 69 % recall for hand-labelled sentence ends. Run-on speech leaves many ends at clause level, and those become REVIEW. |
| `P_CLAUSE` | 0.05 | 96.5 % of sentence ends sit above it, 89 % of labelled mid-sentence pauses sit below it, and 94 % of all other gaps sit below it. |
| `P_HALF` | 0.15 | Every fixture half + half join has both sides under 0.14. The closest ok join has sides of 0.22 and 0.02. The margin is thin; see Known gaps. |
| `MIN_TRIM_GAP` | 0.12 s heard | This speaker's own within-sentence pauses are 0.10-0.12 s at p10, 0.12-0.15 s at p25 and 0.17-0.23 s at the median. Build slivers at 0.15-0.20 s. |
| `MIN_GLUE` | 0.06 s heard | Below this the words touch. |

The heard gap is a voice-band (250-4000 Hz) dip of at least 10 dB under the local speech level. It works under a music
bed. Silero VAD on the final mix missed most short pauses.

## Fixture results (`uv run python -m kit.cut.evaluate --media`)

| label (fixture) | FAIL | REVIEW | PASS | total |
|---|---|---|---|---|
| bad | **4** | 0 | 0 | 4 |
| edl_v1 cropped starts | 1 | 1 | 0 | 2 |
| review | 0 | 2 | 0 | 2 |
| ok_repair | 0 | 2 | 2 | 4 |
| ok | **0** | 13 | 21 | 34 |

- FAIL on an ok or ok_repair join: **0 %**. REVIEW on an ok or ok_repair join: 39 % with the re-listen, 45 % from the
  transcript alone.
- The re-listen promoted four clause-level REVIEWs to PASS (whisper heard a full stop there). It turned two
  ok/ok_repair joins into REVIEW (128->142, 2426->2442), and it adds notes to three that were already REVIEW. These
  look like real audio defects, not boundary-model noise:
  - 2426->2442 (long) and 2426->2471 (Short): "max effort" is squeezed into about 0.34 s of audio where the source
    takes about 0.72 s, and whisper hears "ultra" or "uh". The aligner drifted, so the word is cropped.
  - 128->142: "It's" lasts 34 ms in the edit, and the re-listen does not hear it.
  - 2223->2225: the dropped junk word "English" is still audible.
  - 2347->2357: the re-listen hears "but yeah" from the dropped stretch.
- The v1 crop 2021->388 ("...low, right?" || "it's been around 6 minutes") FAILs. The suggested fix is "start the right
  piece at 376", which is exactly the fix the editor made.
- v1 2223->2237 is only REVIEW. Its right piece "High effort, I just thought..." follows a full stop (p 0.91), so at
  sentence level it is a valid start. What v1 lost there was a whole transition sentence ("...let's move to the next,
  which is the high mode."). The join is flagged through its left end (p 0.17).

## Runtime (this Mac, with other agents running at the same time)

| step | time |
|---|---|
| `sentmap`, first build | 4.4 s per audio minute steady state (Smart Turn ~4 s/min, SaT ~0.15 s/min, VAD ~0.2 s/min, pitch under 0.6 s/min). Loading SaT takes 10-15 s once per process: 49 s for both takes, 8 min of audio, about 6 s per minute. Cached after that. Under heavy load from other agents (load average around 97), the same build took 119 s, about 11 s per audio minute. |
| `cutcheck`, transcript only | about 0.1 s per edit once the maps are cached |
| `cutcheck --media`, cold | 35-75 s per edit: about 2-3 s per join for whisper plus about 15 s to load SaT. Long video: 75-100 s for 4.5 min (29 joins). Short: 35-75 s for 1.4 min (15 joins). Reruns with the whisper cache take 5-30 s, mostly loading SaT. |

## Integration

### films (`edl.py`, `reel_edl.py`)

This is a description only; films/ was not edited.

1. **Snap while choosing KEEP.** Build ranges with `Boundaries(job).snap(a, b)`. Its modes are expand (the whole sentences that cover the range), shrink, and nearest. For a restart, use `restart_cut(k)`.
2. **Gate before building.** Run `cutcheck.check(cutcheck.words_from_ranges(ranges, IdMap.parse("ew1=0,ew2=2000")), idmap)` in `main()` before any media work. Abort on FAIL, print REVIEW items:
   ```python
   from kit.cut.common import IdMap
   from kit.cut import cutcheck
   ids = IdMap.parse("ew1=0,ew2=2000")
   res = cutcheck.check(cutcheck.words_from_ranges([(BASE[c] + a, BASE[c] + b) for c, a, b, *_ in KEEP], ids), ids)
   cutcheck.print_report(res, quiet=True)
   if res["verdict"] == "FAIL" and "--force" not in sys.argv: sys.exit(3)
   ```
   `reel_edl.py` runs the same on its KEEP ids. They are already edit ids, so the mapping is the same.
3. **Gate after rendering.** Next to `kit/qa/qa.py`, run
   `uv run python -m kit.cut.cutcheck edl.json --sources=ew1=0,ew2=2000 --media=<render>.mp4`. That is the re-listen, plus
   the gaps viewers hear at pause trims. Never deliver an exit 3. Answer each REVIEW in the notes.
4. Build pause slivers at 0.15-0.20 s heard, not 0.11 s, and pad word edges from the aligner's word times. The re-listen
   found aligner drift cropping words ("max effort", "It's"), so after a re-cut, re-check with `--media`.

### shorts CLI (`shorts plan`)

This is a description only; shorts/ was not edited.

1. Once `analyze` finishes, build the map: `kit.cut.sentmap.build(job.name)`. It writes `output/temp/jobs/<job>/sentmap.json` (rebuilt on demand if temp was deleted).
2. In `plan()`, after `removed` is final and before `build_segments`, snap each removed range so that what stays is whole
   sentences. A removal must start at a sentence start and end at a sentence end, or be a repair that `repair_kind`
   accepts. `brief.cut_words` and Jev's dropped sentences go through `Boundaries.snap(..., mode="expand")`. Restarts use
   `restart_cut`. The cold open (`teaser_segment`) must start and end at sentence boundaries too.
3. After the segments are built, run
   `cutcheck.check(cutcheck.words_from_ranges([(s.first, s.last) for s in segs], IdMap({job: 0}, None)), ...)`.
   - On a FAIL, raise `ShortsError("E_CUT_SENTENCE", ...)` and include the fix the report suggests.
   - A REVIEW becomes a pending question in `decisions.json`, as `shorts decide` does: the text on both sides plus the reason.
   - Pause-trim WARNs go into `warnings`.
4. `shorts check` (QA) runs `cutcheck --media` on the render, alongside `qa.py`.

## Known gaps

- **Run-on speech produces REVIEW noise.** This speaker's sentence ends often carry no pause and a comma, which makes
  them clause-level, so about a quarter of the ok joins land in REVIEW on boundary grounds alone. That is by design:
  the agent judges them, and the re-listen promotes the ones it hears as full stops.
- **`P_HALF` margins are thin.** The ok join 2347->2357 has a left side of 0.22; B4's left side is 0.13. The B-cases
  are also caught by the other rules (B1, B4: weaker side 0.02; B2: an aside FAIL; B3: a run-on FAIL), so no bad join
  depends on `P_HALF` alone.
- **Narrative crops are out of scope.** Dropping a whole transition sentence before a valid sentence start (v1
  2223->2237) is not a sentence-level crop, so it only becomes REVIEW, and only through the other side.
- **The re-listen is whisper on a mix with music.** Its "word not heard" notes include ASR noise ("token" heard as
  "poker", Hinglish respellings), so they stay REVIEW, never FAIL. Some windows cannot be anchored (the Hinglish
  passage that was transcribed in English).
- **Word times in older edl.json files are stale.** They were built from earlier aligner times or whisper retimes, so a
  pause-trim gap without `--media` is only an estimate and is WARN at most.
- **Calibration covers one speaker, two takes.** Re-run `calibrate --fit` once a new creator or language has about 50
  labelled sentence ends.
