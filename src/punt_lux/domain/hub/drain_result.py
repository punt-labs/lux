"""DrainResult -- what the last look at a dial's socket found, or why there was none."""

from __future__ import annotations

import logging
import ssl
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["CutShort", "DrainIncompleteError", "Drained"]


class DrainIncompleteError(Exception):
    """The last look could not be made: a writer held the socket past its ceiling."""


@dataclass(frozen=True, slots=True)
class Drained:
    """What one last look at a socket found: bytes, whether its stream ended."""

    chunk: bytes
    ended: bool


@dataclass(frozen=True, slots=True)
class CutShort:
    """A last look that found the stream broken: the settle goes ahead on it."""

    endpoint: str
    cause: BaseException

    def report(self, *, captured: bool, is_tls: bool) -> None:
        """Say so at the level the cause deserves.

        Quietly when the stream simply ended (a reset on the same host, a broken
        pipe, TLS end of file) or was closed by the dial's own capture, which this
        look lost the race to. Loudly for a reset from a remote peer, which can
        discard acks queued behind it and so charge a scene that survived, and for
        anything else (a closed descriptor, a TLS fault): a later look at why a
        surviving scene was charged finds the trace.
        """
        if captured:
            logger.debug(
                "Drain of %s found the socket closed by its own capture: %r",
                self.endpoint,
                self.cause,
            )
        elif isinstance(self.cause, ConnectionResetError) and is_tls:
            logger.warning(
                "Drain of %s cut short by a reset from a remote display, which may "
                "have discarded acks queued behind it: a scene it acked may be "
                "charged: %r",
                self.endpoint,
                self.cause,
            )
        else:
            ended = isinstance(self.cause, ConnectionError | ssl.SSLEOFError)
            logger.log(
                logging.DEBUG if ended else logging.WARNING,
                "Drain of %s cut short: %r",
                self.endpoint,
                self.cause,
            )
