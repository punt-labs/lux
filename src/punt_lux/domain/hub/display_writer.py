"""DisplayWriter -- the one way anything is written to the display, pinned to a dial.

Writing to the display is the replicator's act alone: every other part of the Hub
writes the store and marks a scene dirty. That is made a matter of what exists, not
of who calls what. The write verbs live on this class and nowhere else; an instance
is made only by a :class:`WriteSeat`; the seat is made once, by the link, and given
away once (:meth:`~punt_lux.domain.hub.request_desk.RequestDesk.take_seat`), so
there is one holder and a second asker is refused. The link keeps its own use of the
seat for the one write it makes itself, the manifest that declares what the Hub
holds when a connection opens.

A writer is pinned to the dial that was current when it was made, and every write
goes out on that dial: a failure names it (:attr:`dial`), and a redial in between
fails the next write instead of letting it land on the new dial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    HubManifestMessage,
    MenuMessage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.request_exchange import RequestExchange
    from punt_lux.protocol import Element, SceneMessage

__all__ = ["DisplayWriter", "WriteSeat"]


@final
class DisplayWriter:
    """Write to the display, on the one dial this writer was made for."""

    _generation: DialGeneration
    _exchange: RequestExchange
    __slots__ = ("_exchange", "_generation")

    def __new__(cls, generation: DialGeneration, exchange: RequestExchange) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._exchange = exchange
        return self

    @property
    def dial(self) -> DialRef:
        """The dial every write through this writer uses: what a failure names."""
        return self._exchange.name(self._generation)

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        presentation: ScenePresentation | None = None,  # None: framed by its own id
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        Every scene is framed: an omitted *presentation* self-frames by *scene_id*
        (as the Hub does), so a bare ``show`` still lands in a named frame. Returns
        the :class:`AckMessage` or ``None`` on timeout. The ack is matched by
        position among the acks owed, so scenes written without a wait (the
        replicator's) are accounted for. A timeout keeps the dial; the ack still
        owed is dropped when it arrives. Raises
        :class:`~punt_lux.domain.hub.display_busy.DisplayBusyError` if another scene
        held the dial for the whole lock-wait budget.
        """
        framed = presentation or ScenePresentation(frame_id=scene_id)
        msg = framed.message(scene_id, elements)
        with self._exchange.exclusive("scene"):
            pending = self._generation.send_scene(msg, awaited=True)
            return self._exchange.answer(self._generation, pending)

    def send_scene(self, message: SceneMessage) -> None:
        """Send a built scene without waiting for an ack.

        The ack is still owed, and is matched and dropped when it arrives.
        """
        self._generation.send_scene(message, awaited=False)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._generation.send(MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, Any]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._generation.send(CallbackMenuMessage(submenus=submenus))

    def send_manifest(self, scene_ids: Sequence[str]) -> None:
        """Declare the Hub's complete live-scene set to the display (DES-068).

        Meaningful only for a ``kind="hub"`` connection, sent immediately after
        identifying and before any scene content. The display purges every scene
        it cannot attribute to this connection that the manifest does not name.
        """
        self._generation.send(HubManifestMessage(scene_ids=tuple(scene_ids)))


@final
class WriteSeat:
    """Where writers are made: the one place that can, handed out once."""

    _exchange: RequestExchange
    __slots__ = ("_exchange",)

    def __new__(cls, exchange: RequestExchange) -> Self:
        self = super().__new__(cls)
        self._exchange = exchange
        return self

    def current(self) -> DisplayWriter:
        """A writer pinned to the dial that is current now.

        Raises the error that says why there is none (see
        :meth:`~punt_lux.domain.hub.display_connection.DisplayConnection.require`).
        """
        return DisplayWriter(self._exchange.current(), self._exchange)
