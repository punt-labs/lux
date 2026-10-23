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

    @property
    def scope_label(self) -> str | None:
        """The Hub's name for the frame's owner, or ``None`` if it named none."""
        return self._scope_label

    def adopt(
        self,
        title: str | None,  # PY-TS-14: a push may omit what it does not change
        scope_label: str | None,  # PY-TS-14: absent = the Hub named no owner now
    ) -> None:
        """Take what a content push carries; an omitted field means "leave it".

        A title that is empty or absent leaves the last one, and a missing label
        never blanks the one held: the Hub's ``None`` for a departed owner is the
        departure guarantee, so the frame keeps the name it last had.
        """
        if title:
            self._title = title
        if scope_label is not None:
            self._scope_label = scope_label

    def relabel(self, scope_label: str | None) -> None:
        """Replace the label with the Hub's fresh word for it, absence included.

        Only an empty push that removed the frame's oldest scene calls this: it
        carries the Hub's current answer for the frame's new oldest scene, so
        ``None`` there means the Hub has no name for the owner now.
        """
        self._scope_label = scope_label
