"""FinallyGuard -- an action that follows a body, and may not hide the body's failure.

A settle or a release runs after a body so that it happens whatever the body did. When
the body raised and the action raises too, Python lets the second replace the first,
and the read failure that caused everything disappears from the traces. The guard is a
context manager, so the action learns from ``__exit__`` what the body itself did: the
body's own exception, or none. If the body failed, the action's own failure is logged,
with its chain, and the body's failure goes on. If the body succeeded the action's
failure propagates as any would, even when the whole call runs inside someone else's
``except`` handler: nothing about the thread's state decides it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.programmer_error import ProgrammerError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

logger = logging.getLogger(__name__)

__all__ = ["FinallyGuard"]


@final
class FinallyGuard:
    """Runs an action once its ``with`` body ends, by the body's own outcome."""

    _action: Callable[[], object]
    _what: str
    __slots__ = ("_action", "_what")

    def __new__(cls, action: Callable[[], object], what: str) -> Self:
        self = super().__new__(cls)
        self._action = action
        self._what = what
        return self

    def __enter__(self) -> None:
        logger.debug("guarding the action that follows: %s", self._what)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Run the action; its failure never replaces the body's. Never swallows."""
        if exc is None:
            self._action()
            return
        try:
            self._action()
        except ProgrammerError as bug:
            # A violated invariant is never logged and forgotten, even under a
            # failing body: it propagates, with the body's failure as its cause.
            raise bug from exc
        except Exception:
            logger.exception("%s failed while handling %r", self._what, exc)
