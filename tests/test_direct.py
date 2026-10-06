from shorts.decide.run import decide
from shorts.direct.run import NEW, SPEAKER, beats, direct
from shorts.plan.run import plan
from tests.factories import FakeAsker, choice, make_analysis, make_job, noul


def w(i, text, start, end):
    return {"i": i, "text": text, "start": start, "end": end}


def test_beats_break_at_sentences_and_split_long_clauses_at_clause_words():
    words = [w(0, "Hello", 0.0, 0.4), w(1, "there.", 0.45, 1.0),
             w(2, "I", 1.1, 1.3), w(3, "built", 1.35, 1.8), w(4, "this", 1.85, 2.2), w(5, "tool", 2.25, 2.7),
             w(6, "and", 2.75, 3.0), w(7, "it", 3.05, 3.3), w(8, "edits", 3.35, 3.9), w(9, "videos", 3.95, 4.6),
             w(10, "by", 4.65, 4.9), w(11, "itself.", 4.95, 5.6)]
    bs = beats(words)
    assert [b["text"] for b in bs] == ["Hello there.", "I built this tool", "and it edits videos by itself."]
    assert bs[0]["end"] == bs[1]["start"]


def test_tiny_pieces_merge_into_a_neighbour():
    words = [w(0, "So,", 0.0, 0.3), w(1, "this", 0.35, 0.6), w(2, "works.", 0.65, 1.2)]
    assert [b["text"] for b in beats(words)] == ["So, this works."]


TEXT = "So today I am testing a new app. Uh basically it is amazing. It edits videos by itself."
ALL_NO = {"false_start:s1": noul(0.02), "false_start:s2": noul(0.02), "filler:0": noul(0.02), "filler:9": noul(0.02)}


def test_direct_writes_a_draft_and_never_repeats_a_template(jobs_root):
    job = make_job("dj", make_analysis(TEXT))
    decide(job, FakeAsker(ALL_NO))
    plan(job)
    fav = {"stat_chart": 0.7, SPEAKER: 0.2, "chat_thread": 0.1}
    fake = FakeAsker({f"b{k}": choice("stat_chart", fav) for k in range(1, 12)})
    out = direct(job, fake)
    draft = job.read("visuals_draft.json")["beats"]
    picks = [d["pick"] for d in draft]
    assert len(draft) == out["beats"] >= 2
    assert all(a != b or a == SPEAKER for a, b in zip(picks, picks[1:]))
    q = next(iter(fake.questions.values()))
    assert q["type"] == "choice" and SPEAKER in q["criteria"] and NEW in q["criteria"] and "stat_chart" in q["criteria"]
    assert "captions_box" not in q["criteria"]
    first_stat = next(d for d in draft if d["pick"] == "stat_chart")
    assert "to" in first_stat["params"] and first_stat["duration"]["max"] > 0


def test_non_english_takes_get_beats_without_jev(jobs_root):
    job = make_job("dh", make_analysis(TEXT))
    a = job.read("analysis.json"); a["language"] = "hinglish"; job.write("analysis.json", a)
    decide(job, FakeAsker(ALL_NO))
    plan(job)
    fake = FakeAsker({})
    out = direct(job, fake)
    assert fake.questions == {} and out["jev_skipped"] and out["beats"] >= 2
    assert all(b["pick"] is None for b in job.read("visuals_draft.json")["beats"])


def test_without_a_jev_key_english_takes_get_beats_only(jobs_root, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    job = make_job("dn", make_analysis(TEXT))
    decide(job, FakeAsker(ALL_NO))
    plan(job)
    out = direct(job)                                   # no asker, no key: nothing to call
    assert "TYPESAFE_API_KEY" in out["jev_skipped"] and out["jev_error"] is None and out["beats"] >= 2
    assert all(b["pick"] is None for b in job.read("visuals_draft.json")["beats"])
