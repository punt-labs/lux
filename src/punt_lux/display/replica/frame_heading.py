"""FrameHeading -- what a frame's window is called, and whose it is."""

from __future__ import annotations

from typing import Self, final

__all__ = ["FrameHeading"]


@final
class FrameHeading:
    """A frame's base title and the Hub's name for its owner (``lux``, ``lux (2)``).

    The title is what the client called the window; the scope label is what the
    Hub calls the session that owns it. Both are content, so both move with a
    content push and neither moves where the window sits (DES-088); the title
    surfaces compose them into one string through the addressing seam.
    """

    _title: str
    # None = the Hub named no owner for this frame; the title then stays plain.
    _scope_label: str | None
    __slots__ = ("_scope_label", "_title")

    def __new__(cls, title: str, scope_label: str | None = None) -> Self:
        self = super().__new__(cls)
        self._title = title
        self._scope_label = scope_label
        return self

    @property
    def title(self) -> str:
        """The title the client gave the window."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    @property
    def scope_label(self) -> str | None:
        """The Hub's name for the frame's owner, or ``None`` if it named none."""
        return self._scope_label

    @scope_label.setter
    def scope_label(self, value: str | None) -> None:
        self._scope_label = value
