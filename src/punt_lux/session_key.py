"""The MCP session identity luxd admits onto the hub.

The raw ``?session_key=`` query value is sanitized here into the connection
identity a session claims. There is no reserved identity: every REST and
command-line caller now carries its own declared identity, so no shared
pseudo-connection exists for an MCP session to collide with.
"""

from __future__ import annotations

import re
import uuid
from typing import Self, final

from punt_lux.domain.ids import ConnectionId

__all__ = ["SessionKey"]

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


@final
class SessionKey:
    """A sanitized MCP session key resolved to a hub :class:`ConnectionId`.

    The raw ``?session_key=`` query value is a log-injection and identity
    vector, so it is stripped of control characters and capped on construction;
    the sanitized value is what becomes the connection identity, not merely what
    is logged.
    """

    _value: str
    __slots__ = ("_value",)

    def __new__(cls, raw: str | None) -> Self:
        self = super().__new__(cls)
        self._value = _CONTROL_CHAR_RE.sub("", raw or "")[:64]
        return self

    @classmethod
    def from_request(cls, raw: str) -> Self:
        """Resolve a query value; a blank-after-sanitize value gets a handle."""
        return cls(cls(raw).value or str(uuid.uuid4())[:8])

    @property
    def value(self) -> str:
        """The sanitized key, safe to log and to use as an identity."""
        return self._value

    @property
    def connection_id(self) -> ConnectionId:
        """The hub connection this session claims."""
        return ConnectionId(self._value)

    def __str__(self) -> str:
        return self._value
