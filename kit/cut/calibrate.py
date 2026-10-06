"""Calibrate the boundary model on the hand-labelled gaps (kit/cut/fixtures/expensewaale_boundaries.json).

    uv run python -m kit.cut.calibrate [--fit]     -> per-feature AUC, the current model's scores, and (--fit) a fitted
                                                     logistic model with take-to-take cross-validation; kit/cut/eval/calibrate.json

S gaps are positives; N and unlisted gaps negatives; C gaps are left out of the score (they are legitimately either).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.cut.common import EVAL, ROOT  # noqa: E402
from kit.cut import sentmap  # noqa: E402

GOLD = ROOT / "kit/cut/fixtures/expensewaale_boundaries.json"


def auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    # average ties
    allv = np.concatenate([pos, neg])
    for v in np.unique(allv):
        m = allv == v
        ranks[m] = ranks[m].mean()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def dataset(jobs=("ew1", "ew2")):
    gold = json.loads(GOLD.read_text())
    rows = []
    for job in jobs:
        sm = sentmap.build(job)
        lab = gold[job]
        for g in sm["gaps"]:
            k = g["after"]
            cls = "S" if k in lab["S"] else "C" if k in lab["C"] else "N" if k in lab["N"] else "-"
            rows.append((job, k, cls, g))
    return rows


def report(rows, weights=None):
    out = {}
    for job in sorted({r[0] for r in rows}) + ["all"]:
        rr = [r for r in rows if (job == "all" or r[0] == job) and r[2] != "C"]
        y = [1 if r[2] == "S" else 0 for r in rr]
        ps = [sentmap.p_boundary(r[3], weights or sentmap.WEIGHTS) for r in rr]
        res = {"n": len(rr), "pos": sum(y), "auc": round(auc(y, ps), 4)}
        for th in (sentmap.P_CLAUSE, sentmap.P_SENT):
            tp = sum(1 for yy, p in zip(y, ps) if yy and p >= th)
            fp = sum(1 for yy, p in zip(y, ps) if not yy and p >= th)
            res[f"recall@{th}"] = round(tp / max(1, sum(y)), 3)
            res[f"precision@{th}"] = round(tp / max(1, tp + fp), 3)
        nn = [(p, r) for r, p in zip(rr, ps) if r[2] == "N"]
        res["N_over_clause"] = [f"{r[0]}:{r[1]} {p:.2f}" for p, r in nn if p >= sentmap.P_CLAUSE]
        out[job] = res
    return out


def main(argv):
    rows = dataset()
    feats = list(sentmap.design(rows[0][3]).keys())
    print("per-feature AUC (S vs N+unlisted, C excluded):")
    rr = [r for r in rows if r[2] != "C"]
    y = np.array([1 if r[2] == "S" else 0 for r in rr])
    X = np.array([[sentmap.design(r[3])[f] for f in feats] for r in rr])
    for j, f in enumerate(feats):
        a = auc(y, X[:, j])
        print(f"  {f:12s} {a:.3f}" + ("" if j % 1 else ""))
    for job in ("ew1", "ew2"):
        m = np.array([r[0] == job for r in rr])
        print(f"  [{job}] sat {auc(y[m], X[m, feats.index('sat')]):.3f}  sat_p {auc(y[m], X[m, feats.index('sat_p')]):.3f}  "
              f"turn {auc(y[m], X[m, feats.index('turn')]):.3f}  pause {auc(y[m], X[m, feats.index('pause')]):.3f}")
    print("current model:", json.dumps(report(rows), indent=1))
    result = {"current": report(rows)}
    if "--fit" in argv:
        from sklearn.linear_model import LogisticRegression
        fitted = {}
        for train, test in (("ew1", "ew2"), ("ew2", "ew1"), ("all", "all")):
            mt = np.array([train == "all" or r[0] == train for r in rr])
            clf = LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced").fit(X[mt], y[mt])
            w = {"bias": float(clf.intercept_[0]), **{f: float(c) for f, c in zip(feats, clf.coef_[0])}}
            me = np.array([test == "all" or r[0] == test for r in rr])
            s = clf.decision_function(X[me])
            print(f"fit on {train} -> test {test}: AUC {auc(y[me], s):.3f}")
            fitted[f"{train}->{test}"] = {"weights": {k: round(v, 2) for k, v in w.items()}, "auc": round(auc(y[me], s), 4)}
        print(json.dumps(fitted["all->all"]["weights"], indent=1))
        result["fitted"] = fitted
    EVAL.mkdir(parents=True, exist_ok=True)
    (EVAL / "calibrate.json").write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
