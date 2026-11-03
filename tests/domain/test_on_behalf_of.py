"""A Hub-internal act on behalf of an owner is not the owner's contact.

Installing a client's Details scene or removing a root the owner forgot is the Hub
acting under the owner's name. It must not renew the owner's lease: a client that
has gone quiet stays lapsed, and the next sweep departs it.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.client_host import UNOBSERVED
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.scope import Scope
from punt_lux.domain.update import AddElement, RemoveElement
from punt_lux.protocol.elements.text import TextElement

_OWNER = ConnectionId("quiet")
_SCENE = SceneId("scene")
_PAST_ANY_LEASE = 1_000_000.0


@final
class _Clock:
    """A clock the test advances by hand, so a lease lapses on cue."""

    _now: float

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._now = 0.0
        return self

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _text(element_id: str) -> TextElement:
    return TextElement(id=element_id, content="hello")


def _lapsed_owner(factory: HubStoreFactory, clock: _Clock) -> None:
    """An agent that installed a root and then went quiet past its lease."""
    factory.lifecycle.identify(
        _OWNER, ClientIdentity(kind="mcp-session", name="claude"), UNOBSERVED
    )
    factory.display.apply(
        Scope.in_process(_OWNER),
        AddElement(scene_id=_SCENE, element=_text("t"), parent_id=None),
    )
    clock.advance(_PAST_ANY_LEASE)


def test_removing_on_behalf_of_a_lapsed_owner_does_not_revive_it() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock)
    _lapsed_owner(factory, clock)

    factory.display.apply(
        Scope.on_behalf_of(_OWNER),
        RemoveElement(scene_id=_SCENE, element_id=ElementId("t")),
    )

    assert _OWNER not in factory.clients.live_sessions()


def test_installing_on_behalf_of_a_lapsed_owner_does_not_revive_it() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock)
    _lapsed_owner(factory, clock)

    factory.display.apply(
        Scope.on_behalf_of(_OWNER),
        AddElement(scene_id=SceneId("details"), element=_text("d"), parent_id=None),
    )

    assert _OWNER not in factory.clients.live_sessions()


def test_the_sweep_after_an_on_behalf_of_act_departs_the_owner() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock)
    _lapsed_owner(factory, clock)
    factory.display.apply(
        Scope.on_behalf_of(_OWNER),
        RemoveElement(scene_id=_SCENE, element_id=ElementId("t")),
    )

    factory.lifecycle.depart_lapsed(frozenset())

    assert _OWNER not in factory.clients.sessions()


def test_an_ordinary_write_still_renews_the_writer() -> None:
    clock = _Clock()
    factory = HubStoreFactory(clock)
    _lapsed_owner(factory, clock)

    factory.display.apply(
        Scope.in_process(_OWNER),
        AddElement(scene_id=_SCENE, element=_text("u"), parent_id=None),
    )

    assert _OWNER in factory.clients.live_sessions()
