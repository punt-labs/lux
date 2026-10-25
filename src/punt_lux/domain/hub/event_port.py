"""EventPort -- what a link's users may do with what the display pushes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.polled_event import PolledEvent
    from punt_lux.protocol import RemoteEventHandlerInvocation

__all__ = ["EventPort"]


@runtime_checkable
class EventPort(Protocol):
    """Receive the display's interactions and business events; nothing more.

    The reader's lifecycle stays with the link that dialed the connection: a
    holder of this port cannot stop the reader (which retires the dial) or feed
    it messages.
    """

    def set_fallback_handler(
        self, handler: Callable[[RemoteEventHandlerInvocation], None]
    ) -> None:
        """Install the handler every interaction the display reports is given to."""
        ...

    def poll_event(self, timeout: float | None = None) -> PolledEvent:
        """Block for the next subscribed business event.

        Raises ``TimeoutError`` after ``timeout`` seconds.
        """
        ...
