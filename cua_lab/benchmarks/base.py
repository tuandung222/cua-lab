"""Abstract BenchmarkAdapter and BenchmarkRegistry (Open/Closed & Liskov Substitution Principles)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..types import Task


@dataclass(frozen=True)
class BenchmarkCase:
    """Canonical representation of a single benchmark evaluation scenario."""

    uid: str
    short_id: str
    raw_id: str
    benchmark: str
    mode: str  # "computer_use" | "browser_use"
    platform: str
    url: str
    user_prompt: str
    attacker_objective: str
    environment: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""


class BenchmarkAdapter(ABC):
    """Abstract adapter interface that every external benchmark implements."""

    name: str

    @abstractmethod
    def sync_assets(self, cache_dir: Path) -> dict[str, Any]:
        """Download or update benchmark datasets and web/environment assets."""

    @abstractmethod
    def list_cases(
        self,
        cache_dir: Path,
        mode: str | None = None,
        platform: str | None = None,
        search: str | None = None,
    ) -> list[BenchmarkCase]:
        """List available benchmark test cases matching optional filters."""

    @abstractmethod
    def get_case(self, cache_dir: Path, case_id: str) -> BenchmarkCase:
        """Resolve a single BenchmarkCase by uid, short_id, or raw_id."""

    @abstractmethod
    def to_task(
        self,
        case: BenchmarkCase,
        use_local_web: bool = True,
        auto_open_url: bool = True,
        max_steps: int = 18,
    ) -> Task:
        """Convert a BenchmarkCase into an executable cua-lab Task."""


class BenchmarkRegistry:
    """Registry of BenchmarkAdapter implementations (Open/Closed Principle)."""

    _adapters: dict[str, type[BenchmarkAdapter]] = {}

    @classmethod
    def register(cls, name: str):
        def _decorator(adapter_cls: type[BenchmarkAdapter]) -> type[BenchmarkAdapter]:
            adapter_cls.name = name
            cls._adapters[name] = adapter_cls
            return adapter_cls

        return _decorator

    @classmethod
    def get(cls, name: str) -> BenchmarkAdapter:
        key = name.lower().replace("-", "_")
        if key not in cls._adapters:
            avail = ", ".join(sorted(cls._adapters))
            raise KeyError(f"Unknown benchmark {name!r}. Available: {avail}")
        return cls._adapters[key]()

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls._adapters)
