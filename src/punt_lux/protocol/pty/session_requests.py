"""List and kill requests for terminal-session housekeeping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlFields


@dataclass(frozen=True, slots=True)
class ListRequest:
    """List sessions without attaching or starting a program."""

    request_id: int
    OP: ClassVar[Literal["list"]] = "list"

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


@dataclass(frozen=True, slots=True)
class KillRequest:
    """End and remove an explicitly named session."""

    request_id: int
    session: str
    OP: ClassVar[Literal["kill"]] = "kill"

    def __post_init__(self) -> None:
        self._validate(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {"id": self.request_id, "op": self.OP, "session": self.session}

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        fields = cls._validate(raw)
        return cls(fields.request_id(), fields.session())

    @classmethod
    def _validate(cls, raw: Mapping[str, object]) -> ControlFields:
        fields = ControlFields(raw)
        fields.shape(cls.OP, frozenset({"id", "op", "session"}))
        fields.request_id()
        fields.session()
        return fields
