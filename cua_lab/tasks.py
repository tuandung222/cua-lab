from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .types import Task


def load_task(path: str | Path) -> Task:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text())
    missing = {"id", "env", "instruction", "verifier"} - raw.keys()
    if missing:
        raise ValueError(f"{path}: missing keys {sorted(missing)}")
    return Task(
        id=raw["id"],
        env=raw["env"],
        instruction=raw["instruction"].strip(),
        verifier=raw["verifier"],
        max_steps=int(raw.get("max_steps", 15)),
        obs=raw.get("obs"),
        script=raw.get("script"),
        setup=raw.get("setup"),
        injection_verifier=raw.get("injection_verifier"),
    )


def list_tasks(root: str | Path = "tasks") -> list[Path]:
    return sorted(Path(root).glob("*/*.yaml"))
