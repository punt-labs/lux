"""Hub-private observation and worker lifecycle contracts for peripherals."""

from __future__ import annotations

from typing import Protocol

__all__ = ["PeripheralStatus", "PeripheralWorkers"]


class PeripheralStatus(Protocol):
    """Observe one endpoint without connecting to it."""

    @property
    def is_connected(self) -> bool:
        """Report local connection state without I/O."""
        ...


class PeripheralWorkers(Protocol):
    """Run a peripheral's own background workers."""

    def start(self) -> None:
        """Start the workers without changing their connection policy."""
        ...

    def stop(self) -> None:
        """Stop the workers in their own shutdown order."""
        ...
