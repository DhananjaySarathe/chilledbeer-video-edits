"""Ask Jev (TypeSafe System One) many small questions at once: batched, in parallel, with retries."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Answer:
    kind: str                        # "noul" or "choice"
    value: Any                       # noul: probability of yes; choice: the chosen label
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)


class Asker(Protocol):
    def ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict[str, Answer], dict]: ...


def to_answer(raw: Any) -> Answer:
    if raw.type == "noul":
        p = float(raw.noul)
        return Answer("noul", p, max(p, 1.0 - p), {"true": p, "false": 1.0 - p})
    value = raw.choice if raw.type == "choice" else raw.score
    return Answer(raw.type, value, float(raw.confidence), {str(k): float(v) for k, v in raw.probabilities.items()})


class JevAsker:
    """The real Jev. The key comes from TYPESAFE_API_KEY (loaded from .env by shorts.config)."""

    def __init__(self, batch_size: int = 40, concurrency: int = 8, timeout: float = 25.0, model: str | None = None):
        self.batch_size, self.concurrency, self.timeout, self.model = batch_size, concurrency, timeout, model

    def ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict[str, Answer], dict]:
        return asyncio.run(self._ask(state, questions))

    async def _ask(self, state: dict, questions: dict[str, dict]) -> tuple[dict[str, Answer], dict]:
        from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

        ids = list(questions)
        batches = [ids[k:k + self.batch_size] for k in range(0, len(ids), self.batch_size)]
        gate = asyncio.Semaphore(self.concurrency)
        async with AsyncTypeSafeClient(model=self.model, timeout=min(self.timeout, 15.0),
                                       retry=RetryPolicy(max_retries=2, timeout=self.timeout)) as client:
            async def one(batch: list[str]):
                async with gate:
                    return await client.system_one(state=state, questions={q: questions[q] for q in batch})

            responses = await asyncio.gather(*(one(b) for b in batches))
        answers: dict[str, Answer] = {}
        meta: dict = {"model": None, "input_tokens": 0}
        for r in responses:
            meta["model"] = r.model
            meta["input_tokens"] += r.usage.input_tokens or 0
            answers.update({name: to_answer(raw) for name, raw in r.answers.items()})
        return answers, meta
