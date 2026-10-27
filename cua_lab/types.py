"""Shared types for the agent loop. Everything the loop touches is environment agnostic."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Action:
    type: str
    x: int | None = None
    y: int | None = None
    to_x: int | None = None
    to_y: int | None = None
    text: str | None = None
    keys: str | None = None
    direction: str | None = None
    amount: int | None = None
    element_id: int | None = None
    url: str | None = None
    submit: bool = False
    note: str | None = None

    def wire(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v is not False}

    def short(self) -> str:
        parts = [self.type]
        if self.x is not None and self.y is not None:
            parts.append(f"({self.x},{self.y})")
        if self.element_id is not None:
            parts.append(f"#{self.element_id}")
        if self.keys:
            parts.append(self.keys)
        if self.direction:
            parts.append(f"{self.direction}:{self.amount}")
        if self.text:
            parts.append(repr(self.text[:40]))
        if self.url:
            parts.append(self.url)
        return " ".join(parts)


@dataclass
class Observation:
    screenshot: bytes
    width: int
    height: int
    elements: list[dict[str, Any]] | None = None
    url: str | None = None
    title: str | None = None
    changed: bool | None = None
    cursor: dict[str, int] | None = None


@dataclass
class Decision:
    actions: list[Action]
    text: str | None = None
    raw: Any = None
    usage: dict[str, Any] | None = None
    stop_reason: str | None = None


@dataclass
class VerificationResult:
    """Canonical verification result returned by all Verifier implementations."""

    user_success: bool
    attack_attempted: bool = False
    attack_succeeded: bool = False
    explanation: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.user_success and not self.attack_succeeded

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.detail)
        if self.attack_attempted or self.attack_succeeded or "hijacked" in out or self.explanation:
            out["attempted"] = self.attack_attempted
            out["hijacked"] = self.attack_succeeded
            out["user_task_successful"] = self.user_success
        if self.explanation:
            out["explanation"] = self.explanation
        return out


@dataclass
class Task:
    id: str
    env: str
    instruction: str
    verifier: dict[str, Any]
    max_steps: int = 15
    obs: str | None = None
    script: list[dict[str, Any]] | None = None
    setup: str | None = None
    injection_verifier: dict[str, Any] | None = None
    setup_instructions: list[Any] | None = None
    attacker_objective: str | None = None
    benchmark: str | None = None
    platform: str | None = None
    target_paths: list[str] | None = None
