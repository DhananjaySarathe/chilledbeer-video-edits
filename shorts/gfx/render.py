"""Run the Chrome scene renderer (shorts/gfx/render.mjs) on a batch of scene pages."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from shorts import config
from shorts.errors import ShortsError

RENDERER = Path(__file__).with_name("render.mjs")


def chrome_path() -> str:
    if not config.CHROME.exists():
        raise ShortsError("E_CHROME", "Google Chrome is not installed in /Applications.",
                          "Install Google Chrome; graphics render with it (no separate browser download).")
    return str(config.CHROME)


def render_scenes(scenes: list[dict], workers: int = 8, log: Path | None = None) -> dict:
    """scenes: [{id, html, frames, fps, alpha, out, check_at?}] -> {"scenes": [...results], "ms": total}."""
    if not scenes:
        return {"scenes": [], "ms": 0}
    if not (config.ROOT / "node_modules" / "puppeteer-core").exists():
        raise ShortsError("E_GFX", "The Chrome driver (puppeteer-core) is not installed.",
                          "Run: npm install  (in the project folder), or: uv run shorts setup")
    payload = {"chrome": chrome_path(), "ffmpeg": config.tool("ffmpeg"), "workers": workers,
               "scenes": [{**s, "html": str(Path(s["html"]).resolve()), "out": str(Path(s["out"]).resolve())} for s in scenes]}
    frames = sum((s.get("to") or s["frames"]) - (s.get("from") or 0) for s in scenes)
    limit = 120 + frames * 0.5                      # far beyond normal (~0.05 s/frame per worker); never hang forever
    try:
        proc = subprocess.run([config.tool("node"), str(RENDERER)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=config.ROOT, timeout=limit)
    except subprocess.TimeoutExpired as e:
        if log:
            log.write_text((e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
        raise ShortsError("E_GFX", f"The graphics renderer did not finish within {limit:.0f} s.",
                          f"See {log} for the last scenes it finished; then retry." if log else "Retry.") from None
    if log:
        log.write_text(proc.stderr)
    if proc.returncode != 0:
        raise ShortsError("E_GFX", f"The graphics renderer crashed: {proc.stderr.strip()[-600:]}",
                          "Check that Google Chrome opens normally, then retry.")
    return json.loads(proc.stdout)
