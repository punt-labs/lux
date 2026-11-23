"""Subscription handle returned by Display.subscribe — cancellable callback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self

__all__ = ["Subscription"]


type _Cancel = Callable[[], None]


class Subscription:
    """Cancellable handle to a Display.subscribe registration.

    The display owns the subscriber list; this handle just remembers how
    to detach. ``cancel`` is idempotent — calling it twice is a no-op.
    """

    _cancel: _Cancel | None

    def __new__(cls, cancel: _Cancel) -> Self:
        self = super().__new__(cls)
        self._cancel = cancel
        return self

    def cancel(self) -> None:
        """Detach the subscriber. Idempotent."""
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    @property
    def is_active(self) -> bool:
        """True iff the subscription has not been cancelled."""
        return self._cancel is not None
