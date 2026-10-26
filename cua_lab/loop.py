"""The loop. Roughly 60 lines, and that is the whole agent."""

from __future__ import annotations

import time
from typing import Callable

from .env import HttpEnv
from .policy.base import Policy
from .trace.recorder import Recorder
from .types import Task
from .verify import verify


def run(
    task: Task,
    env: HttpEnv,
    policy: Policy,
    rec: Recorder,
    max_steps: int,
    log: Callable[[str], None] = print,
) -> tuple[bool, dict]:
    obs = env.observe()
    finished = False

    for i in range(max_steps):
        t0 = time.time()
        decision = policy.decide(task, obs)
        latency_ms = (time.time() - t0) * 1000

        if not decision.actions:
            rec.step(i, obs, obs, decision, [], latency_ms)
            log(f"[{i}] stop: {decision.text or '(no tool call)'}")
            break

        if decision.text:
            log(f"[{i}] think: {decision.text[:160]}")

        before = obs
        results = []
        for action in decision.actions:
            log(f"[{i}] act: {action.short()}")
            result = env.act(action)
            results.append(result)
            if action.type == "finish":
                finished = True
            if result.get("ok") is False and result.get("error"):
                log(f"     !! {result['error']}")

        obs = env.observe()
        rec.step(i, before, obs, decision, results, latency_ms)

        if finished:
            break

    ok, detail = verify(task, env)
    rec.finish(ok, detail)
    return ok, detail
