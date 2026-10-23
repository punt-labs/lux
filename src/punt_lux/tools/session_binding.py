"""SessionBinding -- the context bindings one MCP session holds, released as one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextvars import Token

__all__ = ["SessionBinding"]


@dataclass(frozen=True, slots=True)
class SessionBinding:
    """The two context bindings one MCP session holds, released together."""

    key: Token[str]
    peer: Token[str | None]
