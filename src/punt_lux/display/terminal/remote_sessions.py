"""Display process facade: named replicas, never child processes."""

from __future__ import annotations

from typing import ClassVar

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_pool import RemotePool


class RemoteSessions:
    _pool: ClassVar[RemotePool] = RemotePool.default()
    last_output_at: ClassVar[float] = 0

    @classmethod
    def get(cls, name: str, command: str) -> RemoteSession:
        return cls._pool.get(name, command)

    @classmethod
    def pump_all(cls, frame_budget_s: float = 0.006) -> bool:
        busy = cls._pool.pump(frame_budget_s)
        cls.last_output_at = cls._pool.last_output_at
        return busy

    @classmethod
    def close_all(cls) -> None:
        """Release only the Display's connection and replicas."""
        cls._pool.close()
