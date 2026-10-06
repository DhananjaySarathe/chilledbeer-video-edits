"""The graphics library: one folder per template in kit/graphics/<id>/ (template.html, meta.json, example.json).

Jev reads each template's description to pick visuals; Claude fills its params; the renderer turns
template + params into a scene video. New templates Claude writes land here too, after `library check`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from shorts import config
from shorts.errors import ShortsError

GRAPHICS = config.KIT / "graphics"
RUNTIME = GRAPHICS / "_runtime"

Category = Literal["title", "mockup", "data", "list", "speaker", "brand", "overlay", "captions"]
# what a passage of the script does for the viewer (kit/refs/SCENES.md): the planner picks visuals from this
Explains = Literal["process", "comparison", "quantity", "relationship", "story", "mechanism", "chronology", "analogy",
                   "instruction", "code", "conversation", "definition", "emphasis", "proof", "structure", "ask"]


class Param(BaseModel):
    type: Literal["text", "number", "list", "bool", "color", "object"] = "text"
    required: bool = False
    default: Any = None
    max_len: int | None = None       # characters for text; items for lists
    help: str = ""


class Duration(BaseModel):
    min: float = 1.0
    default: float = 2.5
    max: float = 6.0


class Cue(BaseModel):
    at: float                        # seconds from the scene start
    name: str                        # a sound in kit/sfx (whoosh, pop, click, ...)
    gain_db: float = -14.0


class Meta(BaseModel):
    id: str
    name: str
    category: Category
    kind: Literal["overlay", "fullscreen", "speaker"]
    description: str = Field(min_length=20)      # what it shows; Jev picks from this
    use_when: str = ""                           # the kind of line it illustrates
    params: dict[str, Param] = {}
    duration: Duration = Duration()
    captions: Literal["show", "dark", "hide"] = "show"
    captions_by: dict | None = None              # {"param": "dark", "values": {"true": "show", "false": "dark"}}
    caption_y: float | None = Field(None, ge=0.5, le=0.8)  # caption centre (fraction of the height) while this
                                                 # full-screen scene is up, for layouts that fill the default band
    cutout: bool = False                         # speaker frames need the background removed
    sfx: list[Cue] = []
    tags: list[str] = []
    internal: bool = False                       # machinery (e.g. the caption track): never offered to Jev
    # scene registry (kit/refs/SCENES.md): what it explains, where it works, what to use instead, which version
    explains: list[Explains] = []
    ratios: list[Literal["9:16", "16:9", "1:1"]] = ["9:16"]
    fallback: str | None = None                  # a simpler template for when this one can't be used
    version: str = "1"


@dataclass(frozen=True)
class Template:
    meta: Meta
    dir: Path

    @property
    def id(self) -> str:
        return self.meta.id

    @property
    def example(self) -> dict:
        p = self.dir / "example.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def files_hash(self) -> str:
        h = hashlib.sha1()
        for name in ("template.html", "meta.json"):
            h.update((self.dir / name).read_bytes())
        for name in ("theme.css", "runtime.js"):
            h.update((RUNTIME / name).read_bytes())
        return h.hexdigest()


def load_template(folder: Path) -> Template:
    try:
        meta = Meta.model_validate(json.loads((folder / "meta.json").read_text()))
    except (OSError, ValueError, ValidationError) as e:
        raise ShortsError("E_TEMPLATE", f"Template {folder.name} has a bad meta.json: {str(e).splitlines()[0]}",
                          f"Fix kit/graphics/{folder.name}/meta.json (see docs/graphics.md).") from None
    if meta.id != folder.name:
        raise ShortsError("E_TEMPLATE", f"Template folder {folder.name} declares id {meta.id!r}.",
                          "The meta.json id must equal the folder name.")
    if not (folder / "template.html").exists():
        raise ShortsError("E_TEMPLATE", f"Template {folder.name} has no template.html.", "Add the template markup.")
    return Template(meta, folder)


def load_library(root: Path = GRAPHICS, skipped: dict[str, str] | None = None) -> dict[str, Template]:
    """Every valid template. Unfinished or broken ones are left out (and reported in `skipped`), so a template
    being written never blocks an edit."""
    lib = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        try:
            t = load_template(d)
            lib[t.id] = t
        except ShortsError as e:
            if skipped is not None:
                skipped[d.name] = e.message
    return lib


def check_params(meta: Meta, params: dict) -> list[str]:
    """Problems with params for a template (empty list = fine)."""
    problems = []
    for name, spec in meta.params.items():
        v = params.get(name, spec.default)
        if v is None:
            if spec.required:
                problems.append(f"{meta.id}: '{name}' is required")
            continue
        ok = {"text": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
              "list": isinstance(v, list), "bool": isinstance(v, bool),
              "color": isinstance(v, str) and v.startswith("#"), "object": isinstance(v, dict)}[spec.type]
        if not ok:
            problems.append(f"{meta.id}: '{name}' should be {spec.type}, got {type(v).__name__}")
        elif spec.max_len is not None and spec.type in ("text", "list") and len(v) > spec.max_len:
            problems.append(f"{meta.id}: '{name}' is {len(v)} long (max {spec.max_len})")
    unknown = sorted(set(params) - set(meta.params))
    if unknown:
        problems.append(f"{meta.id}: unknown params {unknown}")
    return problems


def resolved_params(meta: Meta, params: dict) -> dict:
    return {name: params.get(name, spec.default) for name, spec in meta.params.items()}


THEME_VARS = {"accent": "--accent", "accent_ink": "--accent-ink", "bg": "--bg", "ink": "--ink", "card": "--card",
              "display_font": "--display", "condensed_font": "--condensed", "ui_font": "--ui"}


def build_page(tpl: Template, params: dict, duration_s: float, out_html: Path, *, fps: int = 30,
               theme: dict | None = None, speaker_frames: list[Path] | None = None, face: dict | None = None) -> Path:
    """Write a self-contained page for one scene: runtime + theme + params + the template's markup."""
    theme = theme or {}
    css_vars = "".join(f"{THEME_VARS[k]}:{v};" for k, v in theme.items() if k in THEME_VARS and v)
    cfg = {
        "params": resolved_params(tpl.meta, params), "duration": round(duration_s * 1000), "fps": fps,
        "kind": tpl.meta.kind, "face": face,
        "speaker": {"frames": [f.resolve().as_uri() for f in speaker_frames]} if speaker_frames else None,
    }
    body = (tpl.dir / "template.html").read_text()
    page = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<link rel=\"stylesheet\" href=\"{(RUNTIME / 'theme.css').resolve().as_uri()}\">"
        f"<style>:root{{{css_vars}}}</style>"
        f"<script>window.__GFX__ = {json.dumps(cfg, ensure_ascii=False)};</script>"
        f"<script src=\"{(RUNTIME / 'runtime.js').resolve().as_uri()}\"></script>"
        f"</head><body class=\"kind-{tpl.meta.kind}\">\n{body}\n</body></html>"
    )
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page)
    return out_html


def scene_key(tpl: Template, params: dict, duration_s: float, theme: dict | None, speaker_id: str = "") -> str:
    """Cache key: the same template, words, length, theme and speaker footage render to the same video."""
    blob = json.dumps({"t": tpl.files_hash(), "p": resolved_params(tpl.meta, params), "d": round(duration_s, 3),
                       "th": theme or {}, "s": speaker_id}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def captions_mode(meta: Meta, params: dict) -> str:
    """The template's caption mode for these params (captions_by lets a param such as a dark background decide)."""
    if meta.captions_by:
        v = resolved_params(meta, params).get(meta.captions_by.get("param"))
        mode = meta.captions_by.get("values", {}).get(str(v).lower())
        if mode in ("show", "dark", "hide"):
            return mode
    return meta.captions
