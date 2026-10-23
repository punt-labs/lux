"""HubStoreFactory — the store and the client door, built over one lock and owner map.

The store and the door share two primitives, the ``StoreLock`` and the
``OwnerTracker``. Neither side can create what the other must share, so the
factory builds both and hands the same instance to each. These cases prove the
wiring: a registration made through the door is the one the store reads, a
departure releases what the store holds, and the lock the door exposes is the
lock the store writes under.
"""

from __future__ import annotations

import threading

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements.text import TextElement

_ALICE = ConnectionId("alice")
_BOB = ConnectionId("bob")
_SCENE = SceneId("s1")
_LEASE_SECONDS = 90.0  # a ``cli`` identity's default lease


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _cli(name: str) -> ClientIdentity:
    return ClientIdentity(kind="cli", name=name, repo="/w/lux")


def test_the_door_and_the_registry_share_one_registration() -> None:
    factory = HubStoreFactory(hub=Hub())
    lifecycle = factory.lifecycle
    clients = factory.clients

    lifecycle.arrive(_ALICE, UNOBSERVED)

    assert clients.session_of(_ALICE) is not None
    assert set(clients.live_sessions()) == {_ALICE}


def test_a_departure_empties_the_registry_and_releases_ownership() -> None:
    factory = HubStoreFactory(hub=Hub())
    display = factory.display
    lifecycle = factory.lifecycle
    clients = factory.clients
    lifecycle.arrive(_ALICE, UNOBSERVED)
    display.apply(
        Scope.in_process(_ALICE),
        AddElement(
            scene_id=_SCENE,
            element=TextElement(id="t", content="x"),
            parent_id=None,
        ),
    )

    lifecycle.depart(_ALICE)

    assert clients.session_of(_ALICE) is None
    assert display.elements_owned_by(_ALICE) == ()
    assert display.owner_of(_SCENE, ElementId("t")) is None  # the content stands


def test_a_write_by_a_registered_caller_renews_its_lease() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock=clock, hub=Hub())
    display = factory.display
    lifecycle = factory.lifecycle
    clients = factory.clients
    lifecycle.identify(_ALICE, _cli("alice"), UNOBSERVED)

    clock.now = _LEASE_SECONDS - 10.0
    display.apply(
        Scope.in_process(_ALICE),
        AddElement(
            scene_id=_SCENE,
            element=TextElement(id="t", content="x"),
            parent_id=None,
        ),
    )
    clock.now = 2 * _LEASE_SECONDS - 20.0  # past the first lease, inside the renewed

    assert _ALICE in clients.live_sessions()


def test_a_write_sweeps_other_lapsed_connections_but_never_its_own_caller() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock=clock, hub=Hub())
    display = factory.display
    lifecycle = factory.lifecycle
    clients = factory.clients
    lifecycle.identify(_ALICE, _cli("alice"), UNOBSERVED)
    lifecycle.identify(_BOB, _cli("bob"), UNOBSERVED)

    clock.now = _LEASE_SECONDS + 1.0  # both leases lapsed, nobody swept yet
    display.apply(
        Scope.in_process(_ALICE),
        AddElement(
            scene_id=_SCENE,
            element=TextElement(id="t", content="x"),
            parent_id=None,
        ),
    )

    assert clients.session_of(_ALICE) is not None  # the caller renewed first
    assert clients.session_of(_BOB) is None  # the other lapsed and was departed


def test_writing_as_renews_the_caller_and_holds_the_store_lock() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock=clock, hub=Hub())
    display = factory.display
    lifecycle = factory.lifecycle
    clients = factory.clients
    lifecycle.identify(_ALICE, _cli("alice"), UNOBSERVED)
    clock.now = _LEASE_SECONDS - 10.0

    entered = threading.Event()
    release = threading.Event()
    contender_in = threading.Event()

    def _hold() -> None:
        with display.writing_as(Scope.in_process(_ALICE)):
            entered.set()
            release.wait(timeout=5.0)

    def _contend() -> None:
        with display.write_lock():
            contender_in.set()

    holder = threading.Thread(target=_hold)
    holder.start()
    assert entered.wait(timeout=5.0)
    contender = threading.Thread(target=_contend)
    contender.start()

    assert not contender_in.wait(timeout=0.2)  # the store lock is held
    release.set()
    holder.join(timeout=5.0)
    contender.join(timeout=5.0)
    clock.now = 2 * _LEASE_SECONDS - 20.0  # past the first lease, inside the renewed

    assert contender_in.is_set()
    assert _ALICE in clients.live_sessions()


def test_the_lifecycle_and_the_store_release_ownership_under_one_lock() -> None:
    factory = HubStoreFactory(hub=Hub())
    display = factory.display
    lifecycle = factory.lifecycle
    held = threading.Event()
    release = threading.Event()
    contender_in = threading.Event()

    def _hold() -> None:
        with lifecycle.exclusive():
            held.set()
            release.wait(timeout=5.0)

    def _contend() -> None:
        with display.write_lock():
            contender_in.set()

    holder = threading.Thread(target=_hold)
    holder.start()
    assert held.wait(timeout=5.0)
    contender = threading.Thread(target=_contend)
    contender.start()

    assert not contender_in.wait(timeout=0.2)  # the door's lock IS the store's
    release.set()
    holder.join(timeout=5.0)
    contender.join(timeout=5.0)
    assert contender_in.is_set()


def test_arriving_as_registers_the_caller_and_holds_the_store_lock() -> None:
    factory = HubStoreFactory(hub=Hub())
    display = factory.display
    clients = factory.clients
    entered = threading.Event()
    release = threading.Event()
    contender_in = threading.Event()

    def _hold() -> None:
        with display.arriving_as(Scope.in_process(_ALICE)):
            entered.set()
            release.wait(timeout=5.0)

    def _contend() -> None:
        with display.write_lock():
            contender_in.set()

    holder = threading.Thread(target=_hold)
    holder.start()
    assert entered.wait(timeout=5.0)
    contender = threading.Thread(target=_contend)
    contender.start()

    assert not contender_in.wait(timeout=0.2)  # the store lock is held
    assert clients.session_of(_ALICE) is not None  # and the caller has arrived
    release.set()
    holder.join(timeout=5.0)
    contender.join(timeout=5.0)
    assert contender_in.is_set()


def test_a_write_through_apply_registers_nobody() -> None:
    factory = HubStoreFactory(hub=Hub())
    display = factory.display
    clients = factory.clients

    display.apply(
        Scope.in_process(_ALICE),
        AddElement(
            scene_id=_SCENE, element=TextElement(id="t", content="x"), parent_id=None
        ),
    )

    assert clients.session_of(_ALICE) is None  # arrival is its own act
