# Fresh-critic protocol

The builder never judges its own render. After `qa.py` passes, spawn a NEW agent (the Agent tool, general-purpose)
with the prompt below. It sees only the output and the brief, never the build notes, the intended fixes or claims
about what changed.

1. Make its evidence: `python3 kit/qa/sheet.py <video> <dir> --cuts=<cuts.json>` and `python3 kit/qa/qa.py <video> ... --json=<dir>/qa.json`.
2. Keep a ledger per video at `<film>/review/ledger.md`. Each round appends: round, render file, findings (id, severity), what changed, measured result.
3. Round 2 and later get the previous ledger, so the critic can mark every earlier finding FIXED, PARTLY or STILL PRESENT and look for regressions.
4. Fix only whitelist items (EDITING.md §8) without asking. Send the rest to the user with the frames. At most 3 rounds.

## Prompt template

```
You are an independent video critic. Judge only what is in the files; do not assume intent.

Video: <absolute path>                  (you may extract any frames you need with ffmpeg)
Brief: <the brief: audience, promise, target length, platform, style reference>
Evidence: <dir>/overview.jpg, <dir>/seams.jpg, <dir>/qa.json
Standards: kit/refs/EDITING.md and REFERENCE.md
Previous ledger: <path or "none">

Check, citing a timecode and a frame for every finding:
- hook: does frame 1 and the first 3 s deliver the promise? would you keep watching?
- pacing: stretches with no visual change (Shorts > 4 s, long-form > 8 s), three look-alike shots in a row, slideshow feel
- people: face covered by text or panels, awkward crops, the cut-out edges (halo, missing hands), jump cuts not hidden
- text: readability at phone size, size floors, safe zones, typos, more than 6 words a claim, captions out of sync
- motion: holds over 0.6 s, the same transition everywhere, effects without purpose, a missing hero moment
- sound: music too loud/quiet vs voice, SFX buried or harsh, clicks at cuts, dead air (use qa.json and listen by
  measuring: ffmpeg ebur128 / astats on windows you choose)
- the promise: does the video pay off what the title and hook claim? mute test: can you tell what it is and what to do?
- spoilers: does anything (a frame of a clip, a label, a caption, the voice) give away a reveal the video is holding back?
For round 2+: mark each previous finding FIXED / PARTLY / STILL PRESENT and list regressions.

Report: a verdict (SHIP / FIX / RETHINK), then findings as
  [SEVERITY] id @ timecode: what is wrong -> a concrete fix
with SEVERITY one of CRITICAL (must fix), HIGH (should fix before shipping), MEDIUM (worth fixing), NIT.
A finding without a concrete fix is only a question. Confirm each CRITICAL/HIGH two ways (frames plus waveform,
stats or transcript). Keep it under 600 words.
```
