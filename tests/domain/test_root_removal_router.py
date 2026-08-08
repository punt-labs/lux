"""RootRemovalRouter routes a scene-root's self-removal back through apply.

The scene-root observer can fire after the owner was already dropped —
during a ``drop_connection`` cascade one root's teardown re-enters the root
callback for another. With no owner left there is nothing to remove, so the
router returns quietly instead of raising on an absent element.
"""

from __future__ import annotations

from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_removal_router import RootRemovalRouter
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import RemoveElement

_SCENE = SceneId("ownership-scene")
_OWNER = ConnectionId("owner-conn")
_ELEMENT_ID = ElementId("element")


def test_route_for_an_already_dropped_element_is_a_no_op() -> None:
    """With no owner recorded, ``route`` calls ``apply`` zero times."""
    calls: list[tuple[ConnectionId, RemoveElement]] = []
    router = RootRemovalRouter(OwnerTracker(), lambda c, u: calls.append((c, u)))

    router.route(_SCENE, _ELEMENT_ID)  # nothing recorded → the element has no owner

    assert calls == []


def test_route_for_an_owned_element_applies_its_removal() -> None:
    """With an owner recorded, ``route`` applies the matching ``RemoveElement``."""
    from punt_lux.domain.hub.owner import Owner

    owners = OwnerTracker()
    owners.record(_SCENE, _ELEMENT_ID, Owner.from_session(_OWNER, None))
    calls: list[tuple[ConnectionId, RemoveElement]] = []
    router = RootRemovalRouter(owners, lambda c, u: calls.append((c, u)))

    router.route(_SCENE, _ELEMENT_ID)

    assert calls == [(_OWNER, RemoveElement(scene_id=_SCENE, element_id=_ELEMENT_ID))]
