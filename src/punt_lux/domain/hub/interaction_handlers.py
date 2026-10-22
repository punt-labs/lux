"""InteractionHandlers -- the callbacks a display interaction is answered by.

An interaction the display reports (a click, an edit) runs the callback
registered for its ``(element_id, action)`` key, else the fallback handler the
Hub installs for Hub-side element dispatch, else it is dropped. Handlers run on
the listener thread while other threads register and remove them, so the
registry and the fallback share one lock that no socket I/O ever holds.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.callback_key import CallbackKey

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["InteractionHandlers"]

type InteractionHandler = Callable[[RemoteEventHandlerInvocation], None]


@final
class InteractionHandlers:
    """Registered callbacks plus the fallback, and the answer to one interaction."""

    _lock: threading.Lock
    _callbacks: dict[CallbackKey, InteractionHandler]
    # None = no fallback installed; an unmatched interaction is then dropped.
    _fallback: InteractionHandler | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.Lock()
        self._callbacks = {}
        self._fallback = None
        return self

    @property
    def any_registered(self) -> bool:
        """Whether any ``(element_id, action)`` callback is registered."""
        with self._lock:
            return bool(self._callbacks)

    def register(self, key: CallbackKey, callback: InteractionHandler) -> None:
        """Answer interactions keyed ``key`` with ``callback``."""
        with self._lock:
            self._callbacks[key] = callback

    def remove(self, key: CallbackKey) -> None:
        """Stop answering ``key``; a no-op if it was never registered."""
        with self._lock:
            self._callbacks.pop(key, None)

    def set_fallback(self, handler: InteractionHandler) -> None:
        """Answer interactions no callback is registered for with ``handler``."""
        with self._lock:
            self._fallback = handler

    def run(self, msg: RemoteEventHandlerInvocation) -> None:
        """Answer ``msg`` with its callback, else the fallback, else drop it.

        A raising handler is logged and the event consumed (never re-queued),
        which keeps the listener thread alive at the cost of the event.
        """
        with self._lock:
            callback = self._callbacks.get(CallbackKey(msg.element_id, msg.action))
            fallback = self._fallback
        if callback is not None:
            with self._safely(
                "Callback error for %s:%s (event consumed)", msg.element_id, msg.action
            ):
                callback(msg)
        elif fallback is not None:
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
        else:
            logger.debug(
                "Dropping interaction with no callback: %s:%s",
                msg.element_id,
                msg.action,
            )

    @staticmethod
    @contextlib.contextmanager
    def _safely(error_fmt: str, *log_args: object) -> Generator[None]:
        """Suppress and log any exception raised in the block, per *error_fmt*."""
        try:
            yield
        except Exception:
            logger.exception(error_fmt, *log_args)
