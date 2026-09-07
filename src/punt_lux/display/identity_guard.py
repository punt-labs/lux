"""The fail-closed content-message identity guard.

An unidentified fd -- ``kind_of(fd) is None``, no ``ConnectMessage`` sent at
all -- has no attribution to install content under. This is a strictly worse
case than an already-identified ``kind="test"`` observer, which every
content-bearing handler already knew to distrust. Before this guard existed,
only ``SceneMessage`` handling checked kind at all, and even there it checked
for ``"test"`` and let ``None`` straight through -- harmless only because the
``AF_UNIX`` socket's ``0700`` permission already vouches for same-user
attribution. That stops holding the moment content is stored under a key
derived from the sender's declared identity: an unidentified connection has
no such key to store anything under. One predicate -- "is this fd
identified?" -- backs every content-bearing handler's rejection, so the gap
can never again open in just one of them.
"""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.socket_server import SocketListener

    _RecordError = Callable[[str, str, str], None]

logger = logging.getLogger(__name__)

__all__ = ["IdentityGuard"]


class IdentityGuard:
    """Reject content-bearing messages from an fd that has not identified.

    Two policies share the one underlying fact (``SocketListener.kind_of``):
    :meth:`reject_if_unidentified` is the light guard -- log, record, drop
    the message, leave the fd open -- that menu, callback-menu, and theme
    messages use uniformly. :meth:`reject_scene_unless_hub` is scene's own
    stricter, closing policy, which also turns away an identified
    ``"test"`` observer; it is layered on the same underlying fact rather
    than duplicating the "is this fd identified" check.
    """

    _socket_listener: SocketListener
    _record_error: _RecordError

    def __new__(
        cls, socket_listener: SocketListener, record_error: _RecordError
    ) -> Self:
        self = super().__new__(cls)
        self._socket_listener = socket_listener
        self._record_error = record_error
        return self

    def reject_if_unidentified(self, sock: socket.socket, message_kind: str) -> bool:
        """Reject a message from an fd that never sent a ``ConnectMessage``.

        A closed or torn-down ``sock`` fails closed too: ``fileno()`` returns
        ``-1`` rather than raising, ``kind_of(-1)`` is ``None`` the same as
        any other never-identified fd, and the ordinary reject path below
        logs and records it -- there is no separate dead-socket case to
        special-case. Returns ``True`` when the caller must drop the
        message; never closes the fd -- an identified ``"test"`` fd is let
        through here.
        """
        fd = sock.fileno()
        if self._socket_listener.kind_of(fd) is not None:
            return False
        logger.warning("unidentified fd=%d attempted %s; rejecting", fd, message_kind)
        msg = f"unidentified connection (fd={fd}) attempted {message_kind}"
        self._record_error("error", msg, "")
        return True

    def reject_scene_unless_hub(self, sock: socket.socket) -> bool:
        """Reject a ``SceneMessage`` from any fd not identified as ``kind="hub"``.

        An unidentified fd -- including a closed or torn-down ``sock``,
        whose ``fileno()`` returns ``-1`` rather than raising -- is rejected
        and closed exactly like the already-rejected ``"test"`` observer;
        neither has attribution to install a scene under. Returns ``True``
        when the caller must stop processing this message (rejected and the
        fd is gone); ``False`` only once the fd has identified as
        ``kind="hub"``.
        """
        fd = sock.fileno()
        kind = self._socket_listener.kind_of(fd)
        if kind == "hub":
            return False
        reason = "unidentified" if kind is None else "test-kind"
        logger.warning(
            "%s fd=%d attempted SceneMessage; rejecting and closing", reason, fd
        )
        self._record_error(
            "error", f"{reason} connection (fd={fd}) attempted a SceneMessage", ""
        )
        self._socket_listener.remove_client(sock)
        return True
