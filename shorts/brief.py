"""Claude's creative input for a job: brief.json (what matters) and style.json (how it looks)."""
from __future__ import annotations

from pydantic import BaseModel, ValidationError

from shorts import fonts
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.schemas import Brief, EditFile, Style, Visuals

SCHEMAS: dict[str, type[BaseModel]] = {"brief": Brief, "style": Style, "edit": EditFile, "visuals": Visuals}


def _load(job: Job, rel: str, model: type[BaseModel], code: str):
    try:
        return model.model_validate(job.read(rel))
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        raise ShortsError(code, f"{rel} is invalid at {loc}: {first['msg']}",
                          f"Fix {rel} (see: shorts schema {rel.split('.')[0]}).") from None


def load_brief(job: Job) -> Brief:
    return _load(job, "brief.json", Brief, "E_BRIEF_INVALID")


def load_style(job: Job) -> Style:
    style = _load(job, "style.json", Style, "E_STYLE_INVALID")
    fonts.font_path(style.font)
    return style


def default_font() -> str:
    found = fonts.available()
    return "Montserrat-800.ttf" if "Montserrat-800.ttf" in found else (found[0] if found else "Montserrat-800.ttf")


def init_brief(job_name: str, force: bool = False) -> dict:
    job = Job.open(job_name)
    written = []
    for rel, model in (("brief.json", Brief()), ("style.json", Style(font=default_font()))):
        if job.has(rel) and not force:
            continue
        job.write(rel, model.model_dump())
        written.append(rel)
    return {"job": job.name, "written": written, "brief": str(job.path("brief.json")),
            "style": str(job.path("style.json")), "fonts": fonts.available(),
            "next": f"Read contact.png, fill brief.json (topic, target, visual_notes, caption_overrides) and design style.json, then: shorts decide {job.name}"}


def add_command(sub) -> None:
    p = sub.add_parser("init-brief", help="Write starter brief.json and style.json for Claude to fill in.")
    p.add_argument("job")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.set_defaults(func=lambda a: init_brief(a.job, a.force))
    s = sub.add_parser("schema", help="Print the JSON schema of a job file.")
    s.add_argument("name", choices=sorted(SCHEMAS))
    s.set_defaults(func=lambda a: SCHEMAS[a.name].model_json_schema())
