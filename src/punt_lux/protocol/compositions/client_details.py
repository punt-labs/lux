"""The Details scene — one client's connection state, constructed Hub-side.

``target.md``: "the Hub decodes or constructs typed UI objects." Details is the
Hub reporting on its *own* state — who is connected as this client, since when,
on what lease, holding which topics and scenes — so it constructs its element
tree here rather than any client shipping one. It executes nothing outside the
Hub and reads nothing but the Hub's session registry.

The wire identity a menu label no longer carries lands here: the declared name
with its distinctness token, the kind, the repository, the connection id.

The scene is a two-column grid of field and value. Every value is rendered for a
person to read — a duration as minutes and seconds, an empty list as ``none`` —
because a client's details are looked at, not parsed. The facts render
themselves: a lease knows whether it ever lapses, and a duration knows how a
person says it, so neither is a case for this module to open.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.domain.hub.lease_term import LeaseTerm
from punt_lux.domain.span import Span
from punt_lux.protocol.elements.table import TableElement

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement

__all__ = ["ClientDetails", "ClientDetailsComposition"]

# What a field with nothing in it reads as, so a row never renders blank.
_NOTHING = "none"


class ClientDetails(BaseModel):
    """One client's connection state, and the lines a person reads it as.

    ``repo`` and ``agent`` are genuine absences — a headless command owns no
    repository, and only an agent carries a handle — so each reads as ``none``
    rather than rendering blank.
    """

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)  # the name the menu calls this client
    connection_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    name: str = Field(min_length=1)
    repo: str | None = None  # absent for a headless command and for a daemon
    agent: str | None = None  # absent unless the client is an agent
    connected_seconds: float
    lease: LeaseTerm
    subscribed_topics: tuple[str, ...] = ()
    owned_scenes: tuple[str, ...] = ()

    def rows(self) -> tuple[tuple[str, str], ...]:
        """Return the field/value pairs, in the order a reader wants them."""
        return (
            ("Client", self.label),
            ("Kind", self.kind),
            ("Declared name", self.name),
            ("Repository", self.repo or _NOTHING),
            ("Agent", self.agent or _NOTHING),
            ("Connection", self.connection_id),
            ("Connected", Span.of(self.connected_seconds).rendered()),
            ("Lease", self.lease.rendered()),
            ("Topics", self._listed(self.subscribed_topics)),
            ("Scenes", self._listed(self.owned_scenes)),
        )

    @staticmethod
    def _listed(values: Sequence[str]) -> str:
        """Render a list of names as one line, or say there are none."""
        return ", ".join(values) if values else _NOTHING


@final
class ClientDetailsComposition:
    """Build the element tree that reports one client's connection state."""

    __slots__ = ()

    @staticmethod
    def build(details: ClientDetails, *, element_id: str) -> Sequence[DomainElement]:
        """Return the roots of the Details scene for ``details``."""
        return [
            TableElement(id=element_id, columns=("Field", "Value"), rows=details.rows())
        ]
