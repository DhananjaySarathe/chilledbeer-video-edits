import numpy as np
import pytest

from shorts import config
from shorts.analyze.align import Aligner, align_words, ctc_align, normalize_word
from shorts.analyze.audio import read_wav
from shorts.analyze.transcribe import parse_whisper, transcribe
from tests.media import pair_with_truth

models_ready = config.WHISPER_MODEL.exists() and config.ALIGN_MODEL.exists()


def test_normalize_word():
    assert normalize_word("It's") == "IT'S"
    assert normalize_word("3") == "THREE"
    assert normalize_word("p.m.") == "PM"
    assert normalize_word("—") == ""


def synthetic_logp():
    T, V = 20, 10
    lp = np.full((T, V), np.log(1e-3), np.float32)
    lp[:, 0] = np.log(0.9)                        # blank most of the time
    for frame, tok in ((5, 7), (9, 8), (13, 4)):  # A at frame 5, O at 9, separator at 13
        lp[frame, tok] = np.log(0.95)
        lp[frame, 0] = np.log(0.02)
    return lp


def test_ctc_align_places_tokens_where_they_are_emitted():
    spans = ctc_align(synthetic_logp(), [4, 7, 8, 4], blank=0)
    assert spans is not None
    assert spans[1][0] in (5, 6)
    assert spans[2][0] in (9, 10)


def test_ctc_align_refuses_transcripts_longer_than_audio():
    assert ctc_align(np.zeros((3, 10), np.float32), [4, 7, 8, 7, 4], blank=0) is None


def test_align_words_maps_characters_back_to_words():
    vocab = {"<pad>": 0, "|": 4, "A": 7, "O": 8}
    out = align_words(synthetic_logp(), 0.02, ["A", "o", "?"], vocab)
    assert out[2] is None
    assert out[0][0] < out[1][0]


def test_fillers_align_to_whatever_letter_is_heard():
    T, V = 24, 32
    lp = np.full((T, V), np.log(1e-4), np.float32)
    lp[:, 0] = np.log(0.9)
    for frame, tok in ((5, 7), (12, 5), (18, 8)):   # "a" at 5; the filler sounds like "E" at 12; "o" at 18
        lp[frame, tok] = np.log(0.95)
        lp[frame, 0] = np.log(0.02)
    vocab = {"<pad>": 0, "|": 4, "E": 5, "A": 7, "O": 8, "H": 11, "U": 20}
    out = align_words(lp, 0.02, ["a", "uh", "o"], vocab, wildcard=frozenset({"uh"}))
    assert out[1][0] == pytest.approx(0.26, abs=0.021)
    assert out[0][1] <= out[1][0] < out[2][0]


@pytest.mark.slow
@pytest.mark.skipif(not models_ready, reason="run `uv run shorts setup` first")
def test_aligner_word_ends_match_ground_truth(truth_speech):
    wav, truth = truth_speech
    _, raw = parse_whisper(transcribe(config.tool("whisper-cli"), wav, wav.parent, language="en"))
    pairs = pair_with_truth([w.text for w in raw], truth)
    assert len(pairs) >= 0.9 * len(truth)
    samples, sr = read_wav(wav)
    aligner = Aligner()
    logp, frame_s = aligner.emissions(samples, sr)
    spans = align_words(logp, frame_s, [w.text for w in raw], aligner.vocab, wildcard=frozenset({"uh", "um"}))
    ends = np.array([abs(spans[i][1] - truth[j]["end"]) for i, j in pairs])
    starts = np.array([abs(spans[i][0] - truth[j]["start"]) for i, j in pairs])
    assert ends.mean() < 0.06 and (ends < 0.08).mean() >= 0.85
    assert starts.mean() < 0.15
