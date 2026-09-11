"""AddressRendering -- render the shared AddressBook into an item's identity.

The one seam every leaf renderer (a frame title bar, a Windows-menu entry, a
menu item) routes through, so no aggregated surface builds ImGui identity or a
visible title from a bare label (DES-089). It composes the
:class:`~punt_lux.display.replica.address_book.AddressBook` that owns Hub
liveness and collision-numbered labels, and renders that state into the two
strings a renderer needs: the hidden ImGui id and the visible title. Kept
apart from ``AddressBook`` so identity *storage* (who is live, what each Hub is
called) and identity *rendering* (how one item reads and keys) are separate
responsibilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.id_separator import ID_SEPARATOR

if TYPE_CHECKING:
    from punt_lux.display.replica.address_book import AddressBook
    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.hub_id import HubId

__all__ = ["AddressRendering"]


@final
class AddressRendering:
    """Render one aggregated item's hidden id and visible title from the book."""

    _book: AddressBook
    __slots__ = ("_book",)

    def __new__(cls, book: AddressBook) -> Self:
        self = super().__new__(cls)
        self._book = book
        return self

    def hidden_id_for(self, hub: HubId, composed_key: str) -> str:
        """The ImGui identity: the Hub dimension prepended onto an already-
        composed Rung-2 key -- a frame id, or a ``CallbackInvocation.menu_id``.

        Prepended, never re-derived, so a key already carrying the separator is
        namespaced rather than rejected. Unique across every aggregated Hub,
        because ``hub.wire_token`` is.
        """
        return ID_SEPARATOR.join((hub.wire_token, composed_key))

    def title_for(self, hub: HubId, leaf_label: str) -> str:
        """The visible title: the leaf label, prefixed by the Hub's label only
        while more than one Hub is aggregated.

        The connection rung is not shown on this path -- its scope label does
        not reach the Display today (system.tex Sec:addressing) -- so a lone
        item reads as its plain ``leaf_label``. The Hub rung's label is taken
        from the book, so a second Hub sharing a host reads ``pembroke (2)``.
        """
        address = self._book.address_for(hub, "", "", "", leaf_label)
        return address.title(
            hub_ambiguous=self._book.hub_ambiguous(), connection_ambiguous=False
        )

    def frame_title(self, frame: Frame) -> str:
        """The frame's window title, disambiguated across Hubs when ambiguous."""
        return self.title_for(frame.hub, frame.title)

    def frame_window_id(self, frame: Frame) -> str:
        """The frame's ImGui window id, unique across every aggregated Hub."""
        return self.hidden_id_for(frame.hub, frame.frame_id)
