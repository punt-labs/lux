"""register_callback MCP tool — a session registers its own menu callback.

The tool is the session's end of the callback model, and it answers to both of
registration's preconditions: the calling connection must hold a listen leg (a
bare MCP session has none, and is refused) and the session must have identified.
A registration that takes lands a menu entry under the session's own submenu, and
a click on that entry wakes the leg that owns it. These tests drive the real tool
functions against an isolated store so the adapter wiring — parse, scope from the
session key, facade call, status line — is exercised end to end.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Self, final
from unittest import mock

from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.menu_models import MenuAction
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Operations
from punt_lux.operations.display_connection import HubDisplayConnection
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.tools import subscribe_tools, write_tools
from punt_lux.tools.server import _session_key

_SESSION = "test-register-callback"


def _tool_identity() -> ClientIdentity:
    """The identity the rig's leg declares — the one the tests then re-declare."""
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


@final
class _StubReplicator:
    """A no-op DirtyMarker so a menu push never touches the real replicator."""

    __slots__ = ()

    def mark_dirty(self, scene_id: object) -> None:
        """Swallow a scene mark — registration must never mark a scene."""

    def mark_menus(self) -> None:
        """Swallow the menu-dirty flag."""


@final
class _Listener:
    """A persistent leg's wake, counting the pushes a routed click produced."""

    _woken: int
    __slots__ = ("_woken",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._woken = 0
        return self

    def wake(self) -> None:
        self._woken += 1

    @property
    def woken(self) -> int:
        return self._woken


@final
class _Rig:
    """The click seam of an isolated store: route a click, read what it woke."""

    _router: CallbackRouter
    _listener: _Listener
    __slots__ = ("_listener", "_router")

    def __new__(cls, router: CallbackRouter, listener: _Listener) -> Self:
        self = super().__new__(cls)
        self._router = router
        self._listener = listener
        return self

    def click(self, callback_id: str) -> None:
        """Stand in for a display click on this session's leaf."""
        self._router.route(CallbackInvocation(ConnectionId(_SESSION), callback_id))

    @property
    def woken(self) -> int:
        """How many times the session's listen leg was pushed to."""
        return self._listener.woken


@contextlib.contextmanager
def _isolated_ops(*, listening: bool = True) -> Generator[tuple[Operations, _Rig]]:
    """Bind both tool modules to one fresh Operations store for the session key.

    Yields the store and a rig over its callback router: the router is the seam a
    test uses to stand in for a display click (routing stays Hub-internal and is
    not on the facade the tools call) and to give the session the listen leg
    registration requires. ``listening=False`` withholds that leg, which is what a
    bare MCP session — no ``lux mcp-serve`` process behind it — actually has.
    """
    display = HubDisplay()
    router = CallbackRouter(display.clients)
    listener = _Listener()
    if listening:
        display.clients.attach_listener(
            ConnectionId(_SESSION), _tool_identity(), listener
        )
    ports = HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=ensure_writer,
        next_event=next_event,
        display_port=HubDisplayConnection(
            is_running=lambda: False, clients=client_registry
        ),
    )
    # ``display.clients`` is the fresh registry the identity and callback concerns
    # read and write, keeping this store isolated; the singleton passed as
    # ``client_registry`` feeds only the config concern, unused here.
    ops = Operations.for_store(
        display,
        _StubReplicator(),
        hub=hub,
        client_registry=client_registry,
        menu_registry=HubMenuRegistry(),
        callback_router=router,
        ports=ports,
    )
    token = _session_key.set(_SESSION)
    with (
        mock.patch("punt_lux.tools.tools.OPERATIONS", ops),
        mock.patch("punt_lux.tools.subscribe_tools.OPERATIONS", ops),
        mock.patch.object(DisplayPaths, "is_running", return_value=False),
    ):
        try:
            yield ops, _Rig(router, listener)
        finally:
            _session_key.reset(token)


def test_a_session_with_no_listen_leg_is_refused_the_push_requirement() -> None:
    """What a bare MCP session gets: the tool exists, but the connection cannot."""
    with _isolated_ops(listening=False):
        write_tools.identify("mcp-session", "claude", "/w/lux")
        result = subscribe_tools.register_callback("beads", "Beads")
    assert result.startswith("error: ")
    assert "listen leg" in result
    assert "mcp-serve" in result  # and the way to get one


def test_a_session_that_never_identified_meets_the_leg_it_cannot_hold() -> None:
    """An anonymous caller cannot reach the identity challenge; it has no leg to hold.

    Identity and the listen leg arrive in one registry write, and the route that
    serves ``/ws`` refuses an unnamed handshake, so nothing anonymous ever occupies
    a connection's slot. The refusal an unidentified caller meets is therefore the
    push requirement — and identifying alone would not clear it.
    """
    with _isolated_ops(listening=False):
        result = subscribe_tools.register_callback("beads", "Beads")
    assert result.startswith("error: ")
    assert "listen leg" in result


def test_an_identified_session_registers_and_the_menu_shows_its_entry() -> None:
    with _isolated_ops() as (ops, _rig):
        assert write_tools.identify("mcp-session", "claude", "/w/lux").startswith(
            "identified:"
        )
        assert subscribe_tools.register_callback("beads", "Beads") == "registered:beads"

        # The Hub-authoritative bar the display renders: the session's submenu is
        # appended after any agent menus, labeled from its identity and repo.
        menus = ops.list_menus().menus
    assert len(menus) == 1
    assert menus[0].label == "claude"
    assert len(menus[0].items) == 1
    leaf = menus[0].items[0]
    assert isinstance(leaf, MenuAction)
    assert leaf.label == "Beads"
    # The leaf carries the routable id a click sends back — registration and the
    # click path agree on the same menu id.
    assert leaf.id == CallbackInvocation(ConnectionId(_SESSION), "beads").menu_id


def test_a_click_on_the_registered_entry_pushes_to_the_session() -> None:
    with _isolated_ops() as (_ops, rig):
        write_tools.identify("mcp-session", "claude", "/w/lux")
        subscribe_tools.register_callback("beads", "Beads")

        # A display click routes the leaf's invocation to the owning session, and
        # the session's leg is woken then and there — no read to poll for it.
        rig.click("beads")
        assert rig.woken == 1
