"""Session events, and the request that subscribes a connection to them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields
from punt_lux.protocol.pty.control_json import ControlJson
from punt_lux.protocol.pty.session_label import SessionLabel


@dataclass(frozen=True, slots=True)
class SessionEvent:
    """A content-free notice: which session, and what happened to it.

    The daemon sends these to a connection that issued ``WatchRequest``.
    The list of sessions is the authority; events only reduce latency, so a
    watcher that misses one reconciles against ``ListRequest``.
    """

    kind: Literal["created", "ended"]
    session: str
    label: str
    KEYS: ClassVar[frozenset[str]] = frozenset({"event", "session", "label"})

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {"event": self.kind, "session": self.session, "label": self.label}

    def encode(self) -> bytes:
        return ControlJson.dump(self.to_dict())

    @classmethod
    def decode(cls, data: bytes) -> Self:
        """Decode one event frame; a request payload is refused (no ``event``)."""
        return cls.from_dict(ControlJson.parse(data))

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = cls._validate(raw)
        session, label = fields.session(), SessionLabel.assigned(fields).text
        if raw["event"] == "created":
            return cls("created", session, label)
        return cls("ended", session, label)

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.exact("event", cls.KEYS)
        if raw["event"] not in ("created", "ended"):
            raise ControlError("event must be 'created' or 'ended'")
        fields.session()
        SessionLabel.assigned(fields)
        return fields


@dataclass(frozen=True, slots=True)
class WatchRequest:
    """Turn this connection into a subscriber of session created/ended events."""

    request_id: int
    OP: ClassVar[Literal["watch"]] = "watch"

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {"id": self.request_id, "op": self.OP}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        return cls(cls._validate(raw).request_id())

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.shape(cls.OP, frozenset({"id", "op"}))
        fields.request_id()
        return fields
