"""Sentence-safe cut check: every join in an edit must start at a sentence/thought start and end at a completed
thought. Exit code like kit/qa/qa.py: 0 PASS, 2 WARN (review items listed), 3 FAIL.

    uv run python -m kit.cut.cutcheck EDL.json --sources=ew1=0,ew2=2000 [--wrap=10000] [--media=final.mp4]
                                      [--hinglish=ew1] [--json=report.json] [--no-relisten] [--quiet]

  EDL.json   an edit with "words": [{"i", "text", "t", "e"}] on the output timeline (films' edl.json, reel/edl.json)
  --sources  which take each word id comes from: id = base + word index ("ew2" alone = one take, base 0)
  --wrap     ids at or above this are copies of a word placed twice (a cold open): id % wrap (default 10000)
  --media    the exported video/audio: turns on the re-listen (whisper on t-8..t+4 s around each join) and measures
             the pause the viewer hears at every join and pause trim (voice-band dip, works under a music bed)
  --hinglish takes spoken in Hinglish (re-listen uses the Hinglish prompt); default: the takes' analysis.json language

Every pair of consecutive words is one of:
  continuous   next word of the same take. If the edit shortened the pause there it is a PAUSE TRIM: the gap left must
               sound natural (>= MIN_TRIM_GAP; below MIN_GLUE the words run together = FAIL)
  repair       a few words dropped inside one sentence that the speaker repeated or filled ("your, uh, your" -> "your",
               a restart "it took me a new check, it took me a proper plan" -> "it took me a proper plan"): fine
  cut          anything else (content dropped, another take, a reorder): judged on the boundary map (kit/cut/sentmap.py)
               p_end of the left piece's last word, p_start of the right piece's first word:
    FAIL  the left piece ends on a connector/article ("and", "the", "because", "aur") or the right one starts on a
          postposition/aux/relative ("ki", "se", "hai", "which", "of")
    PASS  both sides are sentence boundaries (p >= P_SENT)
    FAIL  half of one sentence spliced onto half of another (both sides < P_HALF, the two sides in different sentences)
    FAIL  one side is mid-sentence (p < P_CLAUSE): the piece starts/stops inside a sentence (a cropped start/end)
    REVIEW  one side is only a clause boundary (P_CLAUSE <= p < P_SENT): text either side + why, for the editor
    REVIEW  an aside dropped inside one sentence ("But still, [if ... then] I will say, ...") - does it read as one?
  The first word of the edit must start a sentence and the last must end one (same scale).
With --media every cut and repair is re-listened: a PASS becomes REVIEW when the fresh transcript runs straight through
the join or loses words next to it.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.cut.boundaries import OPENERS, Boundaries  # noqa: E402
from kit.cut.common import FILLERS, LEFT_HARD, LEFT_SOFT, RIGHT_HARD, IdMap, job_dir, job_language, load_words, norm  # noqa: E402
from kit.cut.sentmap import P_CLAUSE, P_SENT, SentMap  # noqa: E402

P_HALF = 0.15            # both sides under this, in different sentences = half + half
MIN_TRIM_GAP = 0.12      # a trimmed pause inside a sentence keeps at least this (s, heard): the speaker's own pauses
                         # are 0.10-0.12 s at the 10th percentile, 0.12-0.15 s at the 25th, 0.17-0.23 s median (both
                         # takes); build slivers at ~0.15-0.20 s, flag under 0.12 s
MIN_GLUE = 0.06          # under this the words run into each other
MAX_REPAIR_SKIP = 25     # a restart/filler repair drops at most this many words
RELISTEN_SAT = 0.3       # SaT on the fresh transcript must agree with whisper's full stop to upgrade a REVIEW
GARBLED_P = 0.35         # mean ASR confidence of a short dropped stretch under this = the transcript can't be trusted
SUBORD = frozenset("if when because since although though unless while which who where whereas after before until "
                   "whether jo jab agar kyunki kyonki ki that so".split())
COORD = frozenset("and but then aur lekin".split())     # open an independent clause ("And then...", "But...")


def arg(argv, name, default=None):
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), default)


class Takes:
    """Words, boundary maps and ASR confidence per take, loaded on demand."""

    def __init__(self):
        self.B, self.W, self.P = {}, {}, {}

    def get(self, job):
        if job not in self.B:
            self.B[job] = Boundaries(job, SentMap.load(job))
            self.W[job] = load_words(job)
            an = json.loads((job_dir(job) / "analysis.json").read_text())
            self.P[job] = [float(w.get("p", 1.0)) for w in an["words"]]
        return self.B[job], self.W[job], self.P[job]


def _txt(words, a, b):
    return " ".join(words[k]["text"] for k in range(max(0, a), min(len(words), b + 1)))


def repair_kind(W, k0, k1):
    """A short forward skip inside one sentence that only removes a filler or a restart -> a description, else None."""
    skip = [norm(W[k]["text"]) for k in range(k0 + 1, k1)]
    if not skip or len(skip) > MAX_REPAIR_SKIP:
        return None
    if all(s in FILLERS or not s for s in skip):
        return f"filler removed ({' '.join(W[k]['text'] for k in range(k0 + 1, k1))})"
    n = len(W)
    head = 0                                   # the right piece repeats the words that followed the left piece
    while k1 + head < n and k0 + 1 + head < k1 and norm(W[k0 + 1 + head]["text"]) == norm(W[k1 + head]["text"]):
        head += 1
    tail = 0                                   # the words before the right piece repeat the left piece's last words
    while k0 - tail >= 0 and k1 - 1 - tail > k0 and norm(W[k0 - tail]["text"]) == norm(W[k1 - 1 - tail]["text"]):
        tail += 1
    k = max(head, tail)
    fillers = sum(1 for s in skip if s in FILLERS)
    if k >= 2 or (k >= 1 and (len(skip) <= 4 or fillers)):
        rep = _txt(W, k1, k1 + head - 1) if head >= tail else _txt(W, k0 - tail + 1, k0)
        return f"restart removed (\"{rep}\" said again; the earlier attempt is dropped)"
    return None


def judge_cut(B, W, P, k0, k1, cross, jobL, jobR, BR=None, WR=None, hidden_left=False):
    """Verdict for a content cut. B/W/P = left take (boundary map, words, ASR confidence); BR/WR = right take."""
    BR, WR = BR or B, WR or W
    lw, rw = norm(W[k0]["text"]), norm(WR[k1]["text"])
    notes = []
    pL, _ = B.p_end(k0)
    pR, _ = BR.p_start(k1)
    if hidden_left and k0 > 0:                 # the edit hides this word's caption: it may be an ASR ghost ("So" = the
        p_prev = B.p_end(k0 - 1)[0]            # tail of "tokens") or merged into the word before; judge both
        if p_prev > pL:
            pL, lw = p_prev, norm(W[k0 - 1]["text"])
            notes.append(f"judged at \"{W[k0 - 1]['text']}\" (the last word's caption is hidden)")
    same_fwd = jobL == jobR and k1 > k0 + 1 and BR is B
    if same_fwd and k1 - k0 - 1 <= 2:          # dropped one or two junk words (fillers, a garbled token): see through them
        junk = [k for k in range(k0 + 1, k1) if norm(W[k]["text"]) in FILLERS or P[k] < GARBLED_P]
        if len(junk) == k1 - k0 - 1:
            pL, pR = max(pL, B.p_end(k1 - 1)[0]), max(pR, BR.p_start(k0 + 1)[0])
            notes.append("dropped words are fillers/garbled")
    out = {"pL": round(pL, 3), "pR": round(pR, 3), "left_word": W[k0]["text"], "right_word": WR[k1]["text"]}
    if lw in LEFT_HARD:
        return {**out, "cat": "lexicon", "verdict": "FAIL", "why": f"the left piece ends on \"{W[k0]['text']}\", a word that needs what follows"}
    if rw in RIGHT_HARD:
        return {**out, "cat": "lexicon", "verdict": "FAIL", "why": f"the right piece starts on \"{WR[k1]['text']}\", which hangs on the word before it"}
    if pL >= P_SENT and pR >= P_SENT:
        return {**out, "cat": "sentence", "verdict": "PASS", "why": "sentence end to sentence start" + ("; " + "; ".join(notes) if notes else "")}
    interior = max((B.sm.p_end(k) for k in range(k0 + 1, k1 - 1)), default=0.0) if same_fwd else 0.0
    out["interior"] = round(interior, 3)
    cross = cross or not same_fwd or pL >= P_SENT or pR >= P_SENT or interior >= P_SENT
    coord = rw in COORD
    if not cross:                                       # both sides inside ONE sentence: an aside was dropped
        skip = [norm(W[k]["text"]) for k in range(k0 + 1, k1)]
        first = next((x for x in skip if x not in OPENERS and x not in COORD), skip[0] if skip else "")
        s0 = max((k for k in range(k0) if B.sm.p_end(k) >= P_SENT), default=-1) + 1
        opener_only = all(norm(W[k]["text"]) in OPENERS | {"still"} for k in range(s0, k0 + 1))
        aside = f"\"{_txt(W, k0 + 1, k1 - 1)}\""
        if first in SUBORD or len(skip) <= 3:
            if opener_only or pL >= P_CLAUSE:
                return {**out, "cat": "aside", "verdict": "REVIEW", "why": f"a clause dropped inside one sentence ({aside}); check the rest reads as one sentence"}
            return {**out, "cat": "aside", "verdict": "FAIL", "why": f"the left piece stops mid-clause (p_end {pL:.2f}) before the dropped clause {aside}"}
        if coord and pL >= P_HALF:
            return {**out, "cat": "coord", "verdict": "REVIEW", "why": f"the right piece opens a coordinate clause (\"{WR[k1]['text']} ...\") after a clause end "
                                                       f"(p_end {pL:.2f}); dropped {aside}"}
        if min(pL, pR) < P_CLAUSE:
            side = "left piece stops" if pL <= pR else "right piece starts"
            return {**out, "cat": "runon", "verdict": "FAIL", "why": f"two clauses of one run-on sentence spliced mid-flow: the {side} mid-sentence "
                                                     f"(p {min(pL, pR):.2f}); dropped {aside}"}
        return {**out, "cat": "aside", "verdict": "REVIEW", "why": f"content dropped inside one sentence ({aside})"}
    if pL < P_HALF and pR < P_HALF:
        return {**out, "cat": "half", "verdict": "FAIL", "why": f"half of one sentence spliced onto half of another (p_end {pL:.2f}, p_start {pR:.2f})"}
    if coord and pL >= P_SENT and pR >= P_CLAUSE:
        return {**out, "cat": "coord", "verdict": "PASS", "why": f"a sentence end, then a new sentence opening with \"{WR[k1]['text']}\""}
    if coord and pL >= P_HALF and pR < P_CLAUSE:
        pR = P_CLAUSE
        notes.append(f"the right piece opens a coordinate clause (\"{WR[k1]['text']} ...\")")
    nxt = next((norm(W[k]["text"]) for k in range(k0 + 1, min(len(W), k0 + 4)) if norm(W[k]["text"]) not in OPENERS - SUBORD - COORD), "")
    if nxt in SUBORD | COORD and lw not in LEFT_SOFT and pR >= P_SENT and pL < P_CLAUSE:
        pL = P_CLAUSE
        notes.append(f"the source goes on with \"{nxt} ...\" (a dependent or added clause); the main clause is complete")
    weak = min(pL, pR)
    side = "left piece stops" if pL <= pR else "right piece starts"
    cat = "bumped" if notes else "clause"
    if weak < P_CLAUSE:
        verdict, why, cat = "FAIL", f"the {side} mid-sentence (p {weak:.2f})", "mid"
        if same_fwd and 0 < k1 - k0 - 1 <= 8:
            conf = sum(P[k] for k in range(k0 + 1, k1)) / (k1 - k0 - 1)
            if conf < GARBLED_P:
                verdict, cat, why = "REVIEW", "garbled", why + f"; but the dropped words are garbled in the transcript (ASR confidence {conf:.2f}): listen"
    elif weak < P_SENT:
        verdict, why = "REVIEW", f"the {side} at a clause boundary, not a sentence boundary (p {weak:.2f})"
    else:
        verdict, why = "PASS", "sentence end to sentence start"
    if notes:
        why += "; " + "; ".join(notes)
    return {**out, "pL_eff": round(pL, 3), "pR_eff": round(pR, 3), "cat": cat, "verdict": verdict, "why": why}


def words_from_ranges(ranges, idmap: IdMap, gap: float = 0.15) -> dict:
    """An edit from kept ranges [(first id, last id), ...] in edit ids: the words on a made-up output timeline (source
    times, pieces placed `gap` apart). Lets an edl.py check its KEEP list before building anything."""
    words, t = [], 0.0
    cache = {}
    for a, b in ranges:
        job, ka, copy = idmap.resolve(a)
        _, kb, _ = idmap.resolve(b)
        W = cache.setdefault(job, load_words(job))
        t0 = W[ka]["start"]
        for k in range(ka, kb + 1):
            words.append({"i": a + (k - ka), "text": W[k]["text"], "t": round(t + W[k]["start"] - t0, 3),
                          "e": round(t + W[k]["end"] - t0, 3)})
        t += W[kb]["end"] - t0 + gap
    return {"words": words}


def check(edl_path, idmap: IdMap, media=None, hinglish=None, do_relisten=True, log=print):
    """edl_path: an edl.json path, or a dict with "words" (e.g. from words_from_ranges)."""
    t_start = time.time()
    edl = edl_path if isinstance(edl_path, dict) else json.loads(Path(edl_path).read_text())
    edl_path = "<ranges>" if isinstance(edl_path, dict) else edl_path
    words = list(edl["words"])                       # the list order is the output order (times can be retimed)
    takes = Takes()
    res = {"edl": str(edl_path), "sources": idmap.sources, "joins": [], "trims": [], "edges": []}
    # speed of the output vs the source (1.07 in the ExpenseWaale cuts)
    ratios = []
    for w in words:
        job, k, _ = idmap.resolve(w["i"])
        _, W, _ = takes.get(job)
        if w["e"] > w["t"] and W[k]["end"] > W[k]["start"]:
            ratios.append((W[k]["end"] - W[k]["start"]) / (w["e"] - w["t"]))
    speed = sorted(ratios)[len(ratios) // 2] if ratios else 1.0
    res["speed"] = round(speed, 3)
    for n in range(1, len(words)):
        w0, w1 = words[n - 1], words[n]
        j0, k0, c0 = idmap.resolve(w0["i"])
        j1, k1, c1 = idmap.resolve(w1["i"])
        B0, W0, P0 = takes.get(j0)
        B1, W1, P1 = takes.get(j1)
        out_gap = round(w1["t"] - w0["e"], 3)
        base = {"t": round(w1["t"], 3), "left_id": w0["i"], "right_id": w1["i"], "gap": out_gap}
        if j0 == j1 and c0 == c1 and k1 == k0 + 1:
            src_gap = W0[k1]["start"] - W0[k0]["end"]
            # the edit shortened this pause: the onset-to-onset time shrank (onsets are steadier than word ends)
            if (w1["t"] - w0["t"]) * speed < (W0[k1]["start"] - W0[k0]["start"]) - 0.08 and src_gap > 0.05:
                # without the media the gap is an estimate from word times (they can be 50-100 ms off): WARN at most
                v = "WARN" if out_gap < MIN_GLUE else "PASS"
                res["trims"].append({**base, "src_gap": round(src_gap, 3), "boundary": B0.sm.label_end(k0), "verdict": v,
                                     "left": _txt(W0, k0 - 5, k0), "right": _txt(W0, k1, k1 + 5),
                                     "why": "words may run together (word-time estimate; confirm with --media)" if v == "WARN"
                                     else "pause kept (word-time estimate)"})
            continue
        j = {**base, "left": _txt(W0, k0 - 7, k0), "right": _txt(W1, k1, k1 + 7)}
        if j0 == j1 and c0 == c1 and k1 > k0 + 1 and (rk := repair_kind(W0, k0, k1)):
            j.update({"kind": "repair", "verdict": "PASS", "why": rk, "dropped": _txt(W0, k0 + 1, k1 - 1)})
        else:
            cross = j0 != j1 or c0 != c1 or k1 <= k0
            j["kind"] = "cut"
            if j0 == j1 and k1 > k0 + 1 and c0 == c1:
                j["dropped"] = _txt(W0, k0 + 1, k1 - 1) if k1 - k0 - 1 <= 60 else f"{k1 - k0 - 1} words"
            j.update(judge_cut(B0, W0, P0, k0, k1, cross, j0, j1, B1, W1, hidden_left=(w0.get("text") == "")))
        res["joins"].append(j)
    # edges: the edit starts at a sentence start and ends at a sentence end
    visible = [w for w in words if w.get("text") != ""] or words      # a hidden last word may be an ASR ghost
    for side, w in (("start", visible[0]), ("end", visible[-1])):
        job, k, _ = idmap.resolve(w["i"])
        B, W, _ = takes.get(job)
        p = B.p_start(k)[0] if side == "start" else B.p_end(k)[0]
        v = "PASS" if p >= P_SENT else "REVIEW" if p >= P_CLAUSE else "FAIL"
        res["edges"].append({"side": side, "id": w["i"], "p": round(p, 3), "verdict": v,
                             "text": _txt(W, k - 6, k + 6), "why": f"the edit {'starts' if side == 'start' else 'ends'} "
                             + ("at a sentence boundary" if v == "PASS" else f"inside a sentence (p {p:.2f})")})
    # re-listen + heard gaps
    res["timing"] = {"transcript_checks": round(time.time() - t_start, 2)}
    if media:
        from kit.cut.relisten import gaps_at, relisten
        t1 = time.time()
        items = [j for j in res["joins"]]
        heard = gaps_at(media, [j["t"] - 0.02 for j in items] + [t["t"] - 0.02 for t in res["trims"]])
        res["timing"]["heard_gaps"] = round(time.time() - t1, 2)
        t1 = time.time()
        for j, g in zip(items + res["trims"], heard):
            j["heard_gap"] = g
        if do_relisten and items:
            hl = set(hinglish if hinglish is not None else [s for s in idmap.sources if job_language(s) == "hinglish"])
            groups = {}
            for j in items:
                job = idmap.resolve(j["right_id"])[0]
                groups.setdefault(job in hl or idmap.resolve(j["left_id"])[0] in hl, []).append(j)
            for is_hl, js in groups.items():
                reqs = []
                for j in js:
                    n = next(n for n in range(1, len(words)) if words[n]["i"] == j["right_id"] and words[n - 1]["i"] == j["left_id"])
                    lo = n
                    while lo > 0 and words[lo - 1]["t"] >= j["t"] - 8.0:
                        lo -= 1
                    hi = n
                    while hi + 1 < len(words) and words[hi + 1]["t"] <= j["t"] + 3.8:
                        hi += 1
                    # hidden-caption words ("" in the edit) can be ASR ghosts: leave them out of the comparison
                    keep = [m for m in range(lo, hi + 1) if words[m].get("text") != ""]
                    left = max((q for q, m in enumerate(keep) if m <= n - 1), default=0)
                    reqs.append({"t": j["t"], "left": left,
                                 "words": [{"text": src_text(takes, idmap, words[m]), "t": words[m]["t"]} for m in keep]})
                for j, r in zip(js, relisten(media, reqs, hinglish=is_hl)):
                    j["relisten"] = r
                    apply_relisten(j, r)
        res["timing"]["relisten"] = round(time.time() - t1, 2)
    for t in res["trims"]:                             # with the media: judge the pause the viewer hears
        if "heard_gap" in t:
            g = t["heard_gap"]
            if g < MIN_GLUE and t["boundary"] != "sentence_end":
                t["verdict"], t["why"] = "FAIL", f"no pause heard ({g:.2f} s): the words run together"
            elif g < MIN_GLUE:
                t["verdict"], t["why"] = "WARN", f"almost no pause between two sentences ({g:.2f} s heard)"
            elif g < MIN_TRIM_GAP and t["boundary"] != "sentence_end":
                t["verdict"], t["why"] = "WARN", f"tight pause inside a sentence ({g:.2f} s heard < {MIN_TRIM_GAP} s)"
            else:
                t["verdict"], t["why"] = "PASS", f"natural pause kept ({g:.2f} s heard)"
    allv = [x["verdict"] for x in res["joins"] + res["trims"] + res["edges"]]
    res["verdict"] = "FAIL" if "FAIL" in allv else "WARN" if ("REVIEW" in allv or "WARN" in allv) else "PASS"
    res["counts"] = {"joins": len(res["joins"]), "cuts": sum(j["kind"] == "cut" for j in res["joins"]),
                     "repairs": sum(j["kind"] == "repair" for j in res["joins"]), "trims": len(res["trims"]),
                     **{v: allv.count(v) for v in ("FAIL", "REVIEW", "WARN", "PASS")}}
    res["runtime_s"] = round(time.time() - t_start, 2)
    return res


def src_text(takes, idmap, w):
    job, k, _ = idmap.resolve(w["i"])
    return takes.get(job)[1][k]["text"]


def apply_relisten(j, r):
    """Fold the re-listen into a join's verdict. It never rescues a FAIL. A PASS cut that the fresh transcript reads as
    one sentence running through the join becomes REVIEW; a REVIEW cut at a clause boundary that the fresh transcript
    ends with a full stop (and SaT agrees) becomes PASS. A PASS whose join words are not heard as written (missing, with
    something else heard in their place) becomes REVIEW: a cropped word, or ASR noise - the editor listens."""
    notes = []
    if not r.get("anchored"):
        j["why"] += "; re-listen could not anchor the join in the fresh transcript"
        return
    heard = f"\"{r.get('heard', '')}\""
    stop = r.get("mark") in (".", "?", "!")
    swapped = [side for side, ok in (("left", r.get("left_heard")), ("right", r.get("right_heard"))) if not ok]
    if swapped and (r.get("extra") or r.get("missing")):
        # the word at the join is not heard as itself: a cropped/clipped word (or ASR noise - listen)
        if j["verdict"] == "PASS":
            j["verdict"] = "REVIEW"
        notes.append(f"re-listen does not hear the {' and '.join(swapped)} word at the join as written "
                     f"(missing {r.get('missing')}, heard {r.get('extra') or 'nothing'} there: {heard}); a cropped word?")
    elif r.get("extra"):
        notes.append(f"re-listen hears extra {r['extra']} at the join (a clipped word?)")
    if j["kind"] == "cut" and j["verdict"] == "PASS" and not stop and r["boundary_sat"] < P_CLAUSE:
        j["verdict"] = "REVIEW"
        notes.insert(0, f"re-listen hears one sentence running through the join ({heard}, p {r['boundary_sat']:.2f})")
    elif j["kind"] == "cut" and j["verdict"] == "REVIEW" and j.get("cat") in ("clause", "bumped", "coord") and stop \
            and r["boundary_sat"] >= RELISTEN_SAT and not swapped:
        j["verdict"] = "PASS"
        notes.insert(0, f"re-listen hears a sentence break at the join ({heard}, p {r['boundary_sat']:.2f})")
    if notes:
        j["why"] = j["why"] + "; " + "; ".join(notes)


def print_report(res, quiet=False):
    c = res["counts"]
    print(f"{res['verdict']}: {Path(res['edl']).name}  {c['joins']} joins ({c['cuts']} content cuts, {c['repairs']} repairs), "
          f"{c['trims']} pause trims; {c['FAIL']} FAIL, {c['REVIEW']} REVIEW, {c['WARN']} WARN  ({res['runtime_s']} s)")
    rank = {"FAIL": 0, "REVIEW": 1, "WARN": 2, "PASS": 3}
    items = [("edge", e) for e in res["edges"]] + [("join", j) for j in res["joins"]] + [("trim", t) for t in res["trims"]]
    items.sort(key=lambda it: (rank[it[1]["verdict"]], it[1].get("t", 0)))
    for kind, it in items:
        if quiet and it["verdict"] == "PASS":
            continue
        if kind == "edge":
            print(f"  {it['verdict']:6s} {it['side']:5s} id {it['id']}: {it['why']}  \"{it['text']}\"")
        elif kind == "trim":
            hg = f", heard {it['heard_gap']:.2f}" if "heard_gap" in it else ""
            print(f"  {it['verdict']:6s} trim@{it['t']:.2f} {it['left_id']}->{it['right_id']} gap {it['gap']:.2f} s (source {it['src_gap']:.2f}{hg}): "
                  f"{it['why']}  \"{it['left']} | {it['right']}\"")
        else:
            ps = f"p_end {it['pL']:.2f} p_start {it['pR']:.2f}" if "pL" in it else ""
            print(f"  {it['verdict']:6s} {it['kind']}@{it['t']:.2f} {it['left_id']}->{it['right_id']} {ps}: {it['why']}")
            print(f"           \"...{it['left']}\" || \"{it['right']}...\"")
            if it.get("suggest"):
                print(f"           fix: {it['suggest']}")


def suggest(res, idmap, takes):
    """For each FAIL/REVIEW cut: the nearest sentence boundaries either side (snap)."""
    for j in res["joins"]:
        if j["kind"] != "cut" or j["verdict"] == "PASS":
            continue
        jl, kl, _ = idmap.resolve(j["left_id"])
        jr, kr, _ = idmap.resolve(j["right_id"])
        BL, BR = takes.get(jl)[0], takes.get(jr)[0]
        tips = []
        if j.get("pL_eff", j["pL"]) < P_SENT:
            back, fwd = BL.snap_end(kl, "back"), BL.snap_end(kl, "forward")
            tips.append(f"end the left piece at a sentence end: {idmap.to_id(jl, back) if back is not None else '-'} "
                        f"(\"...{_txt(takes.get(jl)[1], (back or 0) - 4, back or 0)}\") or {idmap.to_id(jl, fwd)} "
                        f"(\"...{_txt(takes.get(jl)[1], fwd - 4, fwd)}\")")
        if j.get("pR_eff", j["pR"]) < P_SENT:
            back, fwd = BR.snap_start(kr, "back"), BR.snap_start(kr, "forward")
            tips.append(f"start the right piece at a sentence start: {idmap.to_id(jr, back)} (\"{_txt(takes.get(jr)[1], back, back + 4)}...\")"
                        + (f" or {idmap.to_id(jr, fwd)} (\"{_txt(takes.get(jr)[1], fwd, fwd + 4)}...\")" if fwd is not None else ""))
        j["suggest"] = "; ".join(tips)


def main(argv):
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 1
    wrap = arg(argv, "wrap", "10000")
    idmap = IdMap.parse(arg(argv, "sources"), int(wrap) if wrap and wrap != "0" else None)
    if not idmap.sources:
        print("--sources is required (e.g. --sources=ew1=0,ew2=2000)")
        return 1
    hl = arg(argv, "hinglish")
    res = check(paths[0], idmap, media=arg(argv, "media"), hinglish=hl.split(",") if hl else None,
                do_relisten="--no-relisten" not in argv)
    suggest(res, idmap, Takes_cache(idmap))
    print_report(res, quiet="--quiet" in argv)
    out = arg(argv, "json")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return {"PASS": 0, "WARN": 2, "FAIL": 3}[res["verdict"]]


def Takes_cache(idmap):
    t = Takes()
    for job in idmap.sources:
        t.get(job)
    return t


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
