"""Task verification, executed inside the sandbox after the trajectory ends."""

from __future__ import annotations

from typing import Any

from .env import HttpEnv
from .types import Task


def verify(task: Task, env: HttpEnv) -> tuple[bool, dict[str, Any]]:
    v = task.verifier or {}
    kind = v.get("type")

    if kind == "shell":
        res = env.exec_shell(v["cmd"])
        ok = res.get("returncode") == 0
        return ok, {"type": "shell", "cmd": v["cmd"], **res}

    if kind == "js":
        res = env.evaluate(v["expr"])
        ok = bool(res.get("result"))
        return ok, {"type": "js", "expr": v["expr"], **res}

    raise ValueError(f"unknown verifier type: {kind!r}")
