"""The JSON files a job produces, as pydantic models. Every command reads and writes these."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Word(BaseModel):
    i: int
    text: str
    start: float
    end: float
    p: float = 1.0
    aligned: bool = True
    start_gap: bool = False     # a real quiet stretch (>= 30 ms) comes right before the word
    end_gap: bool = False       # a real quiet stretch comes right after the word


class Sentence(BaseModel):
    id: str
    first: int
    last: int
    text: str
    start: float
    end: float


class Pause(BaseModel):
    after: int
    start: float
    end: float
    duration: float


class Loudness(BaseModel):
    integrated: float | None = None
    lra: float | None = None
    true_peak: float | None = None


class FaceBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class TimeRange(BaseModel):
    start: float
    end: float


class Picture(BaseModel):
    fps: float
    face_presence: float
    face_box: FaceBox | None = None
    face_track: list[list[float] | None] = []
    blurry: list[TimeRange] = []
    dark: list[TimeRange] = []
    no_face: list[TimeRange] = []
    scene_changes: list[float] = []


class SourceInfo(BaseModel):
    path: str
    working_path: str
    duration: float
    fps: int
    frames: int
    width: int
    height: int
    normalized: bool


class Analysis(BaseModel):
    version: Literal[1] = 1
    source: SourceInfo
    language: str
    words: list[Word]
    sentences: list[Sentence]
    pauses: list[Pause]
    speech_db: float
    floor_db: float
    quiet_db: float
    dip_db: float
    loudness: Loudness
    picture: Picture
    contact_sheet: str
    warnings: list[str] = []


HEX = r"^#[0-9A-Fa-f]{6}$"


class VisualNote(BaseModel):
    start: float
    end: float
    note: str


class Target(BaseModel):
    min: float = 20.0
    max: float = 60.0


class Brief(BaseModel):
    """Written by Claude after reading the transcript and contact sheet."""
    version: Literal[1] = 1
    topic: str = ""                                   # one line: what the video is about (helps Jev)
    target: Target = Target()                         # desired length of the short, in seconds
    visual_notes: list[VisualNote] = []               # what Claude saw, e.g. "looks off camera"
    caption_overrides: dict[int, str] = {}            # word index -> caption text (Hinglish respelling, fixes)
    cut_words: list[tuple[int, int]] = []             # inclusive word ranges to cut, e.g. a restart inside a sentence
    cold_open: tuple[int, int] | None = None          # inclusive word range played first as a teaser (flash-forward),
                                                      # then the story starts from the top; the words play again later


class Style(BaseModel):
    """The look of this short, designed by Claude per video."""
    version: Literal[1] = 1
    caption_template: Literal["bold_pop", "clean_karaoke"] = "bold_pop"
    font: str = "Montserrat-800.ttf"
    font_size: int = Field(88, ge=40, le=160)
    text_color: str = Field("#FFFFFF", pattern=HEX)
    highlight_color: str = Field("#FFD400", pattern=HEX)
    outline_color: str = Field("#000000", pattern=HEX)
    outline_px: int = Field(6, ge=0, le=20)
    shadow_px: int = Field(0, ge=0, le=20)
    spacing: float = Field(0.0, ge=-5.0, le=20.0)
    uppercase: bool = True
    words_per_page: int = Field(2, ge=1, le=3)
    position_y: float = Field(0.60, ge=0.14, le=0.65)    # caption centre as a fraction of the height
    zoom_jump: float = Field(1.15, ge=1.0, le=1.25)      # the tight framing a new thought cuts to (1.12-1.20; <1.1 reads as a glitch)
    zoom_punch: float = Field(1.3, ge=1.0, le=1.45)      # the punch-in on a key line (shorts 1.25-1.40)
    grade: float = Field(0.5, ge=0.0, le=1.0)            # colour grade strength: contrast, colour, warmth, sharpness
    voice_clean: bool = True                             # rumble cut, light denoise, gentle compression, presence
    pace: Literal["normal", "fast"] = "normal"           # fast: shorter kept pauses and more framing changes (reels)
    speed: float = Field(1.0, ge=1.0, le=1.25)           # playback speed of the whole finished short (voice pitch kept)
    music_mood: Literal["chill", "upbeat", "tech", "hype", "emotional", "suspense", "funny", "cinematic"] | None = None
                                                         # default mood for `shorts music` (kit/music library)


class Decision(BaseModel):
    id: str
    group: str
    question: str
    subject: dict[str, Any]
    kind: str
    value: Any = None                 # Jev's raw answer: P(yes) for nouls, the label for choices
    confidence: float | None = None
    probabilities: dict[str, float] = {}
    route: Literal["apply", "claude", "default"]
    effective: Any = None             # what the plan uses unless resolutions.json overrides it


class Decisions(BaseModel):
    version: Literal[1] = 1
    model: str | None = None
    input_tokens: int = 0
    auto_fillers: list[int] = []      # word indices removed by rule (um, uh, ...)
    items: list[Decision] = []
    pending: list[str] = []           # decision ids Claude should resolve
    jev_error: str | None = None


class CaptionWord(BaseModel):
    text: str
    start: float
    end: float
    highlight: bool = False


class CaptionPage(BaseModel):
    start: float
    end: float
    scale: float = 1.0
    words: list[CaptionWord]


class Captions(BaseModel):
    template: Literal["bold_pop", "clean_karaoke"]
    font: str
    font_size: int
    text_color: str
    highlight_color: str
    outline_color: str
    outline_px: int
    shadow_px: int
    spacing: float
    uppercase: bool
    center_x: float
    center_y: float
    max_width: float
    pages: list[CaptionPage]


class Segment(BaseModel):
    in_frame: int
    out_frame: int                    # exclusive
    first_word: int
    last_word: int
    zoom: float = 1.0
    crop: list[int] | None = None     # [w, h, x, y] of the source crop, scaled back up to the output size
    text: str = ""


class OutputSpec(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    grade: float = 0.0
    speed: float = 1.0                # applied to the finished programme; every other time here is at 1x


class AudioSpec(BaseModel):
    clean: bool = False
    fade_ms: int = 10
    loudness_i: float = -14.0
    true_peak: float = -1.0
    source_integrated: float | None = None


class EditFile(BaseModel):
    version: Literal[1] = 1
    source: str
    source_frames: int
    output: OutputSpec
    segments: list[Segment]
    captions: Captions
    audio: AudioSpec
    duration: float                   # at 1x; the rendered file lasts duration / output.speed
    cold_open: int = 0                # how many leading segments are the teaser (they may come from later in the source)
    warnings: list[str] = []


class Scene(BaseModel):
    """One graphic on the output timeline."""
    id: str
    template: str
    start: float                      # seconds on the edited timeline
    end: float
    params: dict[str, Any] = {}
    note: str = ""                    # why this visual (for review)


class Music(BaseModel):
    """A background track under the whole short, ducked while the speaker talks."""
    file: str                                        # the track (mp3, m4a, wav…); it loops if shorter than the short
    # defaults: about 12 dB under the voice while talking, 8 dB in the gaps. The textbook 18-20 dB was inaudible
    # on a phone speaker for a bass-heavy lo-fi track (video2, 2026-09-27).
    level_db: float = Field(-8.0, ge=-40, le=0)      # music loudness relative to the voice, in the gaps between words
    duck_db: float = Field(4.0, ge=0, le=24)         # extra dip under speech (0 = no ducking)
    start: float = Field(0.0, ge=0)                  # seconds into the track where the short begins
    fade_in: float = Field(0.4, ge=0, le=5)
    fade_out: float = Field(1.5, ge=0, le=8)
    enter: float = Field(0.0, ge=0)                  # edited-timeline second where the track comes in (a dry cold
                                                     # open, then the music drops in from the track's `start`)
    drops: list[tuple[float, float]] = []            # edited-timeline windows where the music cuts out (a beat of silence)


class Visuals(BaseModel):
    """visuals.json: the graphics plan for a short (Jev picks templates, Claude fills params)."""
    version: Literal[1] = 1
    theme: dict[str, str] = {}        # accent, accent_ink, bg, ink, card, display_font, condensed_font, ui_font
    captions: Literal["box", "ass"] = "box"
    caption_size: int = Field(96, ge=60, le=140)
    scenes: list[Scene] = []
    music: Music | None = None
