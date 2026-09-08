"""OwnerTracker — the ``(scene, element) -> Owner`` map and its release step.

``require_ownership`` is what ``HubDisplay.apply`` gates ``SetProperty`` and
``RemoveElement`` on; ``release_all`` is what a reaped connection's ownership
is cleared through (see ``docs/connection_lease_reaping.tex``'s ``Reap``).
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.owner import Owner
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

_SCENE = SceneId("scene")
_OTHER_SCENE = SceneId("other-scene")
_ELEMENT = ElementId("element")
_OTHER_ELEMENT = ElementId("other-element")
_OWNER = ConnectionId("owner-conn")
_STRANGER = ConnectionId("stranger-conn")


def test_get_returns_none_for_an_unrecorded_element() -> None:
    tracker = OwnerTracker()
    assert tracker.get(_SCENE, _ELEMENT) is None


def test_record_then_get_roundtrips_the_owner() -> None:
    tracker = OwnerTracker()
    owner = Owner(_OWNER)
    tracker.record(_SCENE, _ELEMENT, owner)
    assert tracker.get(_SCENE, _ELEMENT) == owner


def test_discard_drops_the_record() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    tracker.discard(_SCENE, _ELEMENT)
    assert tracker.get(_SCENE, _ELEMENT) is None


def test_discard_is_a_noop_when_absent() -> None:
    tracker = OwnerTracker()
    tracker.discard(_SCENE, _ELEMENT)  # never recorded; must not raise
    assert tracker.get(_SCENE, _ELEMENT) is None


def test_keys_for_returns_only_this_connections_pairs() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    tracker.record(_OTHER_SCENE, _OTHER_ELEMENT, Owner(_STRANGER))
    assert tracker.keys_for(_OWNER) == ((_SCENE, _ELEMENT),)


def test_keys_for_is_empty_for_a_connection_that_owns_nothing() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    assert tracker.keys_for(_STRANGER) == ()


# -- require_ownership (CL1/CL2/CL3: the guard `apply`'s Claim path gates on) -


def test_require_ownership_passes_silently_for_the_owner() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    tracker.require_ownership(_SCENE, _ELEMENT, _OWNER)  # must not raise


def test_require_ownership_raises_for_a_different_live_owner() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    with pytest.raises(HubOwnershipError):
        tracker.require_ownership(_SCENE, _ELEMENT, _STRANGER)


def test_require_ownership_passes_silently_for_an_unrecorded_element() -> None:
    """An unowned (or never-installed) element never blocks a write here.

    This is the guard's own not-found/not-owner distinction, unchanged by
    ``release_all`` -- a scene ``release_all`` just emptied looks exactly
    like one nothing ever recorded.
    """
    tracker = OwnerTracker()
    tracker.require_ownership(_SCENE, _ELEMENT, _STRANGER)  # must not raise


# -- release_all (the reap-and-release fix's release step) ------------------


def test_release_all_drops_every_key_the_connection_owns() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    tracker.record(_OTHER_SCENE, _OTHER_ELEMENT, Owner(_OWNER))

    tracker.release_all(_OWNER)

    assert tracker.get(_SCENE, _ELEMENT) is None
    assert tracker.get(_OTHER_SCENE, _OTHER_ELEMENT) is None
    assert tracker.keys_for(_OWNER) == ()


def test_release_all_never_touches_another_connections_keys() -> None:
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))
    tracker.record(_OTHER_SCENE, _OTHER_ELEMENT, Owner(_STRANGER))

    tracker.release_all(_OWNER)

    assert tracker.get(_OTHER_SCENE, _OTHER_ELEMENT) == Owner(_STRANGER)


def test_release_all_is_a_noop_for_a_connection_that_owns_nothing() -> None:
    """KT3: releasing an ownerless connection touches no scene."""
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_STRANGER))

    tracker.release_all(_OWNER)  # owns nothing; must be a vacuous no-op

    assert tracker.get(_SCENE, _ELEMENT) == Owner(_STRANGER)


def test_release_all_unblocks_a_write_that_used_to_be_a_different_owner() -> None:
    """The observable half of I2: once released, the guard treats it as unowned."""
    tracker = OwnerTracker()
    tracker.record(_SCENE, _ELEMENT, Owner(_OWNER))

    tracker.release_all(_OWNER)

    tracker.require_ownership(_SCENE, _ELEMENT, _STRANGER)  # no longer raises
