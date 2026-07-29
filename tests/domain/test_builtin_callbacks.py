"""BuiltinBeadsCallbacks — luxd's built-in Beads as a permanent-lease session.

install() registers a permanent-lease app session with a 'beads' callback and a
listener, then pushes the menu; a routed click for the beads callback drains and
renders. The built-in is a session like any other — it shows in the uniform
session-then-callback menu and launches through the invoke path.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.builtin_callbacks import BuiltinBeadsCallbacks
from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest

_BUILTIN = ConnectionId("luxd-builtins")


@final
class _MarkerSpy:
    _count: int
    __slots__ = ("_count",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._count = 0
        return self

    def mark_menus(self) -> None:
        self._count += 1

    @property
    def count(self) -> int:
        return self._count


def test_install_registers_a_beads_callback_that_shows_in_the_menu() -> None:
    clients = HubClientRegistry()
    router = CallbackRouter(clients)
    marker = _MarkerSpy()

    BuiltinBeadsCallbacks(clients, router, marker).install()

    assert marker.count == 1
    wire = CallbackMenuReplica(clients).callback_menu_wire()
    assert wire == [
        {
            "label": "Lux",
            "items": [
                {
                    "label": "Beads Browser",
                    "id": CallbackInvocation(_BUILTIN, "beads").menu_id,
                }
            ],
        }
    ]


def test_the_built_in_session_has_a_permanent_lease() -> None:
    # An app-kind lease never lapses, so the built-in survives any live-read sweep.
    clients = HubClientRegistry()
    BuiltinBeadsCallbacks(clients, CallbackRouter(clients), _MarkerSpy()).install()
    session = clients.session_of(_BUILTIN)
    assert session is not None
    assert session.is_live(now=10_000_000.0)


def test_a_routed_beads_click_renders_off_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = HubClientRegistry()
    router = CallbackRouter(clients)
    built_in = BuiltinBeadsCallbacks(clients, router, _MarkerSpy())
    built_in.install()

    rendered: list[bool] = []

    class _FakeBrowser:
        def render(self) -> None:
            rendered.append(True)

    monkeypatch.setattr(
        "punt_lux.domain.hub.builtin_callbacks.BeadsBrowser", lambda: _FakeBrowser()
    )
    # route() adds to the hold and wakes the registered listener (built_in itself),
    # whose wake drains the hold and spawns the render thread.
    router.route(CallbackInvocation(_BUILTIN, "beads"))
    # The render runs in a daemon thread; give it a moment to record.
    for _ in range(200):
        if rendered:
            break
        time.sleep(0.005)
    assert rendered == [True]
