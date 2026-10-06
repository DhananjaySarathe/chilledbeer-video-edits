"""Score cutcheck on the labelled ExpenseWaale joins (kit/cut/fixtures/expensewaale_joins.json) and on the first cut
(edl_v1.json), whose cropped sentence starts the user complained about.

    uv run python -m kit.cut.evaluate [--media] [--no-relisten]
    -> a table label -> FAIL/REVIEW/PASS, the misses, and kit/cut/eval/{fixture_eval.json, <edit>.cutcheck.json}

--media re-listens every join in the exported films (films/expensewaale/*.mp4); without it the check is transcript-only.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.cut.common import EVAL, ROOT, IdMap  # noqa: E402
from kit.cut import cutcheck  # noqa: E402

FILM = ROOT / "films/expensewaale"
EDITS = {
    "long": (FILM / "edl.json", FILM / "expensewaale_effort_levels.mp4"),
    "short": (FILM / "reel/edl.json", FILM / "reel/short_expensewaale_effort_levels.mp4"),
    "v1": (FILM / "edl_v1.json", None),                     # the v1 render is gone; transcript-only
}
# edl_v1's cropped sentence starts (fixture "about" + recut.py PATCH_WORDS restored their openings)
V1_BAD = {(2021, 388): "cropped start: dropped 'So when I first tested it out on low effort, so quickly,'",
          (2223, 2237): "cropped start: dropped 'But anyways, let's move to the next, which is the high mode.'"}


def main(argv):
    fx = json.loads((ROOT / "kit/cut/fixtures/expensewaale_joins.json").read_text())
    idmap = IdMap.parse("ew1=0,ew2=2000", 10000)
    use_media = "--media" in argv
    EVAL.mkdir(parents=True, exist_ok=True)
    table, rows, runtimes = {}, [], {}
    for name, (edl, media) in EDITS.items():
        t0 = time.time()
        res = cutcheck.check(edl, idmap, media=str(media) if (use_media and media and media.exists()) else None,
                             do_relisten="--no-relisten" not in argv)
        cutcheck.suggest(res, idmap, cutcheck.Takes_cache(idmap))
        runtimes[name] = round(time.time() - t0, 1)
        (EVAL / f"{name}.cutcheck.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
        by = {(j["left_id"], j["right_id"]): j for j in res["joins"]}
        labels = {(x["left_id"], x["right_id"]): x["label"] for x in fx.get(name, [])} if name != "v1" else \
            {k: "v1_cropped" for k in V1_BAD}
        for key, j in by.items():
            lab = labels.get(key)
            if lab is None and name != "v1":
                lab = "unlabelled"                           # a repair/aside the fixture does not list
            if lab is None:
                lab = "v1-other"
            rows.append({"edit": name, "t": j["t"], "left_id": key[0], "right_id": key[1], "label": lab, "kind": j["kind"],
                         "verdict": j["verdict"], "why": j["why"], "left": j["left"], "right": j["right"],
                         "relisten": j.get("relisten")})
        for key in labels:
            if key not in by:
                rows.append({"edit": name, "left_id": key[0], "right_id": key[1], "label": labels[key], "verdict": "NOT FOUND"})
        res_edges = [e for e in res["edges"] if e["verdict"] != "PASS"]
        for e in res_edges:
            rows.append({"edit": name, "t": None, "left_id": e["id"], "right_id": None, "label": f"edge-{e['side']}",
                         "verdict": e["verdict"], "why": e["why"]})
        table[name] = {"verdict": res["verdict"], "counts": res["counts"],
                       "trims": Counter(t["verdict"] for t in res["trims"])}
    # the score
    score = {}
    for lab in ("bad", "review", "ok_repair", "ok"):
        rr = [r for r in rows if r["label"] == lab]
        score[lab] = dict(Counter(r["verdict"] for r in rr), total=len(rr))
    v1 = [r for r in rows if r["label"] == "v1_cropped"]
    score["v1_cropped_starts"] = dict(Counter(r["verdict"] for r in v1), total=len(v1))
    ok = [r for r in rows if r["label"] in ("ok", "ok_repair")]
    score["false_positive_rate_ok"] = round(sum(r["verdict"] == "FAIL" for r in ok) / max(1, len(ok)), 3)
    score["review_rate_ok"] = round(sum(r["verdict"] == "REVIEW" for r in ok) / max(1, len(ok)), 3)
    bad = [r for r in rows if r["label"] == "bad"]
    score["bad_caught"] = f"{sum(r['verdict'] == 'FAIL' for r in bad)}/{len(bad)}"
    print(f"{'label':20s} {'FAIL':>5s} {'REVIEW':>7s} {'PASS':>5s} {'total':>6s}")
    for lab in ("bad", "v1_cropped_starts", "review", "ok_repair", "ok"):
        s = score[lab]
        print(f"{lab:20s} {s.get('FAIL', 0):5d} {s.get('REVIEW', 0):7d} {s.get('PASS', 0):5d} {s['total']:6d}")
    print(f"bad caught (FAIL): {score['bad_caught']}   ok/ok_repair FAIL rate: {score['false_positive_rate_ok']}   "
          f"ok/ok_repair REVIEW rate: {score['review_rate_ok']}")
    print("\nnot as labelled:")
    for r in rows:
        if r["label"] in ("bad", "v1_cropped") or r["label"] in ("ok", "ok_repair") and r["verdict"] != "PASS" \
                or r["label"] in ("unlabelled", "v1-other", "review") or r["label"].startswith("edge"):
            print(f"  [{r['edit']:5s}] {r['label']:10s} {r['verdict']:6s} {r['left_id']}->{r['right_id']}: {r.get('why', '')}")
    for name, tb in table.items():
        print(f"{name}: {tb['verdict']}  {tb['counts']}  trims {dict(tb['trims'])}  ({runtimes[name]} s)")
    (EVAL / "fixture_eval.json").write_text(json.dumps({"score": score, "edits": table, "runtimes_s": runtimes, "rows": rows},
                                                       indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
