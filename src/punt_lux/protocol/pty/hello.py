"""Version handshake for the local terminal-session service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlFields


@dataclass(frozen=True, slots=True)
class HelloRequest:
    """Negotiate the wire version and the bundled Ghostty snapshot codec."""

    request_id: int
    version: int
    snapshot_version: str
    OP: ClassVar[Literal["hello"]] = "hello"

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.request_id,
            "op": self.OP,
            "version": self.version,
            "snapshot_version": self.snapshot_version,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = cls._validate(raw)
        return cls(
            fields.request_id(),
            fields.integer("version", 1, 65535),
            fields.text("snapshot_version", 128),
        )

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.shape(cls.OP, frozenset({"id", "op", "version", "snapshot_version"}))
        fields.request_id()
        fields.integer("version", 1, 65535)
        fields.text("snapshot_version", 128)
        return fields
