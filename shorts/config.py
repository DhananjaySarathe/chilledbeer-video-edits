"""Paths, tool lookup and tunable constants for ChilledBeer Video Edits."""
from __future__ import annotations

import shutil
from pathlib import Path

from dotenv import load_dotenv

from shorts.errors import ShortsError

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "kit"
MODELS = KIT / "models"
FONTS = KIT / "fonts"
QUESTIONS = KIT / "questions"
# Everything the pipeline generates lives under output/ (gitignored). Same layout as kit/paths.py (films use that one).
#   output/final/<name>/  deliverables: the finished video, its contact sheet (keep)
#   output/jobs/<name>/   one take: the footage copy (source.mp4) + transcript + edit decisions (keep while re-editing)
#   output/temp/          everything else: audio, frames, previews, logs, caches (delete any time)
OUTPUT = ROOT / "output"
JOBS = OUTPUT / "jobs"
TEMP = OUTPUT / "temp"
FINAL = OUTPUT / "final"
CACHE = TEMP / "cache"
LEGACY_JOBS = ROOT / "jobs"   # takes made before 2026-10-07 keep the old one-folder layout (jobs/<name>/work/...)

load_dotenv(ROOT / ".env")

# Output frame and platform safe zones (fractions of the frame kept clear of key text).
OUT_W, OUT_H = 1080, 1920
SAFE_TOP, SAFE_BOTTOM, SAFE_LEFT, SAFE_RIGHT = 0.14, 0.35, 0.06, 0.12

# Model files (downloaded by `shorts setup`).
WHISPER_MODEL = MODELS / "ggml-large-v3-turbo-q5_0.bin"
ALIGN_MODEL = MODELS / "wav2vec2-base-960h-int8.onnx"
ALIGN_VOCAB = MODELS / "wav2vec2-base-960h-vocab.json"
FACE_MODEL = MODELS / "face_detection_yunet_2023mar.onnx"
TURN_MODEL = MODELS / "smart-turn-v3.2-cpu.onnx"        # kit/cut: end-of-utterance (Pipecat Smart Turn v3.2, BSD-2)
VAD_MODEL = MODELS / "silero_vad.onnx"                 # kit/cut: pauses (Silero VAD, MIT)
HYPERFRAMES_VERSION = "0.8.134"                         # the renderer every film so far was made with; setup.sh installs exactly this
BIN = KIT / "bin"                                      # Apple Vision tools, compiled by `shorts setup` (gitignored)

# Whisper drops fillers ("uh", "um") unless the prompt itself contains them. This prompt keeps
# fillers AND gives proper casing and punctuation (measured on the first sample, 2026-09-26).
WHISPER_PROMPT = ("Umm, so, uh, today I'm testing, like, a new app. Uh, honestly? "
                  "It's, um, amazing. So yeah, let's see.")
# Hindi speech: whisper's "hi" output is Devanagari or an invented English translation, but English decoding
# primed with romanized Hinglish writes what was said in Latin script (measured on video2, 2026-09-27).
HINDI_LANGS = ("hi", "ur")
HINGLISH_PROMPT = ("Toh, umm, basically main aaj ek naya hack try kar raha hoon. Matlab, maine apna room thoda "
                   "set kiya hai, aur uh, focus bahut badh gaya hai. Dekho, yeh jagah hai jahan main kaam karunga.")
# second try for a chunk the first prompt under-transcribed (whisper's skips depend on the prompt)
HINGLISH_PROMPT_ALT = ("Haan toh dekho, aaj maine ek funny cheez observe ki. Hum hamesha poochte hain ki kitna "
                       "time lagega. Matlab, yaar, bas itna batao, theek hai?")

# Jev (TypeSafe System One) is optional: with no TYPESAFE_API_KEY, Claude answers the zoom-in questions and directs the
# graphics from the beats alone (README "Jev is optional").
def jev_enabled() -> bool:
    import os
    return bool(os.environ.get("TYPESAFE_API_KEY", "").strip())


# Jev routing.
APPLY_THRESHOLD = 0.9       # act on an answer without asking Claude
PUNCH_IN_THRESHOLD = 0.7    # cosmetic: zoom in only when Jev is fairly sure

# Editing.
MIN_SEGMENT_S = 0.4         # shorter segments look like glitches
PAUSE_KEEP_S = 0.12         # least silence around a cut (lead + tail)
# silence kept when a pause is trimmed, by where it falls (pro editors: 150-250 ms inside a sentence, 300-450 ms
# between sentences; 120 ms everywhere made Hinglish sound rushed and chopped phrases, video2 2026-09-27)
PHRASE_GAP_S = 0.2
CLAUSE_GAP_S = 0.25         # after a comma
SENTENCE_GAP_S = 0.35       # after . ? !
CUT_MARGIN_S = 0.15         # a pause is only cut when it is this much longer than what would be kept
ZOOM_MIN_SEG_S = 1.2        # a piece shorter than this keeps the framing (flipping for under a second flickers)
CLOSE_CUTS_S = 1.2          # two visible cuts closer than this should be covered by a graphic
ZOOM_CUT_EVERY_S = 4.0      # a long take gets a framing change about this often, at a sentence or clause break
ZOOM_CUT_MIN_S = 2.5        # (no time is removed: it is a "zoom cut", pieces stay at least this long)
DELIBERATE_PAUSE_MAX_S = 0.6
# style.pace: (phrase, clause, sentence, cut margin, zoom cut every). "fast" is for reels; it stays above the 120 ms
# that sounded chopped on Hinglish (video2), and style.speed compresses it a little more.
PACES = {"normal": (PHRASE_GAP_S, CLAUSE_GAP_S, SENTENCE_GAP_S, CUT_MARGIN_S, ZOOM_CUT_EVERY_S),
         "fast": (0.17, 0.19, 0.26, 0.08, 2.8)}
COLD_OPEN_TAIL_S = 0.3      # beat left after the teaser line, under the rewind transition
LEAD_S = 0.05               # audio kept before a word when the cut sits in silence
TAIL_S = 0.07               # audio kept after a word when the cut sits in silence
AUDIO_FADE_S = 0.01
LOUDNESS_I, LOUDNESS_TP = -14.0, -1.0

_FORMULA = {"ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "whisper-cli": "whisper-cpp", "node": "node"}
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def tool(name: str) -> str:
    """Absolute path of a command-line tool, or a clear error saying how to install it."""
    path = shutil.which(name)
    if not path:
        raise ShortsError("E_TOOL_MISSING", f"{name} is not installed or not on PATH.",
                          f"brew install {_FORMULA.get(name, name)}")
    return path
