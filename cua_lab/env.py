"""HTTP client for the in-container actuators.

The desktop and the browser expose the same surface (/observe, /act, /exec, /eval).
That symmetry is the point: the agent loop cannot tell which one it is driving.
"""

from __future__ import annotations

import base64

import requests

from .types import Action, Observation


class EnvError(RuntimeError):
    pass


class HttpEnv:
    def __init__(self, name: str, base_url: str, mode: str = "pixel", timeout: float = 60.0):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.timeout = timeout

    def _post(self, path: str, payload: dict | None = None) -> dict:
        try:
            r = requests.post(f"{self.base_url}{path}", json=payload or {}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise EnvError(
                f"cannot reach {self.name} actuator at {self.base_url} ({exc}). "
                "Is the sandbox up? Try: make up"
            ) from exc
        if r.status_code >= 400:
            raise EnvError(f"{path} -> HTTP {r.status_code}: {r.text[:500]}")
        return r.json()

    def health(self) -> dict:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise EnvError(f"{self.name} is not healthy at {self.base_url}: {exc}") from exc

    def observe(self) -> Observation:
        data = self._post("/observe", {"mode": self.mode})
        return Observation(
            screenshot=base64.b64decode(data["screenshot"]),
            width=data["width"],
            height=data["height"],
            elements=data.get("elements"),
            url=data.get("url"),
            title=data.get("title"),
            changed=data.get("changed"),
            cursor=data.get("cursor"),
        )

    def reset(self) -> dict:
        return self._post("/reset")

    def act(self, action: Action) -> dict:
        return self._post("/act", {"action": action.wire()})

    def exec_shell(self, cmd: str) -> dict:
        return self._post("/exec", {"cmd": cmd})

    def evaluate(self, expr: str) -> dict:
        return self._post("/eval", {"expr": expr})
