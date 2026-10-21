"""OwnerRows — the rows the frame-info popup shows for a frame's owner."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.identity import HubId

__all__ = ["OwnerRows"]

logger = logging.getLogger(__name__)

# Shown when no facts were ever replicated for the frame. A departed owner is
# not this case: the display keeps its last snapshot. It is the Hub unable to
# resolve an owner, a Hub that predates owner facts, a push whose entries were
# all malformed, or a ``(hub, frame_id)`` that matches no push. Distinct from a
# resolved-but-empty result, so opening the popup is never a silent no-op.
_UNKNOWN_OWNER_ROWS: tuple[tuple[str, str], ...] = (("Owner", "unknown"),)


@final
class OwnerRows:
    """Replicated owner facts by ``(hub, frame_id)``, with an explicit unknown row."""

    _facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None]
    __slots__ = ("_facts_for",)

    def __new__(
        cls, facts_for: Callable[[str, HubId], tuple[tuple[str, str], ...] | None]
    ) -> Self:
        self = super().__new__(cls)
        self._facts_for = facts_for
        return self

    def for_open(self, frame_id: str, hub: HubId) -> tuple[tuple[str, str], ...]:
        """Return the rows for opening the popup, warning when none were replicated.

        Runs once per click, so the warning is one line per event.
        """
        resolved = self._facts_for(frame_id, hub)
        if resolved is None:
            logger.warning(
                "no owner facts replicated for hub=%s frame=%s; popup shows unknown",
                hub,
                frame_id,
            )
            return _UNKNOWN_OWNER_ROWS
        return resolved

    def for_refresh(self, frame_id: str, hub: HubId) -> tuple[tuple[str, str], ...]:
        """Return the current rows; silent, as it runs every frame the popup is open."""
        resolved = self._facts_for(frame_id, hub)
        return resolved if resolved is not None else _UNKNOWN_OWNER_ROWS
