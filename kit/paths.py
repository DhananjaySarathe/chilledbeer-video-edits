"""Where everything the pipeline generates goes. One rule: generated files live under output/, never in films/ or kit/.

    output/final/<video>/     the deliverables: the video(s) to upload, captions.srt, posting notes (keep)
    output/jobs/<take>/       one recorded take: source.mp4 (the footage copy), analysis.json (words), brief, style,
                              resolutions, edit and visuals JSON, sentmap.json (keep while you might re-edit it)
    output/music_usage.json   which music track each video used (keeps tracks from repeating)
    output/temp/              everything else, safe to delete any time (`uv run shorts clean`):
        jobs/<take>/          audio extracts, whisper output, face tracks, graphics frames, previews, logs
        films/<video>/        a film's work/ (cut A-roll, grades, mixes, snapshots), renders/, scratch/ (one-off scripts)
        cache/                caches shared by every video (graphics previews, the re-listen cache)

films/<video>/ keeps only the recipe: edl.py, build.py, src/template.html, visual_plan.json and the screenshots it uses.
A take made before 2026-10-07 (jobs/<take>/ with work/ inside) is still found where it is.

From a film's script (stdlib only, works with plain python3):
    ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
    from kit.paths import job_source, job_temp, film_temp, film_final
    TEMP = film_temp(__file__)        # output/temp/films/<video>/ (created)
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
JOBS = OUTPUT / "jobs"
TEMP = OUTPUT / "temp"
FINAL = OUTPUT / "final"
CACHE = TEMP / "cache"
LEGACY_JOBS = ROOT / "jobs"
FILMS = ROOT / "films"


def _legacy(take: str) -> bool:
    return (LEGACY_JOBS / take).is_dir() and not (JOBS / take).is_dir()


def job_dir(take: str) -> Path:
    """A take's kept folder: analysis.json, brief.json, edit.json... (made by `shorts probe`)."""
    return LEGACY_JOBS / take if _legacy(take) else JOBS / take


def job_temp(take: str) -> Path:
    """A take's temp folder: audio16k.wav, whisper.json, source.face.json, voice_raw.wav, graphics frames, logs."""
    return LEGACY_JOBS / take / "work" if _legacy(take) else TEMP / "jobs" / take


def job_source(take: str) -> Path:
    """The take's footage as normalised by `shorts probe` (kept: deleting temp never loses footage)."""
    return LEGACY_JOBS / take / "work" / "source.mp4" if _legacy(take) else JOBS / take / "source.mp4"


def _film_parts(film: str | Path) -> tuple[str, ...]:
    p = Path(film).resolve()
    if p.suffix:
        p = p.parent
    try:
        return p.relative_to(FILMS).parts
    except ValueError:                       # a kit demo or a preset example: named after its path from the root
        return ("-".join(p.relative_to(ROOT).parts),)


def film_name(film: str | Path) -> str:
    """'expensewaale' for films/expensewaale/build.py, 'expensewaale-reel' for films/expensewaale/reel/build_reel.py."""
    return "-".join(_film_parts(film))


def film_temp(film: str | Path) -> Path:
    """output/temp/films/<video>/ (created): work files, renders/, snapshots, scratch/."""
    d = TEMP / "films" / film_name(film)
    d.mkdir(parents=True, exist_ok=True)
    return d


def film_final(film: str | Path) -> Path:
    """output/final/<video>/ (created): the files to upload. A film's reel delivers next to its long video."""
    d = FINAL / _film_parts(film)[0]
    d.mkdir(parents=True, exist_ok=True)
    return d


class Film:
    """Every folder one film uses. At the top of each film script:  F = Film(__file__)

        F.src       films/<video>[/reel]: the recipe (edl.py, build.py, src/template.html, edl.json, assets/ screenshots)
        F.work      output/temp/films/<name>/work: cut A-roll, grades, voice, mixes, cues.json, review images
        F.hf        output/temp/films/<name>/hf: the HyperFrames project (index.html, hyperframes.json, assets/, vendor/)
        F.assets    F.hf / "assets": what the composition loads (F.stage() copies the film's own assets/ in)
        F.renders   output/temp/films/<name>/renders: raw HyperFrames renders, snapshots
        F.scratch   output/temp/films/<name>/scratch: one-off fix scripts and experiments (never in films/)
        F.final     output/final/<video>: the videos to upload, captions.srt, posting notes
    """

    def __init__(self, script: str | Path):
        p = Path(script).resolve()
        self.src = p.parent if p.suffix else p
        self.name = film_name(self.src)
        self.temp = film_temp(self.src)
        self.work, self.hf, self.renders, self.scratch = (self.temp / d for d in ("work", "hf", "renders", "scratch"))
        self.assets = self.hf / "assets"
        self.final = film_final(self.src)
        for d in (self.work, self.assets, self.renders, self.scratch):
            d.mkdir(parents=True, exist_ok=True)

    def stage(self) -> Path:
        """Make F.hf a HyperFrames project: copy in hyperframes.json/meta.json and the film's tracked assets/ and
        compositions/ (screenshots, blurred stills, web captures, catalog blocks). Returns F.hf."""
        import shutil
        for f in ("hyperframes.json", "meta.json"):
            if (self.src / f).exists():
                shutil.copy2(self.src / f, self.hf / f)
        for d in ("assets", "compositions"):
            if (self.src / d).is_dir():
                shutil.copytree(self.src / d, self.hf / d, dirs_exist_ok=True)
        return self.hf


def cache(name: str) -> Path:
    """output/temp/cache/<name>/ (created): a cache shared across videos."""
    d = CACHE / name
    d.mkdir(parents=True, exist_ok=True)
    return d
