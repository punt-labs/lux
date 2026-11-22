"""The human name of a terminal session, and the rules it must satisfy."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import ClassVar

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields


@dataclass(frozen=True, slots=True)
class SessionLabel:
    """A validated label.

    Labels reach menu entries and window titles, so every control character
    is refused, C1 included: U+009B is a terminal CSI. An empty label means
    "pick a default" in a request and is refused in an event, where the
    session already has a name.
    """

    text: str
    MAX_LENGTH: ClassVar[int] = 64

    def __post_init__(self) -> None:
        if len(self.text) > self.MAX_LENGTH:
            raise ControlError(f"label is longer than {self.MAX_LENGTH}")
        if any(unicodedata.category(char) == "Cc" for char in self.text):
            raise ControlError("label must not contain control characters")

    @classmethod
    def requested(cls, fields: ControlFields) -> SessionLabel:
        """Read the ``label`` field of a request; empty is allowed."""
        return cls(fields.text("label", cls.MAX_LENGTH))

    @classmethod
    def assigned(cls, fields: ControlFields) -> SessionLabel:
        """Read the ``label`` field of an event; empty is refused."""
        label = cls.requested(fields)
        if not label.text:
            raise ControlError("label of a live session must be nonempty")
        return label
