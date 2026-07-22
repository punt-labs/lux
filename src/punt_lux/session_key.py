"""The MCP session identity luxd admits onto the hub.

One connection identity is reserved for the connection-less REST surface
(:data:`punt_lux.rest.app.DEFAULT_SCOPE` scopes every REST request to it). An
MCP session may not claim it: sharing it would cross scene, menu, and topic
ownership, and the session's disconnect cascade would destroy REST-created
state. This module owns both the reserved constant and the rule that enforces
it, so the REST scope and luxd's admission check read one source of truth.
"""

from __future__ import annotations

import re
import uuid
from typing import Self, final

from punt_lux.domain.ids import ConnectionId

__all__ = ["RESERVED_REST_CONNECTION", "SessionKey"]

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

# The connection identity the connection-less REST surface owns.
RESERVED_REST_CONNECTION = ConnectionId("rest")


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
        """Resolve a query-param value, defaulting a blank to a random handle."""
        return cls(raw or str(uuid.uuid4())[:8])

    @property
    def value(self) -> str:
        """The sanitized key, safe to log and to use as an identity."""
        return self._value

    @property
    def connection_id(self) -> ConnectionId:
        """The hub connection this session claims."""
        return ConnectionId(self._value)

    @property
    def is_reserved(self) -> bool:
        """Whether this key collides with the reserved REST identity."""
        return self.connection_id == RESERVED_REST_CONNECTION

    def __str__(self) -> str:
        return self._value
