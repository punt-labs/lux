"""Create a new named terminal session."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlFields
from punt_lux.protocol.pty.session_label import SessionLabel


@dataclass(frozen=True, slots=True)
class NewRequest:
    """Start a new shell and name it; the reply carries the daemon-assigned id.

    ``label`` is what a person calls the session. An empty label asks the
    daemon to pick a default. ``command`` is an argv-like string, not shell code.
    """

    request_id: int
    label: str = ""
    command: str = ""
    cols: int = 80
    rows: int = 24
    OP: ClassVar[Literal["new"]] = "new"
    KEYS: ClassVar[frozenset[str]] = frozenset(
        {"id", "op", "label", "command", "cols", "rows"}
    )

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.request_id,
            "op": self.OP,
            "label": self.label,
            "command": self.command,
            "cols": self.cols,
            "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = cls._validate(raw)
        return cls(
            fields.request_id(),
            SessionLabel.requested(fields).text,
            fields.text("command"),
            fields.integer("cols", 1, 1024),
            fields.integer("rows", 1, 512),
        )

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.shape(cls.OP, cls.KEYS)
        fields.request_id()
        SessionLabel.requested(fields)
        fields.text("command")
        fields.integer("cols", 1, 1024)
        fields.integer("rows", 1, 512)
        return fields
