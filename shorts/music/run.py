"""`shorts music`: rank library tracks for a job and place one so its drop lands on a chosen line.

    shorts music JOB --mood tech                   # ranked picks for the mood (brief.json music_mood is the default)
    shorts music JOB --mood hype --hit "2026"      # line the strongest drop up with the first word matching "2026"
    shorts music JOB --mood tech --apply 1         # write pick 1 into visuals.json and log the use
"""
from __future__ import annotations

import re

from shorts.brief import load_brief, load_style
from shorts.errors import ShortsError
from shorts.gfx.timeline import word_timeline
from shorts.job import Job
from shorts.music import library as lib
from shorts.schemas import Analysis, EditFile, Visuals

RECENT = 4                                   # tracks used by the last N jobs are pushed down the list


def _hit_time(words: list[dict], hit: str | None) -> tuple[float | None, str | None]:
    if not hit:
        return None, None
    if re.fullmatch(r"\d+(\.\d+)?s", hit):
        return float(hit[:-1]), hit
    want = re.sub(r"\W", "", hit.lower())
    for w in words:
        if re.sub(r"\W", "", w["text"].lower()).startswith(want):
            return w["start"], w["text"]
    raise ShortsError("E_MUSIC", f"No kept word starts with {hit!r}.", "Pass a word that is in the edit, or a time like 12.5s.")


def place(s: dict, duration: float, hit: float | None, first_word: float) -> dict:
    """Where to start the track (and when it enters) so the video lines up with it."""
    drops = sorted(s["drops"], key=lambda d: -d["strength"])
    if hit is not None and drops:
        d = next((d for d in drops if d["t"] >= hit and d["t"] - hit + duration <= s["duration"]), drops[0])
        start = d["t"] - hit
        if start >= 0:
            return {"start": round(start, 3), "enter": 0.0, "drop_at": round(hit, 3), "drop_track": d["t"], "mode": "drop on the hit"}
        return {"start": 0.0, "enter": round(-start, 3), "drop_at": round(hit, 3), "drop_track": d["t"],
                "mode": "dry open, the track enters so its drop lands on the hit"}
    # no hit: skip a long quiet intro and start on a beat just before the voice
    beat = 60 / s["bpm"]
    start = max(0.0, s["quiet_intro"] - 0.5)
    start = s["beat0"] + round((start - s["beat0"]) / beat) * beat
    return {"start": round(max(0.0, start - min(first_word, 0.4)), 3), "enter": 0.0, "drop_at": None, "drop_track": None,
            "mode": "groove from the first loud bar"}


def score(t: dict, s: dict, p: dict, duration: float, pace: str, recent: set[str]) -> tuple[float, list[str]]:
    why, sc = [], 0.0
    room = s["duration"] - p["start"] - (duration - p["enter"])
    if room < 0:
        sc -= 3 + min(4, -room / 10)
        why.append(f"loops ({-room:.0f} s short)")
    else:
        sc += 1
    if p["drop_at"] is not None:
        d = next(d for d in s["drops"] if d["t"] == p["drop_track"])
        sc += min(3, d["strength"] / 3)
        why.append(f"drop strength {d['strength']}")
    if pace == "fast":
        sc += 1 if s["bpm"] >= 105 else -0.5
    sc -= max(0, s["steadiness_db"] - 3) * 0.4            # talk-heavy videos want a bed that does not surge around
    if t["file"] in recent:
        sc -= 4
        why.append("used recently")
    if t.get("credit", "none required") != "none required":
        why.append("needs a credit")
    return round(sc, 2), why


def suggest(job: Job, mood: str | None, hit: str | None, n: int = 3) -> dict:
    edit = EditFile.model_validate(job.read("edit.json"))
    analysis = Analysis.model_validate(job.read("analysis.json"))
    overrides = load_brief(job).caption_overrides if job.has("brief.json") else {}
    words = word_timeline(edit, analysis, overrides)          # match lines as the captions read them
    duration = edit.duration
    style = load_style(job) if job.has("style.json") else None
    mood = mood or getattr(style, "music_mood", None)
    if mood not in lib.MOODS:
        raise ShortsError("E_MUSIC", f"Unknown mood {mood!r}.", f"Use one of: {', '.join(lib.MOODS)}.")
    pace = getattr(style, "pace", "normal") or "normal"
    ht, hit_word = _hit_time(words, hit)
    recent = {u["file"] for u in lib.usage()[-RECENT:] if u["job"] != job.name}
    picks = []
    for t in lib.tracks():
        if t["mood"] != mood or t.get("vocals"):
            continue
        s = lib.structure(t)
        p = place(s, duration, ht, words[0]["start"] if words else 0.0)
        sc, why = score(t, s, p, duration, pace, recent)
        picks.append({"score": sc, "file": t["file"], "title": t["title"], "artist": t["artist"], "bpm": s["bpm"],
                      "track_seconds": s["duration"], **p, "notes": why, "credit": t.get("credit", "none required")})
    if not picks:
        raise ShortsError("E_MUSIC", f"No {mood} tracks in the library.", "Run kit/assets_src/fetch.py or add tracks to kit/music.")
    picks.sort(key=lambda x: -x["score"])
    return {"job": job.name, "mood": mood, "duration": round(duration, 2), "hit": hit_word, "hit_at": ht,
            "picks": picks[:n]}


def apply(job: Job, pick: dict, level_db: float | None = None) -> dict:
    vis = Visuals.model_validate(job.read("visuals.json")) if job.has("visuals.json") else Visuals()
    old = vis.music.model_dump() if vis.music else {}
    music = {**{k: v for k, v in old.items() if k in ("level_db", "duck_db", "fade_in", "fade_out", "drops")},
             "file": str(lib.MUSIC.parent / pick["file"]), "start": pick["start"], "enter": pick["enter"]}
    if level_db is not None:
        music["level_db"] = level_db
    data = job.read("visuals.json") if job.has("visuals.json") else Visuals().model_dump()
    data["music"] = music
    Visuals.model_validate(data)
    job.write("visuals.json", data)
    lib.record_use(job.name, pick["file"])
    return {"applied": pick["file"], "music": music, "credit": pick["credit"]}


def run(args) -> dict:
    job = Job.open(args.job)
    out = suggest(job, args.mood, args.hit, n=max(3, args.apply or 0))
    if args.apply:
        if args.apply > len(out["picks"]):
            raise ShortsError("E_MUSIC", f"There are only {len(out['picks'])} picks.", "Choose a smaller --apply number.")
        out["applied"] = apply(job, out["picks"][args.apply - 1], args.level_db)
    return out


def add_command(sub) -> None:
    p = sub.add_parser("music", help="Pick background music from kit/music for a job (mood, drop on a line).")
    p.add_argument("job")
    p.add_argument("--mood", choices=lib.MOODS)
    p.add_argument("--hit", help="a kept word (or a time like 12.5s) where the track's drop should land")
    p.add_argument("--apply", type=int, help="write pick N into visuals.json")
    p.add_argument("--level-db", type=float, help="music level relative to the voice in the gaps (default: keep)")
    p.set_defaults(func=run)
