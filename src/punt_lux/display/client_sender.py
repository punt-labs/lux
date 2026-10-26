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
from typing import TYPE_CHECKING, Self, final

from punt_lux.bounded_send import BoundedSend
from punt_lux.protocol import AckMessage, encode_message

if TYPE_CHECKING:
    import socket

    from punt_lux.display.client_host_port import ClientHost
    from punt_lux.protocol import RemoteEventHandlerInvocation
    from punt_lux.protocol.messages import Message

__all__ = ["ClientSender"]

logger = logging.getLogger(__name__)

# A full buffer drains in tens of ms once the peer reads -- this only bounds
# a genuinely stuck peer, absent a caller deadline.
_ONE_OFF_SEND_BUDGET = 1.0


@final
class ClientSender:
    """Send to clients under the frame's budget; sever one that misses a reply."""

    _host: ClientHost
    _frame_deadline: float | None  # bounds in-frame sends when set by the render loop
    # Scenes installed and not yet acked: the client and the scene, in receipt order.
    _held_acks: list[tuple[socket.socket, str]]
    __slots__ = ("_frame_deadline", "_held_acks", "_host")

    def __new__(cls, host: ClientHost) -> Self:
        self = super().__new__(cls)
        self._host = host
        self._frame_deadline = None
        self._held_acks = []
        return self

    def set_frame_deadline(self, deadline: float) -> None:
        """Bound every deadline-less send this frame against backpressure wedges."""
        self._frame_deadline = deadline

    def clear_frame_deadline(self) -> None:
        """Restore the one-off send budget for post-frame sends (screenshot, etc.)."""
        self._frame_deadline = None

    def send_to_client(
        self, sock: socket.socket, event: RemoteEventHandlerInvocation
    ) -> bool:
        """Send an interaction; return whether it landed before its deadline.

        Only an event leaves this way (its sender holds one that missed and retries
        it); a reply goes through ``reply_to_client``, which the type makes the only
        door for one.
        """
        return self._transmit(sock, event)

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

    def hold_ack(self, sock: socket.socket, scene_id: str) -> None:
        """Note a scene installed for ``sock``; its ack goes out at the next swap.

        The ack tells the Hub the scene survived being drawn, so it is sent only
        once a buffer swap has completed after the install, never on receipt.
        """
        self._held_acks.append((sock, scene_id))

    def release_acks(self) -> None:
        """Ack every scene installed since the last swap, in the order received.

        Called once a swap has completed. Visibility does not matter: a scene in a
        background tab or a docked frame is acked with the rest. A client that left
        before the swap has no one to hear its acks, so they are dropped.
        """
        held, self._held_acks = self._held_acks, []
        for sock, scene_id in held:
            if self._host.is_client(sock):
                self.reply_to_client(
                    sock, AckMessage(scene_id=scene_id, ts=time.time())
                )

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
