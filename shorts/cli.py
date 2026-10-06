"""`shorts` command line. Every command prints one JSON object on stdout; errors go to stderr as JSON."""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from shorts.errors import ShortsError

COMMAND_MODULES = [
    "shorts.job",
    "shorts.clean",
    "shorts.setup_assets",
    "shorts.doctor",
    "shorts.media.run",
    "shorts.analyze.run",
    "shorts.brief",
    "shorts.decide.run",
    "shorts.plan.run",
    "shorts.render.run",
    "shorts.check.run",
    "shorts.gfx.run",
    "shorts.gfx.scenes",
    "shorts.direct.run",
    "shorts.music.run",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shorts", description="ChilledBeer Video Edits: local vertical-shorts editor driven by Claude.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMAND_MODULES:
        importlib.import_module(name).add_command(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.func(args)
    except ShortsError as e:
        print(json.dumps(e.to_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 3 if isinstance(result, dict) and result.get("passed") is False else 0


def run() -> None:
    sys.exit(main())
