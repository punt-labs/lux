"""DisplayLostError -- the display ended its dial and the redial found nobody home.

A dial the display ended is evidence that it died, and a sender that finds it gone
is charged with what it was sending. When the redial that follows fails as well,
there is no dial left to carry that evidence, so the error carries the name of the
dial the display ended: whoever attributes the death does it once, against that dial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_ref import DialRef

__all__ = ["DisplayLostError"]


@dataclass(eq=False)  # an exception cannot be frozen: it gets a traceback attached
class DisplayLostError(DisplayNotConnectedError):
    """No display answered the redial, after the last dial was ended by the display."""

    reason: str  # why the redial failed
    dial: DialRef  # the dial the display ended: what the death is attributed against

    def __str__(self) -> str:
        return self.reason
