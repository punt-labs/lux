"""The name of a launcher: the only thing a request to start a terminal carries."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import ClassVar

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields


@dataclass(frozen=True, slots=True)
class LauncherName:
    """A validated launcher name.

    The daemon resolves the name against its own launcher list, so a request
    can start only a program the machine's owner listed. The name is also the
    New menu entry, so control characters are refused as in a label. Empty
    names the built-in launcher, the user's login shell.
    """

    text: str
    MAX_LENGTH: ClassVar[int] = 64

    def __post_init__(self) -> None:
        if len(self.text) > self.MAX_LENGTH:
            raise ControlError(f"launcher is longer than {self.MAX_LENGTH}")
        if any(unicodedata.category(char) == "Cc" for char in self.text):
            raise ControlError("launcher must not contain control characters")

    @classmethod
    def requested(cls, fields: ControlFields) -> LauncherName:
        """Read the ``launcher`` field of a request; empty is the login shell."""
        return cls(fields.text("launcher", cls.MAX_LENGTH))
