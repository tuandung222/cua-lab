"""Replays a fixed action list from the task YAML. No model, no API key.

Useful for debugging the sandbox and the trace viewer in isolation:
if a scripted action does not land where you expect, the problem is the
environment, not the policy.
"""

from __future__ import annotations

from ..types import Action, Decision, Observation, Task


class ScriptedPolicy:
    name = "script"

    def __init__(self, actions: list[Action]):
        self._actions = list(actions)

    def decide(
        self,
        task: Task,
        obs: Observation,
        results: list[dict] | None = None,
    ) -> Decision:
        if not self._actions:
            return Decision(actions=[], text="script complete")
        return Decision(actions=[self._actions.pop(0)], text=None)
