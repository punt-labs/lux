"""SessionLease — how long a Hub session stays live between contacts.

A session is live while its lease has not lapsed, and any authenticated contact
renews it. The lease length is set by the client's cadence, declared through its
kind: an ``mcp-session`` holds a live connection but idles between tool calls, so
its lease is generous; a ``cli`` invocation re-identifies deterministically every
run and nothing depends on its entry outliving the command, so its lease is short
and its registry entry is swept promptly; luxd's own ``app`` built-ins live for
the whole process, so their lease never lapses.

The lease carries no kind knowledge itself — it is pure time arithmetic — and the
kind-to-length policy lives here beside it, keyed by the string a ``ClientKind``
already is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientKind

__all__ = ["SessionLease"]

# The lease length per client kind, in seconds. An ``mcp-session`` idles between
# tool calls but its live connection means it is alive, so 30 minutes is a
# backstop against a wedged connection rather than a liveness probe; a ``cli`` run
# re-identifies each time, so 90 seconds sweeps its entry soon after it exits; an
# ``app`` built-in is permanent.
_TTL_BY_KIND: dict[str, float] = {
    "mcp-session": 1800.0,
    "cli": 90.0,
    "app": math.inf,
}

# A connected-but-unidentified session is an MCP session mid-handshake — it has
# bound its connection but not yet declared identity — so it gets the generous
# grace rather than being swept before it can identify.
_UNIDENTIFIED_TTL = 1800.0


@dataclass(frozen=True, slots=True)
class SessionLease:
    """A renewal time and a length; the session is live until they lapse."""

    renewed_at: float
    ttl_seconds: float

    @classmethod
    def unidentified(cls, now: float) -> Self:
        """The lease a session holds before it has declared an identity."""
        return cls(now, _UNIDENTIFIED_TTL)

    @classmethod
    def for_kind(cls, kind: ClientKind, now: float) -> Self:
        """The lease a session of ``kind`` holds, renewed at ``now``."""
        return cls(now, _TTL_BY_KIND[kind])

    @classmethod
    def for_declared(cls, kind: ClientKind, ttl: float | None, now: float) -> Self:
        """The lease a session holds: its declared ``ttl`` when given, else its kind's.

        An originator that declares a TTL sets its own cadence; one that declares
        none falls to the kind default, which is how luxd's built-ins stay permanent
        without carrying a TTL. The declared value is already bounds-checked at the
        identity boundary, so this is pure selection.
        """
        return cls(now, ttl) if ttl is not None else cls.for_kind(kind, now)

    def is_live(self, now: float) -> bool:
        """Whether the lease has not lapsed as of ``now``."""
        return now - self.renewed_at <= self.ttl_seconds

    def renewed(self, now: float) -> Self:
        """Return this lease renewed at ``now``, keeping its length."""
        return type(self)(now, self.ttl_seconds)
