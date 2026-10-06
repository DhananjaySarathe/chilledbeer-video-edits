"""Fast unit tests for kit/cut (no models, no media): uv run pytest kit/cut -q"""
from kit.cut.boundaries import Boundaries
from kit.cut.common import IdMap
from kit.cut.cutcheck import apply_relisten, judge_cut, repair_kind
from kit.cut.sentmap import SentMap, label_of


def take(text: str, ends: dict[int, float]):
    """A fake take: words of `text`, p_boundary 0.001 after every word except the given ones."""
    words = text.split()
    gaps = [{"after": k, "left": w, "right": words[k + 1] if k + 1 < len(words) else None, "p": ends.get(k, 0.001)}
            for k, w in enumerate(words)]
    for g in gaps:
        g["label"] = label_of(g["p"])
    sm = SentMap({"gaps": gaps})
    return Boundaries("fake", sm), [{"text": w} for w in words], [0.9] * len(words)


def test_idmap():
    m = IdMap.parse("ew1=0,ew2=2000", 10000)
    assert m.resolve(5) == ("ew1", 5, False)
    assert m.resolve(2522) == ("ew2", 522, False)
    assert m.resolve(12522) == ("ew2", 522, True)
    assert m.to_id("ew2", 10) == 2010


def test_repairs():
    _, W, _ = take("asking him to use your, uh, your approach", {})
    assert repair_kind(W, 4, 7).startswith("restart")          # "use | your, uh, | your approach"
    _, W, _ = take("first it read the code, it took me a new check, it took me a proper plan", {})
    assert "it took me a" in repair_kind(W, 4, 11)
    _, W, _ = take("I tested it on low effort, so quickly it was done", {})
    assert repair_kind(W, 5, 8) is None                         # dropping "so quickly" is content, not a repair


def test_sentence_to_sentence_passes():
    B, W, P = take("it is live. So I gave a prompt. The beauty is this.", {2: 0.99, 7: 0.95, 10: 1.0})
    assert judge_cut(B, W, P, 2, 8, False, "a", "a")["verdict"] == "PASS"


def test_half_and_half_fails():
    text = "it will launch a lot of agents, and many agents research. Then it is a whole, you can say, you are launching a team"
    B, W, P = take(text, {10: 0.9})
    v = judge_cut(B, W, P, 6, 19, False, "a", "a")             # "...agents," || "you are launching..."
    assert v["verdict"] == "FAIL" and v["cat"] == "half"


def test_cropped_start_fails():
    B, W, P = take("let us go one by one. So when I tested it on low, so quickly it took six minutes", {5: 0.97})
    B2, W2, P2 = take("first is low effort, right? Next", {4: 0.95})
    v = judge_cut(B2, W2, P2, 4, 15, True, "b", "a", B, W)    # "...right?" || "it took six minutes" (cropped)
    assert v["verdict"] == "FAIL"
    v = judge_cut(B2, W2, P2, 4, 13, True, "b", "a", B, W)    # "...right?" || "so quickly it took..." (cropped too)
    assert v["verdict"] == "FAIL"


def test_connector_end_fails():
    B, W, P = take("I asked the model to do the work. Done.", {7: 0.9})
    assert judge_cut(B, W, P, 6, 8, True, "a", "a")["cat"] == "lexicon"   # ends on "the"


def test_dropped_conditional_is_review():
    text = "right? But still, if you want to see the approach, then I will say, try ultracode."
    B, W, P = take(text, {0: 0.99, 15: 1.0})
    v = judge_cut(B, W, P, 2, 11, False, "a", "a")              # "But still," || "I will say, ..."
    assert v["verdict"] == "REVIEW" and v["cat"] == "aside"


def test_snap_and_restart():
    B, _, _ = take("one. So when I first tested it on low effort, so quickly it took six minutes. Next", {0: 0.99, 15: 0.97})
    assert B.snap(10, 12) == (1, 15)
    assert B.snap(10, 12, mode="shrink") == (None, None)
    assert B.restart_cut(12) == 0


def test_relisten_never_rescues_a_fail():
    j = {"kind": "cut", "verdict": "FAIL", "cat": "half", "why": "x"}
    apply_relisten(j, {"anchored": True, "mark": ".", "boundary_sat": 0.9, "left_heard": True, "right_heard": True,
                       "extra": [], "missing": [], "heard": "a. | b"})
    assert j["verdict"] == "FAIL"
    j = {"kind": "cut", "verdict": "REVIEW", "cat": "clause", "why": "x"}
    apply_relisten(j, {"anchored": True, "mark": ".", "boundary_sat": 0.9, "left_heard": True, "right_heard": True,
                       "extra": [], "missing": [], "heard": "a. | b"})
    assert j["verdict"] == "PASS"
