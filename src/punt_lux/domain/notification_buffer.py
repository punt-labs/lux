"""NotificationBuffer -- the property changes a patch in progress has not yet announced.

Inside a patch the telling is *buffered* and happens only when the patch commits, so a
patch that fails midway tells nobody; outside a patch there is no buffer and the
change is announced at once.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["NotificationBuffer"]


@final
class NotificationBuffer:
    """The properties a patch in progress changed, in the order they first did."""

    # PY-TS-14 OK: ``None`` means "not inside a patch, announce immediately".
    _pending: list[str] | None
    __slots__ = ("_pending",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._pending = None
        return self

    def begin(self) -> None:
        """Start buffering: the patch in progress announces nothing until it commits."""
        self._pending = []

    def discard(self) -> None:
        """Drop what the patch buffered: it failed, and announces nothing."""
        self._pending = None

    def take(self) -> list[str]:
        """End buffering; the properties the patch changed, each as often as flagged."""
        pending = self._pending or []
        self._pending = None
        return pending

    def record(self, prop: str) -> bool:
        """Buffer ``prop`` if a patch is in progress; whether it was buffered."""
        if self._pending is None:
            return False
        self._pending.append(prop)
        return True
