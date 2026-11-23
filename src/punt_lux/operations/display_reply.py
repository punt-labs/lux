"""What luxd's one display connection can answer with, as the operations see it.

A proxied operation reaches the display over luxd's single connection and gets
back one of these. Each reply knows how to ``resolve`` itself to either the
display's payload or the matching ``OpError`` — polymorphism instead of a match
every proxied operation would otherwise repeat. The four outcomes are closed:
the display answered with a payload, answered with an error sentence, was not
running, or did not answer in time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.hub_connection import HubConnection

__all__ = [
    "DisplayErrored",
    "DisplayFault",
    "DisplayReplied",
    "DisplayReply",
]


@dataclass(frozen=True, slots=True)
class DisplayReplied:
    """The display answered with a result payload.

    ``payload`` is the display's own response shape — a fact about the running
    process that each operation narrows into its own typed result (PY-TS-14 wire
    boundary), so it stays a raw mapping here.
    """

    payload: Mapping[str, object]
    connection: HubConnection = field(default_factory=HubConnection)

    def resolve(self) -> Mapping[str, object] | OpError:
        """Resolve a successful display reply to its payload."""
        return self.payload


@dataclass(frozen=True, slots=True)
class DisplayErrored:
    """The display answered, but with an error sentence instead of a result."""

    message: str

    def resolve(self) -> OpError:
        """Convert a display-reported error to a rejected operation."""
        return OpError(code="rejected", reason=self.message)


class DisplayFault(Enum):
    """The two failures to obtain an answer, with their operation errors."""

    UNAVAILABLE = ("display_unavailable", "display is not running")
    TIMEOUT = ("timeout", "display did not respond in time")
    _value_: tuple[Literal["display_unavailable", "timeout"], str]

    def resolve(self) -> OpError:
        """Convert a reply fault to its immutable operation error."""
        return OpError(code=self.value[0], reason=self.value[1])


# A proxied round-trip yields exactly one of these.
type DisplayReply = DisplayReplied | DisplayErrored | DisplayFault
