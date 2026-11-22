"""The name of a launcher: the only thing a request to start a terminal carries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from punt_lux.protocol.pty.control_fields import ControlFields
from punt_lux.protocol.pty.menu_name import MenuName


@dataclass(frozen=True, slots=True)
class LauncherName(MenuName):
    """A validated launcher name.

    The daemon resolves the name against its own launcher list, so a request
    can start only a program the machine's owner listed. Empty names the
    built-in launcher, the user's login shell.
    """

    FIELD: ClassVar[str] = "launcher"

    @classmethod
    def requested(cls, fields: ControlFields) -> LauncherName:
        """Read the ``launcher`` field of a request; empty is the login shell."""
        return cls(fields.text(cls.FIELD, cls.MAX_LENGTH))
