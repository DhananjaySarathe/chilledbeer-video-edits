"""Exact word timing. A small wav2vec2 model (int8 ONNX, CPU) aligns Whisper's words to the audio.
Whisper's own word times were ~0.5 s off on real footage; aligned word ends land within ~35 ms."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from shorts import config

_DIGITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]


def normalize_word(word: str) -> str:
    s = re.sub(r"\d", lambda m: _DIGITS[int(m.group())], word.upper().replace("&", "AND"))
    return re.sub(r"[^A-Z']", "", s)


def log_softmax(x: np.ndarray) -> np.ndarray:
    m = x.max(axis=-1, keepdims=True)
    return x - m - np.log(np.exp(x - m).sum(axis=-1, keepdims=True))


def ctc_align(logp: np.ndarray, tokens: list[int], blank: int) -> list[tuple[int, int]] | None:
    """Viterbi forced alignment (the torchaudio tutorial variant). tokens[0] must be the word separator.
    Returns (first_frame, last_frame) per token, or None when the transcript cannot fit the audio."""
    T, N = logp.shape[0], len(tokens)
    if N == 0 or N > T:
        return None
    tok = np.asarray(tokens)
    trellis = np.zeros((T, N), dtype=np.float32)
    trellis[1:, 0] = np.cumsum(logp[1:, blank])
    trellis[0, 1:] = -np.inf
    trellis[T - N + 1:, 0] = np.inf
    for t in range(T - 1):
        trellis[t + 1, 1:] = np.maximum(trellis[t, 1:] + logp[t, blank], trellis[t, :-1] + logp[t, tok[1:]])
    t, j = T - 1, N - 1
    path = [(j, t)]
    while j > 0 and t > 0:
        stayed = trellis[t - 1, j] + logp[t - 1, blank]
        changed = trellis[t - 1, j - 1] + logp[t - 1, tok[j]]
        t -= 1
        if changed > stayed:
            j -= 1
        path.append((j, t))
    if j > 0:
        return None
    first: dict[int, int] = {}
    last: dict[int, int] = {}
    for jj, tt in reversed(path):
        first.setdefault(jj, tt)
        last[jj] = tt
    return [(first[k], last[k]) for k in range(N)]


def load_vocab(path: Path = config.ALIGN_VOCAB) -> dict[str, int]:
    return json.loads(Path(path).read_text())


def align_words(logp: np.ndarray, frame_s: float, words: list[str], vocab: dict[str, int],
                wildcard: frozenset[str] = frozenset()) -> list[tuple[float, float] | None]:
    """Word spans in seconds. Words in `wildcard` (fillers like "uh", which this read-speech model barely knows)
    match whatever letter is heard, so they land on their real sound instead of squeezing into a neighbour."""
    sep, blank = vocab["|"], vocab["<pad>"]
    letters = [i for tok, i in vocab.items() if len(tok) == 1 and tok != "|"]
    star = logp.shape[1]
    logp = np.concatenate([logp, logp[:, letters].max(axis=1, keepdims=True)], axis=1)
    tokens, owner = [sep], [-1]
    for i, w in enumerate(words):
        if re.sub(r"[^a-z']", "", w.lower()) in wildcard:
            ids = [star]
        else:
            ids = [vocab[c] for c in normalize_word(w) if c in vocab]
        if not ids:
            continue
        for t in ids:
            tokens.append(t)
            owner.append(i)
        tokens.append(sep)
        owner.append(-1)
    out: list[tuple[float, float] | None] = [None] * len(words)
    spans = ctc_align(logp, tokens, blank)
    if spans is None:
        return out
    for k, (f0, f1) in enumerate(spans):
        i = owner[k]
        if i < 0:
            continue
        s, e = f0 * frame_s, (f1 + 1) * frame_s
        out[i] = (min(out[i][0], s), max(out[i][1], e)) if out[i] else (s, e)
    return out


class Aligner:
    FRAME = 320   # wav2vec2 output stride in samples at 16 kHz (20 ms)

    def __init__(self, model: Path = config.ALIGN_MODEL, vocab: Path = config.ALIGN_VOCAB, threads: int = 4):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(model), opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.vocab = load_vocab(vocab)

    def _logp(self, x: np.ndarray) -> np.ndarray:
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        return log_softmax(self.session.run(None, {self.input_name: x[None, :].astype(np.float32)})[0][0])

    def emissions(self, samples: np.ndarray, sr: int = 16000, chunk_s: float = 15.0,
                  context_s: float = 1.0) -> tuple[np.ndarray, float]:
        """Log-probabilities per ~20 ms frame for the whole clip. Long audio is processed in overlapping chunks,
        because the model's attention cost grows with the square of the input length."""
        if sr != 16000:
            raise ValueError("the aligner needs 16 kHz audio")
        n, chunk, ctx = len(samples), int(chunk_s * sr), int(context_s * sr)
        if n <= chunk + ctx:
            lp = self._logp(samples)
        else:
            parts = []
            for start in range(0, n, chunk):
                end = min(n, start + chunk)
                a, b = max(0, start - ctx), min(n, end + ctx)
                lp_chunk = self._logp(samples[a:b])
                fa = (start - a) // self.FRAME
                parts.append(lp_chunk[fa: fa + (end - start) // self.FRAME])
            lp = np.concatenate(parts)
        return lp, (n / sr) / len(lp)
