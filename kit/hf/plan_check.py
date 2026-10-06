"""Check a visual plan (visual_plan.json) against the scene registries before building a film (kit/refs/SCENES.md).

    python3 kit/hf/plan_check.py <visual_plan.json> [--key]

Checks: required fields and goals, explanation types, that each technique exists (kit/hf/registry.json or a
kit/graphics template) and explains the passage's type, ratio support, fallbacks (present and valid), on-screen time
against each component's limits, stickman budget (2-4 moments, <= 5 s, never back to back), runs of the same technique,
words-only share, and that listed assets exist. `--key` prints a cache key over the plan, the versions of the
components it uses, the kit files, the preset and the output settings.
Exit 0 = clean, 2 = warnings only, 3 = errors.
"""
import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
TYPES = {"process", "comparison", "quantity", "relationship", "story", "mechanism", "chronology", "analogy", "instruction", "code",
         "conversation", "definition", "emphasis", "proof", "structure", "ask"}
NEEDS_FALLBACK = {"screen", "code", "terminal", "diagram", "stickman"}
WORDS_ONLY = {"words", "pill", "side"}


def registry() -> dict:
    """{id: {source, explains, ratios, fallback, timing, version}} for long-form components and short-form templates."""
    reg = {}
    hf = json.loads((KIT / "hf/registry.json").read_text())
    for cid, c in hf["components"].items():
        reg[cid] = {"source": "kit/hf", "explains": c.get("explains", []), "ratios": [r.split(" ")[0] for r in c.get("ratios", [])],
                    "fallback": c.get("fallback"), "timing": c.get("timing", {}), "version": c.get("version", "1")}
    for meta in sorted((KIT / "graphics").glob("*/meta.json")):
        m = json.loads(meta.read_text())
        if m.get("internal"):
            continue
        d = m.get("duration", {})
        reg[m["id"]] = {"source": "kit/graphics", "explains": m.get("explains", []), "ratios": m.get("ratios", ["9:16"]), "fallback": m.get("fallback"),
                        "timing": {"min": d.get("min", 1.0), "max": d.get("max", 6.0)}, "version": str(m.get("version", "1"))}
    return reg


def span(p: dict, words: dict) -> tuple[float, float] | None:
    if "t" in p:
        return float(p["t"][0]), float(p["t"][1])
    if "words" in p and words:
        a, b = p["words"]
        if a in words and b in words:
            return words[a][0], words[b][1]
    return None


def check(plan_path: Path) -> tuple[list[str], list[str], dict]:
    plan = json.loads(plan_path.read_text())
    reg = registry()
    errs, warns = [], []
    ratio = plan.get("ratio", "16:9")
    words = {}
    if plan.get("edl"):
        e = plan_path.parent / plan["edl"]
        if e.exists():
            words = {w["i"]: (w["t"], w["e"]) for w in json.loads(e.read_text())["words"]}
        else:
            warns.append(f"edl {plan['edl']} not found: word spans can't be timed")
    ps = plan.get("passages", [])
    if not ps:
        errs.append("no passages")
    stick, last, run, words_only = [], None, 0, 0
    for p in ps:
        pid = p.get("id", "?")
        for f in ("id", "goal", "type", "technique", "beats"):
            if not p.get(f):
                errs.append(f"{pid}: missing '{f}'")
        if "words" not in p and "t" not in p:
            errs.append(f"{pid}: needs 'words' [first, last] or 't' [a, b]")
        ty, te = p.get("type"), p.get("technique")
        if ty and ty not in TYPES:
            errs.append(f"{pid}: unknown type '{ty}' (one of {sorted(TYPES)})")
        c = reg.get(te)
        if te and not c:
            errs.append(f"{pid}: technique '{te}' is not in kit/hf/registry.json or kit/graphics")
            continue
        if not c:
            continue
        if ty in TYPES and c["explains"] and ty not in c["explains"]:
            warns.append(f"{pid}: '{te}' isn't listed for '{ty}' (it explains {c['explains']}); check kit/refs/SCENES.md §2")
        if c["ratios"] and ratio not in c["ratios"]:
            fb = p.get("fallback") or c["fallback"]
            (warns if fb else errs).append(f"{pid}: '{te}' doesn't support {ratio}" + (f"; the fallback '{fb}' will be used" if fb else " and has no fallback"))
        fb = p.get("fallback")
        if te in NEEDS_FALLBACK and not fb:
            errs.append(f"{pid}: '{te}' needs a 'fallback' (the asset or ratio can fail)")
        if fb and fb not in reg and fb != "none":
            errs.append(f"{pid}: fallback '{fb}' is not a known component or template")
        sp = span(p, words)
        if sp:
            dur = sp[1] - sp[0]
            mn, mx = c["timing"].get("min"), c["timing"].get("max")
            if mn and dur < mn - 0.05:
                warns.append(f"{pid}: {te} on screen {dur:.1f} s, under its {mn} s minimum")
            if mx and dur > mx + 0.05:
                warns.append(f"{pid}: {te} on screen {dur:.1f} s, over its {mx} s maximum (split it or develop it across passages)")
            for b in p.get("beats", []):
                at = b.get("at")
                t = words.get(at, (None,))[0] if isinstance(at, int) and words else at if isinstance(at, float) else None
                if t is not None and not (sp[0] - 0.05 <= t <= sp[1] + 0.05):
                    warns.append(f"{pid}: beat at {at} falls outside the passage")
            if te == "stickman":
                stick.append((pid, dur, sp))
        elif te == "stickman":
            stick.append((pid, None, None))
        for a in p.get("assets", []):
            if not (plan_path.parent / a).exists():
                warns.append(f"{pid}: asset {a} not found (relative to the plan)")
        same = te == last and not (te == "diagram" and p.get("diagram"))
        run = run + 1 if same else 1
        if run >= 3:
            warns.append(f"{pid}: '{te}' {run} passages in a row; vary it unless it's one developing diagram")
        last = te
        words_only += te in WORDS_ONLY
        if not p.get("why"):
            warns.append(f"{pid}: no 'why' (how this visual helps the viewer)")
    try:                                                                    # looks per passage (kit/refs/SCENES.md §6)
        sys.path.insert(0, str(KIT / "look"))
        import looks as LK
        names = set(LK.LOOKS)
    except Exception:
        names = None
    seq = [p.get("look", "natural") for p in ps]
    for p, lk in zip(ps, seq):
        if names is not None and lk not in names:
            errs.append(f"{p.get('id')}: unknown look '{lk}' (one of {sorted(names)})")
    others = {lk for lk in seq if lk != "natural"}
    if len(others) > 3:
        warns.append(f"{len(others)} different looks besides natural ({sorted(others)}); keep it to 2-3")
    flips = sum(1 for k in range(2, len(seq)) if seq[k] == seq[k - 2] != seq[k - 1])
    if flips >= 2:
        warns.append("looks flip back and forth passage by passage; hold a mood (>= 3 s) or stay natural")
    if len(stick) > 4:
        errs.append(f"{len(stick)} stickman moments (max 4 per video)")
    for pid, dur, _ in stick:
        if dur and dur > 5.05:
            warns.append(f"{pid}: stickman moment {dur:.1f} s (keep it 2-5 s)")
    ids = [p.get("id") for p in ps]
    for k in range(1, len(ps)):
        if ps[k].get("technique") == "stickman" and ps[k - 1].get("technique") == "stickman":
            errs.append(f"{ids[k - 1]} and {ids[k]}: stickman moments back to back")
    if ps and words_only / len(ps) > 0.4:
        warns.append(f"{words_only}/{len(ps)} passages are words-only; show the thing instead (SCENES.md §3)")
    return errs, warns, plan


def cache_key(plan: dict) -> str:
    reg = registry()
    h = hashlib.sha256()
    h.update(json.dumps(plan, sort_keys=True).encode())
    for te in sorted({p.get("technique") for p in plan.get("passages", [])} | {p.get("fallback") for p in plan.get("passages", [])}):
        if te in reg:
            h.update(f"{te}@{reg[te]['version']}".encode())
    for f in sorted((KIT / "hf").glob("*.js")) + [KIT / "hf/paper.css", KIT / "stickman/stickman.js", KIT / "presets/paper_studio/preset.json"]:
        if f.exists():
            h.update(f.read_bytes())
    h.update(json.dumps({k: plan.get(k) for k in ("ratio", "fps", "width", "height", "preset")}, sort_keys=True).encode())
    return h.hexdigest()[:16]


def main():
    path = Path(sys.argv[1])
    errs, warns, plan = check(path)
    for e in errs:
        print("ERROR  ", e)
    for w in warns:
        print("WARN   ", w)
    n = len(plan.get("passages", []))
    print(f"{'FAIL' if errs else 'WARN' if warns else 'PASS'}: {path.name}  {n} passages, {len(errs)} errors, {len(warns)} warnings")
    if "--key" in sys.argv:
        print("cache key:", cache_key(plan))
    sys.exit(3 if errs else 2 if warns else 0)


if __name__ == "__main__":
    main()
