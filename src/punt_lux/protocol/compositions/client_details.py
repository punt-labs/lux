"""The Details scene — one client's connection state, constructed Hub-side.

``target.md``: "the Hub decodes or constructs typed UI objects." Details is the
Hub reporting on its *own* state — who is connected as this client, since when,
on what lease, holding which topics and scenes — so it constructs its element
tree here rather than any client shipping one. It executes nothing outside the
Hub and reads nothing but the Hub's session registry.

The wire identity a menu label no longer carries lands here: the declared name
with its distinctness token, the kind, the repository, the connection id.

The scene is a two-column grid of field and value. Every value is rendered for a
person to read — a duration as minutes and seconds, a lease that never lapses as
``permanent``, an empty list as ``none`` — because a client's details are looked
at, not parsed.
"""

from __future__ import annotations

from math import isinf
from typing import TYPE_CHECKING, final

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.protocol.elements.table import TableElement

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement

__all__ = ["ClientDetails", "ClientDetailsComposition"]

# What a field with nothing in it reads as, so a row never renders blank.
_NOTHING = "none"

# What a lease that never lapses reads as.
_PERMANENT = "permanent"

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


class ClientDetails(BaseModel):
    """One client's connection state, as the Details scene reports it.

    The raw facts, not their rendering: the composition below turns each into
    the line a person reads. ``repo`` and ``agent`` are genuine absences — a
    headless command owns no repository, and only an agent carries a handle.
    """

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)  # the name the menu calls this client
    connection_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)
    repo: str | None = None  # absent for a headless command and for a daemon
    agent: str | None = None  # absent unless the client is an agent
    connected_seconds: float
    lease_ttl_seconds: float
    subscribed_topics: tuple[str, ...] = ()
    owned_scenes: tuple[str, ...] = ()


@final
class ClientDetailsComposition:
    """Build the element tree that reports one client's connection state."""

    __slots__ = ()

    @classmethod
    def build(
        cls, details: ClientDetails, *, element_id: str
    ) -> Sequence[DomainElement]:
        """Return the roots of the Details scene for ``details``."""
        return [
            TableElement(
                id=element_id,
                columns=("Field", "Value"),
                rows=cls._rows(details),
            )
        ]

    @classmethod
    def _rows(cls, details: ClientDetails) -> tuple[tuple[str, str], ...]:
        """Return the field/value pairs, in the order a reader wants them."""
        return (
            ("Client", details.label),
            ("Kind", details.kind),
            ("Declared name", details.name),
            ("Repository", details.repo or _NOTHING),
            ("Agent", details.agent or _NOTHING),
            ("Connection", details.connection_id),
            ("Connected", cls._duration(details.connected_seconds)),
            ("Lease", cls._lease(details.lease_ttl_seconds)),
            ("Topics", cls._listed(details.subscribed_topics)),
            ("Scenes", cls._listed(details.owned_scenes)),
        )

    @staticmethod
    def _listed(values: Sequence[str]) -> str:
        """Render a list of names as one line, or say there are none."""
        return ", ".join(values) if values else _NOTHING

    @classmethod
    def _lease(cls, seconds: float) -> str:
        """Render a lease length; an endless one is permanent, not ``inf``."""
        return _PERMANENT if isinf(seconds) else cls._duration(seconds)

    @staticmethod
    def _duration(seconds: float) -> str:
        """Render a span of seconds the way a person says it."""
        whole = int(seconds)
        if whole < _SECONDS_PER_MINUTE:
            return f"{whole}s"
        if whole < _SECONDS_PER_HOUR:
            return f"{whole // _SECONDS_PER_MINUTE}m {whole % _SECONDS_PER_MINUTE:02d}s"
        minutes = whole % _SECONDS_PER_HOUR // _SECONDS_PER_MINUTE
        return f"{whole // _SECONDS_PER_HOUR}h {minutes:02d}m"
