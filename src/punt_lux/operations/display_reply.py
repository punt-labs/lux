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
from dataclasses import dataclass
from typing import ClassVar, Literal

from punt_lux.operations.models.common import OpError

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

    def resolve(self) -> Mapping[str, object] | OpError:
        """A payload reply resolves to its payload."""
        return self.payload


@dataclass(frozen=True, slots=True)
class DisplayErrored:
    """The display answered, but with an error sentence instead of a result."""

    message: str

    def resolve(self) -> Mapping[str, object] | OpError:
        """A display-reported error resolves to a ``rejected`` OpError."""
        return OpError(code="rejected", reason=self.message)


@dataclass(frozen=True, slots=True)
class DisplayFault:
    """The round-trip never produced an answer.

    ``display_unavailable`` means no display process is running; ``timeout``
    means the bounded send or receive elapsed (or the peer died mid-send). The
    code maps straight onto the matching ``OpError`` code.
    """

    code: Literal["display_unavailable", "timeout"]

    _REASON: ClassVar[dict[str, str]] = {
        "display_unavailable": "display is not running",
        "timeout": "display did not respond in time",
    }

    def resolve(self) -> Mapping[str, object] | OpError:
        """A fault resolves to the OpError its code names."""
        return OpError(code=self.code, reason=self._REASON[self.code])


# A proxied round-trip yields exactly one of these.
type DisplayReply = DisplayReplied | DisplayErrored | DisplayFault
