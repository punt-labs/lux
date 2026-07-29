"""register_callback MCP tool — a session registers its own menu callback.

The tool is the session's end of the callback model: an identified session's
call lands a menu entry under its own submenu, guarded by the same identity
challenge as a scene write, and a click on that entry is held for the session
to drain through ``pending_callbacks``. These tests drive the real tool
functions against an isolated store so the adapter wiring — parse, scope from
the session key, facade call, status line — is exercised end to end.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import final
from unittest import mock

from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.callback_hold import CallbackRouter
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


@final
class _StubReplicator:
    """A no-op DirtyMarker so a menu push never touches the real replicator."""

    __slots__ = ()

    def mark_dirty(self, scene_id: object) -> None:
        """Swallow a scene mark — registration must never mark a scene."""

    def mark_menus(self) -> None:
        """Swallow the menu-dirty flag."""


@contextlib.contextmanager
def _isolated_ops() -> Generator[tuple[Operations, CallbackRouter]]:
    """Bind both tool modules to one fresh Operations store for the session key.

    Yields the store and its callback router; the router is the seam a test uses
    to stand in for a display click, since routing a click stays Hub-internal and
    is not exposed on the facade the tools call.
    """
    display = HubDisplay()
    router = CallbackRouter(display.clients)
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
            yield ops, router
        finally:
            _session_key.reset(token)


def test_an_unidentified_session_is_refused_the_identify_challenge() -> None:
    with _isolated_ops():
        result = subscribe_tools.register_callback("beads", "Beads")
    assert result.startswith("error: ")
    assert "identity" in result


def test_an_identified_session_registers_and_the_menu_shows_its_entry() -> None:
    with _isolated_ops() as (ops, _router):
        assert write_tools.identify("mcp-session", "claude", "/w/lux").startswith(
            "identified:"
        )
        assert subscribe_tools.register_callback("beads", "Beads") == "registered:beads"

        # The Hub-authoritative bar the display renders: the session's submenu is
        # appended after any agent menus, labeled from its identity and repo.
        menus = ops.list_menus().menus
    assert len(menus) == 1
    assert menus[0].label == "claude — /w/lux"
    assert len(menus[0].items) == 1
    leaf = menus[0].items[0]
    assert isinstance(leaf, MenuAction)
    assert leaf.label == "Beads"
    # The leaf carries the routable id a click sends back — registration and the
    # click path agree on the same menu id.
    assert leaf.id == CallbackInvocation(ConnectionId(_SESSION), "beads").menu_id


def test_a_click_on_the_registered_entry_drains_through_pending_callbacks() -> None:
    with _isolated_ops() as (_ops, router):
        write_tools.identify("mcp-session", "claude", "/w/lux")
        subscribe_tools.register_callback("beads", "Beads")

        # A display click routes the leaf's invocation to the owning session; the
        # MCP pickup leg drains it once, so a second poll is empty.
        router.route(CallbackInvocation(ConnectionId(_SESSION), "beads"))

        assert subscribe_tools.pending_callbacks().callback_ids == ("beads",)
        assert subscribe_tools.pending_callbacks().callback_ids == ()
