"""Put the paper-studio component kit into a HyperFrames film.

HyperFrames serves only the project folder, so a film can't load files from kit/. This copies what the kit needs
(fonts, gsap) into the film and inlines the kit's CSS and JS into the page at the `<!--HF:KIT-->` marker.

    python3 kit/hf/vendor.py <film_dir>                                  # copy fonts + gsap into the film
    python3 kit/hf/vendor.py <film_dir> src/template.html index.html     # ... and write index.html with the kit inlined

From a film's build.py:
    sys.path.insert(0, str(ROOT / "kit/hf")); import vendor
    vendor.copy_assets(HERE); html = vendor.inline(html)
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
ROOT = KIT.parent
FONTS = ["InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf", "Inter-500.ttf", "Inter-600.ttf", "Inter-700.ttf", "Inter-800.ttf",
         "JetBrainsMono-500.ttf", "JetBrainsMono-700.ttf"]
MODULES = ["core.js", "motion.js", "scenes.js", "diagram.js", "screen.js", "code.js"]
GSAP_CANDIDATES = [ROOT / "node_modules/gsap/dist/gsap.min.js"]     # the repo root's npm install (./setup.sh)
# v7 styles (README: sketch / annotate / scribble / collage): their modules, hand fonts and libraries (repo-root `npm i`)
MODULES += ["sketch.js", "annotate.js", "scribble.js", "collage.js"]
FONTS += ["Excalifont-Regular.woff2", "Caveat-700.ttf"]
# v8 motion (README "v8 motion"): kinetic type, springs and motion tokens, plus its display faces
MODULES += ["kinetic.js"]
FONTS += ["Anton-400.ttf", "Montserrat-800.ttf", "Montserrat-900.ttf"]
LIBS = [("gsap/dist/DrawSVGPlugin.min.js", "DrawSVGPlugin.min.js", None),            # (node_modules path, vendor/ name, CJS global)
        ("roughjs/bundled/rough.js", "rough.js", None),
        ("perfect-freehand/dist/cjs/index.js", "perfect-freehand.js", "PerfectFreehand")]


def copy_libs(film: Path) -> None:
    """Copy the style libraries into vendor/ (a CJS file is wrapped so it sets a global). Missing ones are skipped."""
    for src, name, glob in LIBS:
        p = next((r / "node_modules" / src for r in (ROOT,) if (r / "node_modules" / src).exists()), None)
        if p is None:
            print(f"vendor.py: {src} not installed (run `npm i` at the repo root); {name} skipped", file=sys.stderr)
            continue
        js = p.read_text()
        if glob:
            js = f"(function(){{var exports={{}},module={{exports:exports}};\n{js}\nwindow.{glob}=module.exports;}})();\n"
        (film / "vendor" / name).write_text(js)


def gsap_path() -> Path:
    for p in GSAP_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit("gsap not found: run `npm install` in the repo root (./setup.sh does it)")


def copy_assets(film: Path) -> None:
    film = Path(film)
    (film / "assets/fonts").mkdir(parents=True, exist_ok=True)
    (film / "vendor").mkdir(exist_ok=True)
    for f in FONTS:
        shutil.copy2(KIT / "fonts" / f, film / "assets/fonts" / f)
    shutil.copy2(gsap_path(), film / "vendor/gsap.min.js")
    copy_libs(film)


def inline(html: str, stickman: bool = True) -> str:
    """Replace <!--HF:KIT--> with gsap + the kit's CSS and JS (and the stickman rig)."""
    if "<!--HF:KIT-->" not in html:
        raise SystemExit("template has no <!--HF:KIT--> marker (put it in <head>)")
    css = (HERE / "paper.css").read_text().replace("FONTS/", "assets/fonts/")
    js = [(HERE / m).read_text() for m in MODULES]
    if stickman:
        js.append((KIT / "stickman/stickman.js").read_text())
    block = ['<script src="vendor/gsap.min.js"></script>'] + [f'<script src="vendor/{n}"></script>' for _, n, _ in LIBS] + [f"<style>\n{css}\n</style>"]
    block += [f"<script>\n{s}\n</script>" for s in js]
    return html.replace("<!--HF:KIT-->", "\n".join(block))


if __name__ == "__main__":
    film = Path(sys.argv[1])
    copy_assets(film)
    if len(sys.argv) >= 4:
        src, out = film / sys.argv[2], film / sys.argv[3]
        out.write_text(inline(src.read_text()))
        print(f"{out}: kit inlined ({', '.join(MODULES)} + stickman)")
    else:
        print(f"{film}: fonts + gsap copied")
