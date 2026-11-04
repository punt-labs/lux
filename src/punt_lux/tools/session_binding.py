"""SessionBinding -- the context bindings one MCP session holds, released as one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from contextvars import Token

    from punt_lux.client_host import ClientHost

__all__ = ["SessionBinding"]


@final
@dataclass(frozen=True, slots=True)
class SessionBinding:
    """The two context bindings one MCP session holds, released together."""

    key: Token[str]
    client_host: Token[ClientHost]

    def release(self) -> None:
        """Release both bindings, the host first as it was bound last."""
        self.client_host.var.reset(self.client_host)
        self.key.var.reset(self.key)
