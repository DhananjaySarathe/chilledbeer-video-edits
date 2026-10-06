import numpy as np
import pytest

from shorts import config
from shorts.analyze.align import Aligner, align_words
from shorts.analyze.audio import energy_db, levels, read_wav
from shorts.analyze.transcribe import RawWord, parse_whisper, transcribe
from shorts.analyze.words import OBVIOUS_FILLERS, bare, find_pauses, group_sentences, place_fillers, refine_words
from shorts.schemas import Word
from tests.media import pair_with_truth


def test_bare_and_fillers():
    assert bare("Uh,") == "uh" and bare("It's") == "it's"
    assert bare("Um...") in OBVIOUS_FILLERS and bare("like") not in OBVIOUS_FILLERS


def db_from(loud_ranges, n=200):
    db = np.full(n, -60.0, np.float32)
    for a, b in loud_ranges:
        db[a:b] = -20.0
    return db


def test_start_snaps_back_to_onset_and_end_forward_to_silence():
    raw = [RawWord("hello", 0.0, 0.3, 0.9), RawWord("there", 1.0, 1.1, 0.9)]
    db = db_from([(50, 90), (120, 160)])
    words = refine_words(raw, [(0.62, 0.88), (1.30, 1.58)], db, quiet_db=-40.0)
    assert (words[0].start, words[0].end) == (0.5, 0.9)
    assert (words[1].start, words[1].end) == (1.2, 1.6)
    assert words[0].start_gap and words[0].end_gap and words[1].start_gap and words[1].end_gap


def test_fused_words_have_no_gaps():
    raw = [RawWord("all", 0.0, 0.1, 0.9), RawWord("basically", 0.2, 0.3, 0.9)]
    db = db_from([(50, 160)])
    words = refine_words(raw, [(0.62, 1.05), (1.10, 1.58)], db, quiet_db=-40.0)
    assert words[0].start == 0.5 and words[0].end == 1.05 and not words[0].end_gap
    assert words[1].start == 1.05 and not words[1].start_gap


def test_gap_flags_tolerate_soft_noise_between_words():
    raw = [RawWord("a", 0.0, 0.1, 1), RawWord("b", 0.0, 0.1, 1)]
    db = db_from([(50, 90), (100, 140)])
    db[98] = -35.0                                        # a breath: not silent, but far below speech
    strict = refine_words(raw, [(0.5, 0.9), (1.02, 1.4)], db, quiet_db=-40.0)
    loose = refine_words(raw, [(0.5, 0.9), (1.02, 1.4)], db, quiet_db=-40.0, gap_db=-30.0)
    assert not strict[1].start_gap and loose[1].start_gap
    assert strict[1].start == loose[1].start == 1.0


def test_fillers_move_onto_their_own_sound():
    db = db_from([(20, 50), (80, 110), (111, 160)])      # "all", the real "uh", "basically" (dip at frame 110)
    texts = ["all,", "uh,", "basically"]
    squeezed = place_fillers(texts, [(0.2, 0.5), (0.52, 0.55), (1.13, 1.6)], db, dip_db=-30.0)
    assert squeezed[1] == pytest.approx((0.8, 1.1))
    right = place_fillers(texts, [(0.2, 0.5), (0.82, 1.08), (1.13, 1.6)], db, dip_db=-30.0)
    assert right[1] == pytest.approx((0.8, 1.1)) and right[0] == (0.2, 0.5)


def test_unaligned_word_is_placed_between_neighbours():
    raw = [RawWord("a", 0.0, 0.1, 1), RawWord("bb", 5.0, 5.1, 1), RawWord("c", 0.0, 0.1, 1)]
    db = db_from([(50, 60), (80, 90), (120, 130)])
    words = refine_words(raw, [(0.5, 0.6), None, (1.2, 1.3)], db, quiet_db=-40.0)
    assert not words[1].aligned
    assert words[0].end <= words[1].start < words[1].end <= words[2].start


def mk(texts, gap=0.05, dur=0.3):
    out, t = [], 0.0
    for i, s in enumerate(texts):
        out.append(Word(i=i, text=s, start=round(t, 3), end=round(t + dur, 3)))
        t += dur + gap
    return out


def test_sentences_break_on_punctuation_before_capital():
    sents = group_sentences(mk("So it's 3 p.m. in the afternoon. I woke up.".split()))
    assert [s.text for s in sents] == ["So it's 3 p.m. in the afternoon.", "I woke up."]
    assert sents[1].id == "s2" and sents[1].first == 7


def test_sentences_break_on_long_silence_and_length():
    words = mk(["one", "two"], gap=1.5)
    assert len(group_sentences(words)) == 2
    assert len(group_sentences(mk(["w"] * 90))) == 3


def test_find_pauses():
    words = mk(["a", "b", "c"], gap=0.05)
    words[2] = Word(i=2, text="c", start=words[1].end + 0.5, end=words[1].end + 0.8)
    pauses = find_pauses(words)
    assert [(p.after, round(p.duration, 2)) for p in pauses] == [(1, 0.5)]


@pytest.mark.slow
@pytest.mark.skipif(not (config.WHISPER_MODEL.exists() and config.ALIGN_MODEL.exists()), reason="run `uv run shorts setup` first")
def test_refined_times_match_ground_truth(truth_speech):
    wav, truth = truth_speech
    _, raw = parse_whisper(transcribe(config.tool("whisper-cli"), wav, wav.parent, language="en"))
    samples, sr = read_wav(wav)
    db = energy_db(samples, sr)
    quiet_db = levels(db)[2]
    aligner = Aligner()
    logp, frame_s = aligner.emissions(samples, sr)
    texts = [w.text for w in raw]
    spans = place_fillers(texts, align_words(logp, frame_s, texts, aligner.vocab, wildcard=OBVIOUS_FILLERS), db,
                          levels(db)[3])
    words = refine_words(raw, spans, db, quiet_db, gap_db=levels(db)[3])
    pairs = pair_with_truth([w.text for w in words], truth)
    assert len(pairs) >= 0.9 * len(truth)
    ds = np.array([abs(words[i].start - truth[j]["start"]) for i, j in pairs])
    de = np.array([abs(words[i].end - truth[j]["end"]) for i, j in pairs])
    assert ds.mean() < 0.07 and de.mean() < 0.06 and (ds < 0.08).mean() >= 0.75
