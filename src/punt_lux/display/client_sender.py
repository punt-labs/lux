"""ClientSender -- what the display sends its clients, and what a miss costs.

Two doors, because the two kinds of message differ in what a missed deadline means.
An interaction is held and retried by its sender, so it goes out through
:meth:`ClientSender.send_to_client`, which reports whether it landed. A reply is
matched to its request by order and a dialer waits for its ``ReadyMessage``, so one
the client misses must end the connection: :meth:`ClientSender.reply_to_client`.
:meth:`ClientSender._transmit` is the one place a byte leaves for a client.

The frame deadline is the send budget the render loop arms for one frame; with none
armed a send takes its own one-off budget.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.bounded_send import BoundedSend
from punt_lux.protocol import RemoteEventHandlerInvocation, encode_message

if TYPE_CHECKING:
    import socket

    from punt_lux.protocol.messages import Message

__all__ = ["ClientSender", "SenderHost"]

logger = logging.getLogger(__name__)

# A full buffer drains in tens of ms once the peer reads -- this only bounds
# a genuinely stuck peer, absent a caller deadline.
_ONE_OFF_SEND_BUDGET = 1.0


class SenderHost(Protocol):
    """What the sender needs of the listener that owns the clients."""

    def remove_client(self, sock: socket.socket) -> None:
        """Drop a dead or severed client and clean up its per-fd state."""
        ...

    def is_client(self, sock: socket.socket) -> bool:
        """Return whether ``sock`` is still a live registered client."""
        ...


@final
class ClientSender:
    """Send to clients under the frame's budget; sever one that misses a reply."""

    _host: SenderHost
    _frame_deadline: float | None  # bounds in-frame sends when set by the render loop
    __slots__ = ("_frame_deadline", "_host")

    def __new__(cls, host: SenderHost) -> Self:
        self = super().__new__(cls)
        self._host = host
        self._frame_deadline = None
        return self

    @property
    def frame_deadline(self) -> float | None:
        """Return the deadline armed by :meth:`set_frame_deadline`, if any."""
        return self._frame_deadline

    def set_frame_deadline(self, deadline: float) -> None:
        """Bound every deadline-less send this frame against backpressure wedges."""
        self._frame_deadline = deadline

    def clear_frame_deadline(self) -> None:
        """Restore the one-off send budget for post-frame sends (screenshot, etc.)."""
        self._frame_deadline = None

    def send_to_client(self, sock: socket.socket, msg: Message) -> bool:
        """Send an interaction; return whether it landed before its deadline.

        Only an event leaves this way (its sender holds one that missed and retries
        it); a reply raises ``TypeError`` unsent and goes through ``reply_to_client``.
        """
        if not isinstance(msg, RemoteEventHandlerInvocation):
            err = f"{type(msg).__name__} is not an event: reply_to_client sends it"
            raise TypeError(err)
        return self._transmit(sock, msg)

    def reply_to_client(self, sock: socket.socket, msg: Message) -> None:
        """Send a reply the client waits for, or end its connection.

        The Hub matches replies to requests by order, so one dropped on a live
        connection would shift every later one, and a dialer waits for its
        ``ReadyMessage``; an event, by contrast, is held and retried by its sender.
        """
        if self._transmit(sock, msg) or not self._host.is_client(sock):
            return  # sent, or a dead peer _transmit already removed
        logger.warning("severing %s: %s missed its deadline", sock, type(msg).__name__)
        self._host.remove_client(sock)

    def _transmit(self, sock: socket.socket, msg: Message) -> bool:
        """The one place a byte leaves for a client; whether it beat its deadline.

        A slow-but-alive peer (``BlockingIOError``) keeps the client and defers;
        only a dead peer (``OSError``) removes it.
        """
        deadline = (
            self._frame_deadline
            if self._frame_deadline is not None
            else time.monotonic() + _ONE_OFF_SEND_BUDGET
        )
        try:
            BoundedSend().send(sock, encode_message(msg), deadline)
        except BlockingIOError:
            return False  # alive but slow past the deadline -- defer, do not remove
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "send failed (%s); dropped %s, removing client",
                type(exc).__name__,
                type(msg).__name__,
            )
            self._host.remove_client(sock)
            return False
        return True
