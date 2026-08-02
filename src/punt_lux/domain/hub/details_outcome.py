"""What became of a Details click, and what each outcome has to say for itself.

A click either opened a frame or came to nothing. The second is the normal case
of a click that outlived its client — the menu is a replica, and a lease can
lapse between the paint and the pointer — not a failure of the command.

The two are two classes rather than one flag, because the difference between
them is behavior: a frame on screen is its own report, while a refusal paints
nothing at all and the log is the only place it can show. The dispatch asks the
outcome to report itself and does not ask which one it is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

__all__ = ["DetailsOutcome", "DetailsRefused", "DetailsShown"]

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True, slots=True)
class DetailsShown:
    """The frame opened for the client the entry named."""

    def reported(self) -> None:
        """Say nothing: what happened is on the screen."""


@final
@dataclass(frozen=True, slots=True)
class DetailsRefused:
    """The Hub holds no session for that connection, so nothing was painted."""

    connection_id: ConnectionId

    def reported(self) -> None:
        """Leave the one trace a click that painted nothing can leave.

        Named for the connection, because that is what tells a reader which
        entry was clicked when the frame they expected never opened.
        """
        logger.info(
            "Details clicked for %s, which the Hub no longer holds a session for",
            self.connection_id,
        )


# One or the other; the dispatch tells it to report and never asks which.
type DetailsOutcome = DetailsShown | DetailsRefused
