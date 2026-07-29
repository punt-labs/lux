"""luxd's built-in Beads Browser as a permanent-lease app callback session.

The built-in is a session like any other: luxd registers a permanent-lease
``app`` session in the Hub session registry with a ``beads`` callback, so it
appears in the uniform session-then-callback menu and its click routes through
the same ``CallbackInvocation`` path an agent's callback takes. A Hub-side
:class:`~punt_lux.domain.hub.callback_hold.CallbackListener` drains the routed
click and runs the beads render off the routing thread — no ``Path.cwd`` guess
in the routing, and no privileged menu path: launching the built-in is exactly
what launching an agent callback is.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.apps.beads import BeadsBrowser
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.hub_clients import HubClientRegistry

__all__ = ["BuiltinBeadsCallbacks", "MenuDirtyMarker"]

logger = logging.getLogger(__name__)

# The connection the built-ins register under. A fixed, non-hashed id no external
# client can collide with (external ids are blake2s hex digests, never this label).
_BUILTIN_CONNECTION = ConnectionId("luxd-builtins")
_BEADS_CALLBACK_ID = "beads"


@runtime_checkable
class MenuDirtyMarker(Protocol):
    """The one replicator call the built-ins make — flag the menu for a re-push."""

    def mark_menus(self) -> None:
        """Signal that the menu registry changed so the replicator re-sends it."""
        ...


@final
class BuiltinBeadsCallbacks:
    """Register luxd's built-in Beads callback and run its render on invoke."""

    _clients: HubClientRegistry
    _router: CallbackRouter
    _marker: MenuDirtyMarker
    __slots__ = ("_clients", "_marker", "_router")

    def __new__(
        cls,
        clients: HubClientRegistry,
        router: CallbackRouter,
        marker: MenuDirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._router = router
        self._marker = marker
        return self

    @classmethod
    def install_process_builtins(cls) -> None:
        """Register luxd's built-ins against the process-wide Hub singletons.

        The one call luxd's startup makes; the singleton wiring lives here beside
        the built-in it serves rather than in the lifespan.
        """
        from punt_lux.domain.hub import hub_display
        from punt_lux.domain.hub.replicator_instance import (
            hub_callback_router,
            hub_replicator,
        )

        cls(hub_display.clients, hub_callback_router, hub_replicator).install()

    def install(self) -> None:
        """Register the permanent-lease built-in session, listener, and push the menu.

        The ``app`` kind gives the session a permanent lease, so the Beads entry is
        the item that "appears once and always works" — luxd's lease never lapses.
        Registering the listener means a click routed to the built-in is drained and
        rendered at once rather than waiting for a poll.
        """
        self._clients.record(
            _BUILTIN_CONNECTION, ClientIdentity(kind="app", name="Lux")
        )
        self._clients.register_callback(
            _BUILTIN_CONNECTION,
            SessionCallback(id=_BEADS_CALLBACK_ID, label="Beads Browser"),
        )
        self._router.add_listener(_BUILTIN_CONNECTION, self)
        self._marker.mark_menus()

    def wake(self) -> None:
        """CallbackListener: drain the built-in's routed clicks and render each.

        Runs on the routing thread; the render itself is handed to a daemon thread
        so ``bd`` and the Hub install stay off it. A drained invocation for the
        beads callback renders the board; any other id is ignored (the built-in
        registers only ``beads`` today).
        """
        for invocation in self._router.take(_BUILTIN_CONNECTION):
            if invocation.callback_id == _BEADS_CALLBACK_ID:
                self._render_beads()

    @staticmethod
    def _render_beads() -> None:
        """Build the beads board off-thread; it writes the Hub and marks dirty."""

        def _run() -> None:
            try:
                BeadsBrowser().render()
            except Exception:
                logger.exception("BeadsBrowser.render failed in background thread")

        threading.Thread(target=_run, daemon=True).start()
