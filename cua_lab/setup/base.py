"""Abstract Command interface for sandbox environment setup & teardown."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..protocols import SandboxEnvProtocol


class EnvSetupInstruction(ABC):
    """Command object that prepares or cleans up a specific aspect of the sandbox."""

    @abstractmethod
    def execute(self, env: SandboxEnvProtocol) -> dict[str, Any]:
        """Apply this setup instruction inside the target environment."""

    def cleanup(self, env: SandboxEnvProtocol) -> None:
        """Optional cleanup hook executed on reset."""
        return None
