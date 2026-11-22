"""Create a new named terminal session from a launcher."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields
from punt_lux.protocol.pty.launcher_name import LauncherName
from punt_lux.protocol.pty.session_label import SessionLabel


@dataclass(frozen=True, slots=True)
class NewRequest:
    """A request to start a new terminal under a label, distinct from attaching.

    ``label`` is what a person calls the session; empty means the daemon picks
    one. ``launcher`` names an entry in the daemon's launcher list; empty is
    the login shell. The request carries no command line, so it can start only
    what the machine's owner listed. The daemon answers it
    ``unsupported operation``.
    """

    request_id: int
    label: str = ""
    launcher: str = ""
    cols: int = 80
    rows: int = 24
    OP: ClassVar[Literal["new"]] = "new"
    KEYS: ClassVar[frozenset[str]] = frozenset(
        {"id", "op", "label", "launcher", "cols", "rows"}
    )

    def __post_init__(self) -> None:
        SessionLabel(self.label)
        LauncherName(self.launcher)
        self._check_range("id", self.request_id, 1, (1 << 32) - 1)
        self._check_range("cols", self.cols, 1, 1024)
        self._check_range("rows", self.rows, 1, 512)

    @staticmethod
    def _check_range(key: str, value: int, minimum: int, maximum: int) -> None:
        if not minimum <= value <= maximum:
            raise ControlError(f"{key} is outside {minimum}..{maximum}")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.request_id,
            "op": self.OP,
            "label": self.label,
            "launcher": self.launcher,
            "cols": self.cols,
            "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> Self:
        """Check the wire shape and field types; the constructor checks values."""
        fields = ControlFields(raw)
        fields.shape(cls.OP, cls.KEYS)
        return cls(
            fields.request_id(),
            SessionLabel.requested(fields).text,
            LauncherName.requested(fields).text,
            fields.integer("cols", 1, 1024),
            fields.integer("rows", 1, 512),
        )
