import json
import subprocess
from pathlib import Path

import pytest

from shorts import config
from shorts.analyze.audio import extract_wav
from shorts.analyze.transcribe import parse_whisper, transcribe, whisper_cmd

FIXTURE = Path(__file__).parent / "fixtures" / "whisper_mini.json"


def test_parse_joins_subwords_and_drops_specials():
    lang, words = parse_whisper(json.loads(FIXTURE.read_text()))
    assert lang == "en"
    assert [w.text for w in words] == ["So,", "it's", "3", "p.m.", "uh"]
    assert words[1].start == 0.45 and words[1].end == 0.60 and words[1].p == 0.95
    assert words[3].start == 0.86 and words[3].end == 1.43


def test_whisper_cmd_uses_filler_prompt():
    cmd = whisper_cmd("whisper-cli", Path("a.wav"), Path("out/whisper"))
    assert cmd[cmd.index("--prompt") + 1] == config.WHISPER_PROMPT
    assert "-ojf" in cmd and cmd[cmd.index("-l") + 1] == "auto"
    assert "-dtw" not in cmd


@pytest.mark.slow
@pytest.mark.skipif(not config.WHISPER_MODEL.exists(), reason="run `uv run shorts setup` first")
def test_transcribes_say_speech_and_caches(tmp_path):
    subprocess.run(["say", "-v", "Samantha", "-o", str(tmp_path / "s.aiff"), "Hello there. This is a quick test."], check=True)
    wav = extract_wav("ffmpeg", str(tmp_path / "s.aiff"), tmp_path / "s.wav")
    data = transcribe(config.tool("whisper-cli"), wav, tmp_path, language="en")
    lang, words = parse_whisper(data)
    assert lang == "en"
    assert "hello" in " ".join(w.text.lower() for w in words)
    stamp = (tmp_path / "whisper.json").stat().st_mtime
    transcribe(config.tool("whisper-cli"), wav, tmp_path, language="en")
    assert (tmp_path / "whisper.json").stat().st_mtime == stamp   # cached: whisper did not run again


def test_hinglish_decodes_as_english_primed_with_romanized_hindi():
    cmd = whisper_cmd("whisper-cli", Path("a.wav"), Path("out/whisper-hinglish"), language="hinglish")
    assert cmd[cmd.index("-l") + 1] == "en" and cmd[cmd.index("--prompt") + 1] == config.HINGLISH_PROMPT


def _wav(path, seconds=20.0, sr=16000):
    import wave
    import numpy as np
    t = np.arange(int(seconds * sr)) / sr
    speech = (np.sin(2 * np.pi * 180 * t) * 0.3 * ((t % 5.0) < 4.0)).astype(np.float32)   # 4 s talk, 1 s pause
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((speech * 32767).astype("int16").tobytes())
    return path


def _raw(texts):
    from shorts.analyze.transcribe import RawWord
    return [RawWord(t, i * 0.3, i * 0.3 + 0.25, 0.9) for i, t in enumerate(texts)]


def test_loops_collapse_but_real_doubles_stay():
    from shorts.analyze.transcribe import collapse_loops
    words = _raw("uske baad, uske baad, uske baad, uske baad suh raha hai baar baar".split())
    assert [w.text for w in collapse_loops(words)] == "uske baad, suh raha hai baar baar".split()
    assert [w.text for w in collapse_loops(_raw("no no no".split()))] == ["no", "no", "no"]


def test_prompt_echo_is_dropped():
    from shorts.analyze.transcribe import drop_prompt_echo
    words = _raw("haan matlab, yaar, bas itna batao, theek hai? chalo".split())
    kept = drop_prompt_echo(words, "Matlab, yaar, bas itna batao, theek hai?")
    assert [w.text for w in kept] == ["haan", "chalo"]


def test_speech_chunks_cut_in_the_pauses_within_bounds():
    import numpy as np
    from shorts.analyze.transcribe import speech_chunks
    t = np.arange(0, 20, 0.01)
    db = np.where((t % 5.0) < 4.0, -20.0, -60.0)             # pauses at 4-5, 9-10, 14-15 s
    chunks = speech_chunks(db)
    assert chunks[0][0] == 0.0 and chunks[-1][1] == 20.0
    assert all(2.0 <= b - a <= 8.0 for a, b in chunks)
    assert all(((b % 5.0) >= 4.0) for _, b in chunks[:-1])     # every cut lands in a pause


def test_auto_sends_hindi_sounding_speech_to_chunked_hinglish(tmp_path, monkeypatch):
    import shorts.analyze.transcribe as tr
    wav = _wav(tmp_path / "a.wav")
    calls = []

    class Done:
        def __init__(self, err=""):
            self.stderr = err

    def fake_run(cmd, **kw):
        if "-of" in cmd:                                     # the whole-clip pass says English
            calls.append("full")
            Path(cmd[cmd.index("-of") + 1]).with_suffix(".json").write_text(
                json.dumps({"result": {"language": "en"}, "transcription": []}))
            return Done()
        files = [Path(cmd[i + 1]) for i, c in enumerate(cmd) if c == "-f"]
        if "-dl" in cmd:
            calls.append("detect")
            return Done("whisper_full_with_state: auto-detected language: en (p = 0.7)\n"
                        "whisper_full_with_state: auto-detected language: hi (p = 0.55)\n")
        calls.append(f"decode{len(files)}")
        for f in files:
            toks = [{"text": f" shabd{i}", "p": 0.9, "offsets": {"from": i * 300, "to": i * 300 + 250}} for i in range(12)]
            Path(str(f) + ".json").write_text(json.dumps({"result": {"language": "en"},
                                                          "transcription": [{"tokens": toks}]}))
        return Done()
    monkeypatch.setattr(tr, "run", fake_run)
    data = transcribe("whisper-cli", wav, tmp_path)
    lang, words = parse_whisper(data)
    assert lang == "hinglish" and calls[0] == "detect" and calls[1].startswith("decode") and "full" not in calls
    starts = [c["start"] for c in data["chunks"]]
    assert len(starts) >= 3 and words[12].start == pytest.approx(starts[1])      # chunk 2's words shifted to the clip
    n = len(calls)
    transcribe("whisper-cli", wav, tmp_path)
    assert len(calls) == n                                                        # everything cached: no whisper runs
