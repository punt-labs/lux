"""A click's handler runs under the store's write lock, as an agent's write does.

A handler's write is judged by the seam, and the judge walks the store's element
index. An agent's ``show`` mutates that index under the store write lock, so a
handler that ran outside it could be walked over mid-iteration. Firing under the
same lock makes the two exclude each other.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.hub_interaction_dispatch import HubInteractionDispatch
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.scope import Scope
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements import ButtonElement, TreeElement
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    import pytest

_OWNER = ConnectionId("agent-1")
_SCENE = SceneId("scene")


def _click() -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(
        scene_id=str(_SCENE),
        element_id="b",
        action="confirm",
        event_kind="button_clicked",
        ts=1.0,
        value=True,
    )


def test_an_agents_show_waits_for_the_handler_that_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = HubStoreFactory()
    store = factory.display
    factory.lifecycle.arrive(_OWNER, UNOBSERVED)
    scope = Scope.in_process(_OWNER)
    shown = threading.Thread(
        target=lambda: store.replace_scene(
            scope, SceneId("other"), [TreeElement(id="t")]
        )
    )
    still_waiting: list[bool] = []

    def handler(_event: ButtonClicked) -> None:
        shown.start()
        shown.join(0.3)
        still_waiting.append(shown.is_alive())

    button = ButtonElement(id="b", label="x")
    button.add_handler(ButtonClicked, handler)
    store.apply(scope, AddElement(scene_id=_SCENE, element=button, parent_id=None))
    import punt_lux.domain.hub as hub_module

    monkeypatch.setattr(hub_module, "hub_display", store)
    monkeypatch.setattr(
        "punt_lux.domain.hub.replicator_instance.hub_replicator", MagicMock()
    )

    HubInteractionDispatch.dispatch(_click())
    shown.join(5)

    assert (still_waiting, shown.is_alive()) == ([True], False)
