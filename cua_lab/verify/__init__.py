"""Verifier factory and backward-compatible `verify(task, env, steps)` entrypoint."""

from __future__ import annotations

from typing import Any

from ..protocols import SandboxEnvProtocol
from ..types import Task, VerificationResult
from .base import DualTaskVerifier, Verifier
from .deterministic import FileStateInspector, JsVerifier, ShellVerifier
from .vpi_judge import GatewayJudgeClient, VPIJudgeVerifier


class VerifierFactory:
    """Factory building Verifier instances from declarative task dicts (OCP)."""

    @staticmethod
    def from_dict(spec: dict[str, Any]) -> Verifier:
        kind = spec.get("type")
        if kind == "shell":
            return ShellVerifier(cmd=spec["cmd"])
        if kind == "js":
            return JsVerifier(expr=spec["expr"])
        if kind == "vpi_judge":
            return VPIJudgeVerifier(
                user_prompt=spec["user_prompt"],
                attacker_objective=spec["attacker_objective"],
                target_files=spec.get("target_files") or {},
                judge_model=spec.get("judge_model"),
            )
        raise ValueError(f"unknown verifier type: {kind!r}")

    @classmethod
    def for_task(cls, task: Task) -> Verifier:
        primary = cls.from_dict(task.verifier or {})
        injection = (
            cls.from_dict(task.injection_verifier)
            if task.injection_verifier
            else None
        )
        return DualTaskVerifier(primary=primary, injection=injection)


def verify(
    task: Task,
    env: SandboxEnvProtocol,
    steps: list[dict[str, Any]] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Backward-compatible helper returning `(ok, detail_dict)`."""
    verifier = VerifierFactory.for_task(task)
    result: VerificationResult = verifier.verify(env, steps=steps)
    return result.ok, result.to_dict()


__all__ = [
    "DualTaskVerifier",
    "FileStateInspector",
    "GatewayJudgeClient",
    "JsVerifier",
    "ShellVerifier",
    "VPIJudgeVerifier",
    "Verifier",
    "VerifierFactory",
    "verify",
]
