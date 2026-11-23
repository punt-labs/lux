"""Validated session placement shared by terminal construction and scene validation."""

from __future__ import annotations

from abc import abstractmethod

from punt_lux.wire.model.element_abc import Element
from punt_lux.wire.model.validation import ValidationError
from punt_lux.wire.stream.control_fields import ControlError, ControlFields


class TerminalPlacement(Element):
    @property
    @abstractmethod
    def session(self) -> str: ...

    @property
    @abstractmethod
    def command(self) -> str: ...

    @staticmethod
    def checked(session: str, command: str) -> tuple[str, str]:
        fields = ControlFields({"session": session, "command": command})
        fields.session()
        fields.text("command")
        return session, command

    def validate(self) -> tuple[ValidationError, ...]:
        try:
            self.checked(self.session, self.command)
        except ControlError as error:
            return (ValidationError(self.id, "terminal", str(error)),)
        return ()
