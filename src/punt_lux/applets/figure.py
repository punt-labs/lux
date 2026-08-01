"""Figure — one phrase of a click's line: a stage, its milliseconds, its say.

The line a click reports is a walk through the click, and this is one step of
that walk. A stage that had something to say about itself says it in parentheses
after its number, because the number alone cannot tell two clicks apart: 28 ms
answering with a board the applet already had and 28 ms answering with the word
"Loading" are the same figure and different clicks.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["Figure"]


@final
class Figure:
    """A stage's name, how long it took, and whatever it said about itself."""

    _ms: float
    _name: str
    _said: str
    __slots__ = ("_ms", "_name", "_said")

    def __new__(cls, name: str, ms: float, said: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._ms = ms
        self._said = said
        return self

    def text(self) -> str:
        """The phrase this figure contributes to the click's one line."""
        if self._said:
            return f"{self._name} {self._ms:.0f} ms ({self._said})"
        return f"{self._name} {self._ms:.0f} ms"
