"""AddressRendering -- the Display's identity facade for aggregated items.

The one seam every leaf renderer (a frame title bar, a Windows-menu entry, a
menu item) routes through, so no aggregated surface builds ImGui identity or a
visible title from a bare label (DES-089). It composes an
:class:`~punt_lux.display.replica.address_book.AddressBook` -- the store that
tracks which Hubs are live and what each is called -- and renders that state
into the two strings a renderer needs: the hidden ImGui id and the visible
title. Connect/disconnect feed it through :meth:`note_connection` /
:meth:`forget_connection`; renderers read it through the rest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.address_book import AddressBook
from punt_lux.display.replica.lux_address import Rung
from punt_lux.domain.id_separator import ID_SEPARATOR

if TYPE_CHECKING:
    from punt_lux.display.replica.frame import Frame
    from punt_lux.domain.hub_id import HubId

__all__ = ["AddressRendering"]


@final
class AddressRendering:
    """Own the identity store and render one item's hidden id and visible title."""

    _book: AddressBook
    __slots__ = ("_book",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._book = AddressBook()
        return self

    def note_connection(self, hub: HubId, connection_key: str) -> None:
        """Record one live Hub connection so its liveness and label are current."""
        self._book.note_connection(hub, connection_key)

    def forget_connection(self, hub: HubId, connection_key: str) -> None:
        """Drop one connection, retiring its Hub's label once none remain."""
        self._book.forget_connection(hub, connection_key)

    def hidden_id_for(self, hub: HubId, composed_key: str) -> str:
        """The ImGui identity: the Hub dimension prepended onto an already-
        composed Rung-2 key -- a frame id, or a ``CallbackInvocation.menu_id``.

        Prepended, never re-derived, so a key already carrying the separator is
        namespaced rather than rejected. Unique across every aggregated Hub,
        because ``hub.wire_token`` is.
        """
        return ID_SEPARATOR.join((hub.wire_token, composed_key))

    def frame_title(self, frame: Frame) -> str:
        """The frame's window title: its owner's scope label when the Hub named
        one, behind the Hub's label only while more than one Hub is aggregated.

        The label is a fact the frame carries, so nothing counts frames or
        sessions: a lone ``Vox`` of a named session reads ``lux :: Vox`` and an
        unnamed owner's frame reads as its plain title (DES-100). The Hub rung's
        label is taken from the book, so a second Hub sharing a host reads
        ``pembroke (2)``.
        """
        label = frame.heading.scope_label
        address = self._book.address_for(
            frame.hub, Rung("", label or ""), Rung("", frame.heading.title)
        )
        return address.title(
            hub_ambiguous=self._book.hub_ambiguous(),
            connection_shown=label is not None,
        )

    def frame_window_label(self, frame: Frame) -> str:
        """The label ImGui opens the frame's window with: title, then its id.

        ImGui keys a window on what follows ``##``, so the visible title may move
        (a label arrives, a second Hub appears) without the window losing its
        position, scroll or collapse state.
        """
        return f"{self.frame_title(frame)}##{self.frame_window_id(frame)}"

    def frame_window_id(self, frame: Frame) -> str:
        """The frame's ImGui window id, unique across every aggregated Hub."""
        return self.hidden_id_for(frame.hub, frame.frame_id)
