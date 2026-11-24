"""The rules every name shown in a terminal menu or window title must satisfy."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import ClassVar

from punt_lux.wire.stream.control_fields import ControlError


@dataclass(frozen=True, slots=True)
class MenuName:
    """A bounded, printable name; ``field`` names it in every refusal.

    Names reach menu entries and window titles, so every control character is
    refused, C1 included (U+009B is a terminal CSI), and so is any unpaired
    surrogate, which cannot be encoded as UTF-8. Empty is allowed here; a
    holder that needs a name refuses it where it reads one.
    """

    text: str
    field: str
    MAX_LENGTH: ClassVar[int] = 64

    def __post_init__(self) -> None:
        if len(self.text) > self.MAX_LENGTH:
            raise ControlError(f"{self.field} is longer than {self.MAX_LENGTH}")
        if any(unicodedata.category(char) in {"Cc", "Cs"} for char in self.text):
            raise ControlError(
                f"{self.field} must not contain control characters or surrogates"
            )
