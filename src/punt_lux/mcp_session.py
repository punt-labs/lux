"""Per-connection registration and cleanup for luxd's stateful MCP HTTP leg."""

from __future__ import annotations

from collections import Counter
from typing import Self, final

__all__ = ["SessionRegistry"]


@final
class SessionRegistry:
    """The live MCP sessions, counted per instance for the health probe.

    Keyed by session key but summed by instance: two sessions under one key
    count as two, and the first to disconnect leaves the peer counted (a set
    would drop the peer). Cleanup keys on the ``ConnectionId``, so :meth:`discard`
    reports whether its call drained the key — the last session out is the one
    that may tear the shared scope down.
    """

    _active: Counter[str]
    __slots__ = ("_active",)

    def __new__(cls) -> Self:
        """Start with no registered MCP sessions."""
        self = super().__new__(cls)
        self._active = Counter()
        return self

    def add(self, key: str) -> None:
        """Record one live session under ``key``."""
        self._active[key] += 1

    def discard(self, key: str) -> bool:
        """Drop one live session under ``key``; report whether the key is drained.

        Returns ``True`` when no live session remains under ``key`` (the last
        same-key session left, so its shared scope may now be torn down) and
        ``False`` while a peer is still counted. Idempotent: discarding an absent
        or already-drained key is a no-op that reports ``True``.
        """
        self._active -= Counter({key: 1})
        return key not in self._active

    @property
    def count(self) -> int:
        """How many MCP sessions are live right now."""
        return self._active.total()
