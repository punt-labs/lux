"""What luxd's one display connection can answer with, as the operations see it.

A proxied operation reaches the display over luxd's single connection and gets
back one of these. The operation maps the reply to a typed result or an
``OpError``; it never sees a socket, a timeout knob, or a reconnect. The four
outcomes are closed: the display answered with a payload, answered with an error
sentence, was not running, or did not answer in time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True, slots=True)
class DisplayErrored:
    """The display answered, but with an error sentence instead of a result."""

    message: str


@dataclass(frozen=True, slots=True)
class DisplayFault:
    """The round-trip never produced an answer.

    ``display_unavailable`` means no display process is running; ``timeout``
    means the bounded send or receive elapsed (or the peer died mid-send). The
    code maps straight onto the matching ``OpError`` code.
    """

    code: Literal["display_unavailable", "timeout"]


# A proxied round-trip yields exactly one of these.
type DisplayReply = DisplayReplied | DisplayErrored | DisplayFault
