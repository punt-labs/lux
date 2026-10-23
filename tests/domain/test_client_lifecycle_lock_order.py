"""The lock order: the store lock first, then the registry's; readers only the latter.

``ClientLifecycle`` steps hold the store write lock and then reach into the
registry, which takes its own. The registry never calls back out while holding
its lock, so nothing ever waits on the store lock from inside the registry. Two
properties follow, and each is a way the reverse order would deadlock:

- every registry write completes while another thread holds the store lock;
- every lifecycle step completes while a reader holds the registry lock.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.menu_presence import MarkMenusSink
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Callable

_CONN = ConnectionId("c1")
_OTHER = ConnectionId("c2")
_JOIN_SECONDS = 5.0
_HELD_SECONDS = 0.3


@final
class _Leg:
    def wake(self) -> None:
        """Occupies the slot only."""


@final
class _Marker:
    def mark_dirty(self, scene_id: object) -> None:
        """Scenes are not what this test observes."""

    def mark_menus(self) -> None:
        """Menus are not what this test observes."""


def _applet() -> ClientIdentity:
    return ClientIdentity(kind="applet", name="lux · lux · #1 · beads", repo="/w/lux")


def _agent() -> ClientIdentity:
    return ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")


def _wired() -> HubStoreFactory:
    factory = HubStoreFactory(hub=Hub())
    marker = _Marker()
    factory.lifecycle.present_as(marker, MarkMenusSink(marker))
    return factory


def _completes(step: Callable[[], object]) -> bool:
    """Run ``step`` on a worker thread; whether it finished within the bound."""
    worker = threading.Thread(target=step, daemon=True)
    worker.start()
    worker.join(timeout=_JOIN_SECONDS)
    return not worker.is_alive()


class TestRegistryWritesNeverWaitOnTheStoreLock:
    def test_every_registry_write_completes_while_the_store_lock_is_held(self) -> None:
        factory = _wired()
        writes = HubClientRegistry().take_writes()
        leg = _Leg()
        callback = SessionCallback(id="run", label="Run")
        steps: dict[str, Callable[[], object]] = {
            "record": lambda: writes.record(_CONN, _applet(), UNOBSERVED),
            "renew_if_registered": lambda: writes.renew_if_registered(
                _CONN, UNOBSERVED
            ),
            "attach": lambda: writes.attach(_CONN, _applet(), leg, UNOBSERVED),
            "register_callback": lambda: writes.register_callback(_CONN, callback),
            "detach": lambda: writes.detach(_CONN, leg),
            "reap_lapsed": lambda: writes.reap_lapsed(frozenset()),
            "discard": lambda: writes.discard(_CONN),
        }

        stalled = []
        with factory.lifecycle.exclusive():
            for name, write in steps.items():
                if not _completes(write):
                    stalled.append(name)

        assert stalled == []


class TestLifecycleStepsNeverWaitOnAReader:
    def _held_registry(self, factory: HubStoreFactory) -> threading.Event:
        """Hold the registry's lock as a reader would, until the event is set."""
        release = threading.Event()
        acquired = threading.Event()

        def hold() -> None:
            with factory.clients._lock:  # a reader inside a registry read
                acquired.set()
                release.wait(timeout=_JOIN_SECONDS)

        threading.Thread(target=hold, daemon=True).start()
        assert acquired.wait(timeout=_JOIN_SECONDS)
        return release

    @staticmethod
    def _run(step: Callable[[], object], done: threading.Event) -> None:
        step()
        done.set()

    def _steps(self, factory: HubStoreFactory) -> dict[str, Callable[[], object]]:
        lifecycle = factory.lifecycle
        leg = _Leg()
        callback = SessionCallback(id="run", label="Run")
        return {
            "identify": lambda: lifecycle.identify(_OTHER, _agent(), UNOBSERVED),
            "register_callback": lambda: lifecycle.register_callback(
                _CONN, callback, UNOBSERVED
            ),
            "detach": lambda: lifecycle.detach(_CONN, leg),
            "depart_lapsed": lambda: lifecycle.depart_lapsed(frozenset()),
        }

    def test_every_step_completes_once_the_reader_lets_go(self) -> None:
        factory = _wired()
        factory.lifecycle.attach(_CONN, _applet(), _Leg(), UNOBSERVED)
        release = self._held_registry(factory)
        finished = {}
        workers = {}
        for name, step in self._steps(factory).items():
            done = threading.Event()
            finished[name] = done

            def run(
                step: Callable[[], object] = step, done: threading.Event = done
            ) -> None:
                step()
                done.set()

            workers[name] = threading.Thread(target=run, daemon=True)
            workers[name].start()

        threading.Event().wait(_HELD_SECONDS)
        release.set()  # the reader leaves; no step may be left behind

        for name, worker in workers.items():
            worker.join(timeout=_JOIN_SECONDS)
            assert finished[name].is_set(), f"{name} deadlocked behind a reader"
