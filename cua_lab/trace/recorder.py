"""Append-only trajectory recorder: one directory per run, JSONL steps, PNGs on disk."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..types import Decision, Observation


class Recorder:
    def __init__(self, root: Path, meta: dict[str, Any]):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run = f"{stamp}-{meta['task']}"
        self.dir = Path(root) / self.run
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = {"run": self.run, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **meta}
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2, ensure_ascii=False))
        self._steps = open(self.dir / "steps.jsonl", "w", encoding="utf-8")
        self.n = 0

    def step(
        self,
        i: int,
        before: Observation,
        after: Observation,
        decision: Decision,
        results: list[dict],
        latency_ms: float,
    ) -> None:
        before_name = f"{i:03d}_before.png"
        after_name = f"{i:03d}_after.png"
        (self.dir / before_name).write_bytes(before.screenshot)
        (self.dir / after_name).write_bytes(after.screenshot)

        row = {
            "index": i,
            "before": before_name,
            "after": after_name,
            "obs": {
                "width": before.width,
                "height": before.height,
                "url": before.url,
                "title": before.title,
                "n_elements": len(before.elements or []),
            },
            "after_obs": {"url": after.url, "title": after.title},
            "actions": [a.wire() for a in decision.actions],
            "results": results,
            "text": decision.text,
            "usage": decision.usage,
            "stop_reason": decision.stop_reason,
            "raw": decision.raw,
            "latency_ms": round(latency_ms, 1),
        }
        self._steps.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._steps.flush()
        self.n += 1

    def finish(self, success: bool, detail: dict) -> None:
        self._steps.close()
        (self.dir / "result.json").write_text(
            json.dumps({"success": success, "detail": detail}, indent=2, ensure_ascii=False, default=str)
        )
        self._update_index(success)

    def _update_index(self, success: bool) -> None:
        index = self.dir.parent / "runs.json"
        runs: list[dict] = []
        if index.exists():
            try:
                runs = json.loads(index.read_text())
            except json.JSONDecodeError:
                runs = []
        runs = [r for r in runs if r.get("run") != self.run]
        runs.insert(
            0,
            {
                "run": self.run,
                "task": self.meta["task"],
                "env": self.meta["env"],
                "mode": self.meta["mode"],
                "model": self.meta.get("model"),
                "steps": self.n,
                "success": success,
                "started_at": self.meta["started_at"],
            },
        )
        index.write_text(json.dumps(runs[:200], indent=2, ensure_ascii=False))
