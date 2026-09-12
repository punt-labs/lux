"""The Hub-owned topic namespace agents may not subscribe to or publish on."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from punt_lux.operations.models import OpError

__all__ = ["RESERVED_TOPICS", "ReservedTopics"]


@final
@dataclass(frozen=True, slots=True)
class ReservedTopics:
    """The topic namespace whose events the Hub owns and a reader trusts.

    Topics under the reserved prefix (``lux.``) carry Hub-emitted events —
    ``lux.menu`` menu clicks today, any future ``lux.*`` — whose payloads a
    ``recv()`` reader trusts to be genuine. The Hub delivers them by enqueuing
    directly on a session inbox, never through the public publish path, so
    reserving the prefix at every public topic entry point is what makes
    "reserved" true: an agent cannot subscribe to or publish a reserved topic,
    and so cannot spoof a Hub event onto its own event stream (nor, were pub-sub
    fan-out ever cross-session rather than self-scoped, onto another's).
    """

    _prefix: str = "lux."

    def covers(self, topic: str) -> bool:
        """Return whether ``topic`` lives in the reserved namespace."""
        return topic.startswith(self._prefix)

    def rejection(self, topic: str) -> OpError:
        """Build the ``invalid_request`` refusing a reserved-topic operation."""
        return OpError(
            code="invalid_request",
            reason=(
                f"topic {topic!r} is in the reserved {self._prefix!r} namespace; "
                "reserved topics carry Hub-owned events and cannot be subscribed "
                "to or published by an agent"
            ),
        )


RESERVED_TOPICS: ReservedTopics = ReservedTopics()
