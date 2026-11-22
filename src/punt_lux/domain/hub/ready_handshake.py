"""Receive the Display's Ready frame and enforce the shared wire generation."""

from __future__ import annotations

import logging
import socket

from punt_lux.domain.hub.handshake_outcome import DisplayNotConnectedError
from punt_lux.wire.model import PROTOCOL_VERSION, ReadyMessage, recv_message
from punt_lux.wire.model.messages.wire_vocabulary import DISPLAY_VOCABULARY

__all__ = ["ReadyHandshake"]

logger = logging.getLogger(__name__)


class ReadyHandshake:
    """Own the Ready-frame boundary, closing incompatible or failed connections."""

    @classmethod
    def receive(
        cls, sock: socket.socket, endpoint: str, connect_timeout: float
    ) -> ReadyMessage:
        """Read a compatible Ready or close the socket and report the failure."""
        try:
            ready = recv_message(sock, DISPLAY_VOCABULARY, timeout=connect_timeout)
            if ready is None:
                msg = f"Handshake timed out after {connect_timeout}s at {endpoint}"
                raise DisplayNotConnectedError(msg)
            return cls._require_ready(ready)
        except Exception:
            sock.close()
            raise

    @staticmethod
    def _require_ready(ready: object) -> ReadyMessage:
        """Refuse incompatible peers before declaring identity or sending scenes."""
        if isinstance(ready, ReadyMessage) and ready.version == PROTOCOL_VERSION:
            return ready
        msg = (
            f"Expected ReadyMessage protocol {PROTOCOL_VERSION}, got {ready!r}. "
            "Restart luxd-display with `make restart` or `lux service restart`."
        )
        logger.log(
            logging.ERROR if isinstance(ready, ReadyMessage) else logging.WARNING,
            "Handshake mismatch: %s",
            msg,
        )
        raise DisplayNotConnectedError(msg)
