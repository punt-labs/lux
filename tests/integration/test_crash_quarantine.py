"""Crash-loop quarantine end to end — real store, real worker, real operations.

The runtime companion to ``docs/display_crash_loop.tex``: installs a scene
whose fault-injected render always fails, drives the real background
``HubReplicator`` (composing real ``CrashAttribution`` and ``RespawnBackoff``
instances) against a fake display connection, and proves the four properties
the design promises end to end — quarantine triggers at
``ATTRIBUTION_THRESHOLD``, the scene is excluded from replication, an owner's
patch-style write is rejected with the record, and quarantine clears on a
wholesale re-show.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Self

import pytest

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.crash_attribution import ATTRIBUTION_THRESHOLD
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.operations import OpError, RenderRequest, SceneShown, UpdateRequest
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element import Element as WireElement

pytestmark = pytest.mark.integration

_CONN = ConnectionId("crash-quarantine-caller")
_SCOPE = Scope(_CONN)


def _scoped(local_id: str) -> SceneId:
    """The store key ``local_id`` composes to for ``_CONN``."""
    return SceneId(ConnectionScopedId.compose(_CONN, local_id))


class _FaultInjectingSender:
    """A display connection whose named scenes always raise on render.

    The fault-injection element the design's write-set text names: rather than
    a real ImGui renderer, this stands in for "a scene whose render crashes the
    Display" at the one seam the Hub can observe it through — a failed send.
    """

    shows: list[str]
    _crashers: set[str]
    __slots__ = ("_crashers", "shows")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.shows = []
        self._crashers = set()
        return self

    def crash_on(self, scene_id: str) -> None:
        self._crashers.add(scene_id)

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        frame_id: str | None = None,
        **_kwargs: object,
    ) -> None:
        if scene_id in self._crashers:
            raise OSError(f"{scene_id} crashed the display")
        self.shows.append(scene_id)

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        pass

    def set_callback_menus(self, submenus: list[dict[str, object]]) -> None:
        pass

    def probe_alive(self, timeout: float) -> bool:
        """Report alive unless a crash-armed scene would fail a subsequent write."""
        del timeout
        return not self._crashers


class _Provider:
    """Hands out one sender; every ``get()`` after a ``drop()`` reconciles.

    Models the DES-068 connect-success hook (``ClientRegistry
    ._connect_and_reconcile``): a fresh connect re-marks every replication-
    eligible (non-quarantined) live scene dirty.
    """

    _sender: _FaultInjectingSender
    _replicator: HubReplicator | None
    _store: HubDisplay
    _needs_reconcile: bool
    __slots__ = ("_needs_reconcile", "_replicator", "_sender", "_store")

    def __new__(cls, sender: _FaultInjectingSender, store: HubDisplay) -> Self:
        self = super().__new__(cls)
        self._sender = sender
        self._store = store
        self._replicator = None
        self._needs_reconcile = False
        return self

    def attach(self, replicator: HubReplicator) -> None:
        self._replicator = replicator

    def get(self) -> _FaultInjectingSender:
        if self._needs_reconcile and self._replicator is not None:
            for scene_id in self._store.live_scene_ids():
                self._replicator.mark_dirty(scene_id)
            self._replicator.mark_menus()
            self._needs_reconcile = False
        return self._sender

    def drop(self) -> None:
        self._needs_reconcile = True


class _Lifecycle:
    """A no-op display lifecycle — no real process to reap or respawn."""

    __slots__ = ()

    def reap(self, timeout: float = 2.0) -> None:
        pass

    def ensure(self, timeout: float = 5.0) -> Path:
        return Path("/tmp/lux-test.sock")


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
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


def _stack() -> tuple[
    HubDisplay, HubReplicator, _FaultInjectingSender, SceneOperations
]:
    store = HubDisplay()
    sender = _FaultInjectingSender()
    provider = _Provider(sender, store)
    repl = HubReplicator(
        store.reader,
        HubMenuRegistry(),
        _NoCallbackMenus(),
        provider,
        _Lifecycle(),
        store,
    )
    provider.attach(repl)
    ops = SceneOperations(store, repl, hub_element_factory, Hub())
    return store, repl, sender, ops


def test_a_scene_that_crashes_the_display_is_quarantined_at_the_threshold() -> None:
    store, repl, sender, ops = _stack()
    request = RenderRequest.parse(
        {
            "scene_id": "poison",
            "elements": [{"kind": "text", "id": "t1", "content": "x"}],
        }
    )
    result = ops.render(request, scope=_SCOPE)
    assert isinstance(result, SceneShown)
    sender.crash_on("poison")

    repl.start()
    try:
        repl.mark_dirty(SceneId("poison"))
        assert _wait_until(lambda: store.is_quarantined(SceneId("poison")))
        record = store.quarantine_record(SceneId("poison"))
        assert record is not None
        assert record.death_count >= ATTRIBUTION_THRESHOLD
    finally:
        repl.stop()


def test_a_quarantined_scene_is_excluded_from_replication() -> None:
    store, repl, sender, ops = _stack()
    request = RenderRequest.parse(
        {
            "scene_id": "poison",
            "elements": [{"kind": "text", "id": "t1", "content": "x"}],
        }
    )
    ops.render(request, scope=_SCOPE)
    sender.crash_on("poison")

    repl.start()
    try:
        repl.mark_dirty(SceneId("poison"))
        assert _wait_until(lambda: store.is_quarantined(SceneId("poison")))
        # live_scene_ids() is the replication-facing read; it must exclude a
        # quarantined scene at the source, not merely at the send filter.
        assert SceneId("poison") not in store.live_scene_ids()
        assert "poison" not in sender.shows  # never a single successful send
    finally:
        repl.stop()


def test_an_owner_write_to_a_quarantined_scene_is_rejected_with_the_record() -> None:
    store, _repl, _sender, ops = _stack()
    store.replace_scene(_CONN, _scoped("poison"), [TextElement(id="t1", content="x")])
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


def test_quarantine_clears_on_a_wholesale_re_show() -> None:
    store, _repl, _sender, ops = _stack()
    store.replace_scene(_CONN, _scoped("poison"), [TextElement(id="t1", content="x")])
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
