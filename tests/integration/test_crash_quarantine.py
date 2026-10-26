"""Crash-loop quarantine end to end — real store, real worker, real operations.

The runtime companion to ``docs/display_crash_loop.tex``: installs a scene
the display dies painting, drives the real background
``HubReplicator`` (composing real ``CrashAttribution`` and ``RespawnBackoff``
instances) over the real registry, link and dials against a display that acks at a swap,
and proves the four properties the design promises end to end — quarantine triggers at
``ATTRIBUTION_THRESHOLD``, the scene is excluded from replication, an owner's
patch-style write is rejected with the record, and quarantine clears on a
wholesale re-show.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.clients import ClientRegistry
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.crash_attribution import ATTRIBUTION_THRESHOLD
from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.frame_owner_facts import NoFrameOwnerFacts
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.liveness import DisplayLiveness
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.operations import OpError, RenderRequest, SceneShown, UpdateRequest
from punt_lux.operations.scene_deps import SceneOperationsDeps
from punt_lux.operations.scenes import SceneOperations
from punt_lux.protocol.elements.text import TextElement
from tests.domain.display_double import Display, Responder

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


pytestmark = pytest.mark.integration

_CONN = ConnectionId("crash-quarantine-caller")
_SCOPE = Scope.in_process(_CONN)


def _scoped(local_id: str) -> SceneId:
    """The store key ``local_id`` composes to for ``_CONN``."""
    return SceneId(ConnectionScopedId.compose(_CONN, local_id))


class _Lifecycle:
    """A no-op display lifecycle — no real process to reap or respawn."""

    __slots__ = ()

    def reap(self, timeout: float = 2.0) -> None:
        pass

    def ensure(self, timeout: float = 5.0) -> Path:
        return Path("/tmp/lux-test.sock")


def _wait_until(predicate: Callable[[], bool], timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        threading.Event().wait(0.01)
        result = predicate()
    return result


class _NoCallbackMenus:
    """A CallbackMenuReader with no registered session callbacks."""

    __slots__ = ()

    def callback_menu_wire(self) -> list[dict[str, object]]:
        return []


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


@pytest.fixture
def poisoned(display: Display) -> Iterator[Responder]:
    """The real display's ack discipline, and a scene it dies painting: "poison".

    Every scene is held and acked at a swap, as the display does, and a swap with the
    poison scene held never completes: the display hangs up with no ack sent.
    """
    responder = Responder(display, frozenset({_scoped("poison")}), at_swap=True)
    yield responder
    responder.stop()


def _stack(
    display: Display, monkeypatch: pytest.MonkeyPatch
) -> tuple[HubDisplay, HubReplicator, SceneOperations, DisplayLiveness]:
    """The real replicator and keepalive over the real registry, link and dials.

    The scene's death is found and charged by the production code: the display dies
    painting the scene, the dial's reader settles it with its ledger, the keepalive
    redials (which re-marks every live scene), and the replicator's next push charges
    the death before it sends.
    """
    factory = HubStoreFactory()
    store = factory.display
    monkeypatch.setattr("punt_lux.domain.hub.clients.hub_display", store)
    registry = ClientRegistry()
    registry._client = DisplayLink(display, recv_timeout=3.0)  # test seam
    repl = HubReplicator(
        store.reader,
        HubMenuRegistry(factory.clients),
        _NoCallbackMenus(),
        registry,
        _Lifecycle(),
        store,
        NoFrameOwnerFacts(),
    )
    registry.attach_replicator(repl)
    deps = SceneOperationsDeps(store, repl, hub_element_factory, Hub())
    liveness = DisplayLiveness(registry, interval=0.05, ping_timeout=1.0)
    return store, repl, SceneOperations(deps), liveness


def test_a_scene_that_crashes_the_display_is_quarantined_at_the_threshold(
    display: Display, poisoned: Responder, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repl, ops, liveness = _stack(display, monkeypatch)
    request = RenderRequest.parse(
        {
            "scene_id": "poison",
            "elements": [{"kind": "text", "id": "t1", "content": "x"}],
        }
    )
    result = ops.render(request, scope=_SCOPE)
    assert isinstance(result, SceneShown)

    repl.start()
    liveness.start()
    try:
        repl.mark_dirty(_scoped("poison"))
        assert _wait_until(lambda: store.is_quarantined(_scoped("poison")))
        record = store.quarantine_record(_scoped("poison"))
        assert record is not None
        assert record.death_count >= ATTRIBUTION_THRESHOLD
    finally:
        liveness.stop()
        repl.stop()


def test_a_quarantined_scene_is_excluded_from_replication(
    display: Display, poisoned: Responder, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repl, ops, liveness = _stack(display, monkeypatch)
    request = RenderRequest.parse(
        {
            "scene_id": "poison",
            "elements": [{"kind": "text", "id": "t1", "content": "x"}],
        }
    )
    ops.render(request, scope=_SCOPE)

    repl.start()
    liveness.start()
    try:
        repl.mark_dirty(_scoped("poison"))
        assert _wait_until(lambda: store.is_quarantined(_scoped("poison")))
        # live_scene_ids() is the replication-facing read; it must exclude a
        # quarantined scene at the source, not merely at the send filter.
        assert _scoped("poison") not in store.live_scene_ids()
        sent = len(poisoned.seen)
        repl.mark_dirty(_scoped("poison"))  # re-marked directly: still never sent
        threading.Event().wait(0.5)
        assert len(poisoned.seen) == sent
    finally:
        liveness.stop()
        repl.stop()


def test_an_owner_write_to_a_quarantined_scene_is_rejected_with_the_record(
    display: Display, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _repl, ops, _liveness = _stack(display, monkeypatch)
    store.replace_scene(
        Scope.in_process(_CONN), _scoped("poison"), [TextElement(id="t1", content="x")]
    )
    store.quarantine(
        _scoped("poison"), QuarantineRecord(death_count=2, last_death_at=1.0)
    )

    request = UpdateRequest.parse([{"id": "t1", "set": {"content": "y"}}])
    result = ops.update("poison", request, scope=_SCOPE)

    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert "quarantined" in result.reason
    # The store is untouched — a patch is not the recovery path.
    element = store.resolve(_scoped("poison"), ElementId("t1"))
    assert element.to_dict()["content"] == "x"


def test_quarantine_clears_on_a_wholesale_re_show(
    display: Display, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _repl, ops, _liveness = _stack(display, monkeypatch)
    store.replace_scene(
        Scope.in_process(_CONN), _scoped("poison"), [TextElement(id="t1", content="x")]
    )
    store.quarantine(
        _scoped("poison"), QuarantineRecord(death_count=2, last_death_at=1.0)
    )
    assert store.is_quarantined(_scoped("poison"))

    request = RenderRequest.parse(
        {
            "scene_id": "poison",
            "elements": [{"kind": "text", "id": "t2", "content": "fixed"}],
        }
    )
    result = ops.render(request, scope=_SCOPE)

    assert isinstance(result, SceneShown)
    assert not store.is_quarantined(_scoped("poison"))
