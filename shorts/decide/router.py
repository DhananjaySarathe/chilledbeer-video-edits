"""Confidence routing: act on Jev's answer, hand it to Claude, or fall back to a safe default."""
from __future__ import annotations

from typing import Any

from shorts import config
from shorts.decide.jev import Answer
from shorts.decide.questions import Spec

NO_THRESHOLD = round(1 - config.APPLY_THRESHOLD, 6)
DUP_KEEP_PROB = 0.6


def route(spec: Spec, ans: Answer | None) -> tuple[str, Any]:
    if ans is None:
        return ("default" if spec.policy == "cosmetic" else "claude"), spec.default
    if spec.group == "punch_in":
        return "apply", ans.value >= config.PUNCH_IN_THRESHOLD
    if spec.kind == "noul":
        if ans.value >= config.APPLY_THRESHOLD:
            return "apply", True
        if ans.value <= NO_THRESHOLD:
            return "apply", False
        return "claude", spec.default
    if spec.group == "duplicate_take":
        if ans.confidence >= config.APPLY_THRESHOLD:
            return "apply", ans.value
        return "claude", ans.value if ans.probabilities.get(ans.value, 0.0) >= DUP_KEEP_PROB else spec.default
    return "claude", spec.default
