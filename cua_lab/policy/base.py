from __future__ import annotations

from typing import Any, Protocol

from ..types import Decision, Observation, Task


class PolicyError(RuntimeError):
    pass


class Policy(Protocol):
    name: str

    def decide(
        self,
        task: Task,
        obs: Observation,
        results: list[dict[str, Any]] | None = None,
    ) -> Decision: ...
