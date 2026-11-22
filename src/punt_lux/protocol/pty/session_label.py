"""The human name of a terminal session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields
from punt_lux.protocol.pty.menu_name import MenuName


@dataclass(frozen=True, slots=True)
class SessionLabel(MenuName):
    """A validated label.

    An empty label means "pick a default" in a request and is refused in an
    event, where the session already has a name.
    """

    FIELD: ClassVar[str] = "label"

    @classmethod
    def requested(cls, fields: ControlFields) -> SessionLabel:
        """Read the ``label`` field of a request; empty is allowed."""
        return cls(fields.text(cls.FIELD, cls.MAX_LENGTH))

    @classmethod
    def assigned(cls, fields: ControlFields) -> SessionLabel:
        """Read the ``label`` field of an event; empty is refused."""
        label = cls.requested(fields)
        if not label.text:
            raise ControlError("label of a live session must be nonempty")
        return label
