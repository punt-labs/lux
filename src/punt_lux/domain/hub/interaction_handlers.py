"""InteractionHandlers -- the handler a display interaction is answered by.

An interaction the display reports (a click, an edit) runs the fallback handler the
Hub installs for Hub-side element dispatch, else it is dropped. The handler runs on
the listener thread while another thread installs it, so it sits behind a lock that
no socket I/O ever holds.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["InteractionHandlers"]

type InteractionHandler = Callable[[RemoteEventHandlerInvocation], None]


@final
class InteractionHandlers:
    """The fallback handler, and the answer to one interaction."""

    _lock: threading.Lock
    # None = no handler installed; an interaction is then dropped.
    _fallback: InteractionHandler | None
    __slots__ = ("_fallback", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._fallback = None
        return self

    def set_fallback(self, handler: InteractionHandler) -> None:
        """Answer interactions with ``handler``."""
        with self._lock:
            self._fallback = handler

    def run(self, msg: RemoteEventHandlerInvocation) -> None:
        """Answer ``msg`` with the handler, else drop it.

        A raising handler is logged and the event consumed (never re-queued),
        which keeps the listener thread alive at the cost of the event.
        """
        with self._lock:
            fallback = self._fallback
        if fallback is None:
            logger.debug(
                "Dropping interaction with no handler: %s:%s",
                msg.element_id,
                msg.action,
            )
            return
        logger.debug(
            "dispatch fallback element_id=%s action=%s scene_id=%s",
            msg.element_id,
            msg.action,
            msg.scene_id,
        )
        with self._safely(
            "Fallback handler error for %s:%s", msg.element_id, msg.action
        ):
            fallback(msg)

    @staticmethod
    @contextlib.contextmanager
    def _safely(error_fmt: str, *log_args: object) -> Generator[None]:
        """Suppress and log any exception raised in the block, per *error_fmt*."""
        try:
            yield
        except Exception:
            logger.exception(error_fmt, *log_args)
