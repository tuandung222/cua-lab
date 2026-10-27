"""ISP (Interface Segregation Principle) protocols for environments and judges."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import Action, Observation


@runtime_checkable
class ShellEnvProtocol(Protocol):
    """Environment capable of executing shell commands inside the sandbox."""

    def exec_shell(self, cmd: str) -> dict[str, Any]: ...


@runtime_checkable
class JsEnvProtocol(Protocol):
    """Environment capable of evaluating JavaScript expressions in the active page."""

    def evaluate(self, expr: str) -> dict[str, Any]: ...


@runtime_checkable
class SandboxEnvProtocol(ShellEnvProtocol, JsEnvProtocol, Protocol):
    """Full sandbox actuator protocol shared by Desktop and Browser environments."""

    name: str
    mode: str

    def health(self) -> dict[str, Any]: ...
    def observe(self) -> Observation: ...
    def reset(self) -> dict[str, Any]: ...
    def act(self, action: Action) -> dict[str, Any]: ...


@runtime_checkable
class JudgeLLMProtocol(Protocol):
    """Abstraction for an LLM judge used in post-trajectory security evaluation."""

    def evaluate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...
