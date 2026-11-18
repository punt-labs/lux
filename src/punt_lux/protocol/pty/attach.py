"""Attach to a named terminal, creating it only on first use."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlFields


@dataclass(frozen=True, slots=True)
class AttachRequest:
    """Initial size is in cells; command is an argv-like string, not shell code."""

    request_id: int
    session: str
    command: str = ""
    cols: int = 80
    rows: int = 24
    OP: ClassVar[Literal["attach"]] = "attach"

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.request_id,
            "op": self.OP,
            "session": self.session,
            "command": self.command,
            "cols": self.cols,
            "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = cls._validate(raw)
        return cls(
            fields.request_id(),
            fields.session(),
            fields.text("command"),
            fields.integer("cols", 1, 1024),
            fields.integer("rows", 1, 512),
        )

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.shape(
            cls.OP, frozenset({"id", "op", "session", "command", "cols", "rows"})
        )
        fields.request_id()
        fields.session()
        fields.text("command")
        fields.integer("cols", 1, 1024)
        fields.integer("rows", 1, 512)
        return fields
