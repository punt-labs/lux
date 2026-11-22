"""Display process facade: named replicas, never child processes."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING, ClassVar

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_pool import RemotePool

if TYPE_CHECKING:
    from punt_lux.display.terminal.idling_decision import IdlingDecision


class RemoteSessions:
    _pool: ClassVar[RemotePool] = RemotePool.default()

    @classmethod
    def get(cls, name: str, command: str) -> RemoteSession:
        return cls._pool.get(name, command)

    @classmethod
    def retain_only(cls, names: Collection[str]) -> None:
        """Release every replica whose terminal element has left the scenes."""
        cls._pool.retain_only(names)

    @classmethod
    def pump_frame(cls) -> IdlingDecision:
        return cls._pool.pump_frame()

    @classmethod
    def close_all(cls) -> None:
        """Release only the Display's connection and replicas."""
        cls._pool.close()
