"""HubSceneWriter removal semantics — idempotent absent, loud cross-connection.

``RemoveElement`` is idempotent: removing an id that is not installed is a no-op,
not a batch rejection, so a client can re-issue a remove without racing the
store. Ownership is still enforced loud — a remove of an installed element owned
by another connection is refused whole.

These tests drive the real ``HubSceneWriter.apply`` path, not a stub: the batch
is parsed, staged, committed, and the store is inspected through ``HubDisplay``
after the write.
"""

from __future__ import annotations

import logging

import pytest

from punt_lux.domain.hub.hub_display import HubDisplay, UnknownElementError
from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.hub.write_result import WriteAccepted, WriteRejected
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.protocol.elements.text import TextElement

_SCENE = SceneId("writer-scene")
_OWNER = ConnectionId("owner-conn")
_OTHER = ConnectionId("other-conn")
_ELEM_ID = ElementId("t1")
_SECOND_ID = ElementId("t2")


def _seed_one_text() -> HubDisplay:
    """Install a single ABC text root owned by ``_OWNER``."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    text = TextElement(id=str(_ELEM_ID), content="hello")
    hub_display.apply(_OWNER, AddElement(scene_id=_SCENE, element=text, parent_id=None))
    return hub_display


def _seed_two_texts() -> HubDisplay:
    """Install two ABC text roots (``t1``, ``t2``) owned by ``_OWNER``."""
    hub_display = _seed_one_text()
    second = TextElement(id=str(_SECOND_ID), content="world")
    hub_display.apply(
        _OWNER, AddElement(scene_id=_SCENE, element=second, parent_id=None)
    )
    return hub_display


def test_remove_present_owned_element_evicts_it() -> None:
    """The happy path: an owner removing a present, owned element evicts it.

    Nothing else proved that normal removal still reaches the store after the
    ``is_present`` / ``ElementIndex.contains`` staging refactor — an absent-skip
    that also skipped present removals would pass every idempotency test.
    """
    hub_display = _seed_one_text()
    writer = HubSceneWriter(hub_display)

    result = writer.apply(_OWNER, _SCENE, [{"id": str(_ELEM_ID), "remove": True}])

    assert isinstance(result, WriteAccepted)
    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, _ELEM_ID)


def test_absent_removal_skip_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The idempotent absent-removal skip leaves a diagnosable trace.

    A mistyped id must not vanish silently: the skip emits a DEBUG line naming
    the absent id and scene so an operator can find the typo in the Hub log.
    """
    hub_display = _seed_one_text()
    writer = HubSceneWriter(hub_display)

    with caplog.at_level(logging.DEBUG, logger="punt_lux.domain.hub.scene_writer"):
        writer.apply(_OWNER, _SCENE, [{"id": "submit-buton", "remove": True}])

    assert any(
        "submit-buton" in r.getMessage() and str(_SCENE) in r.getMessage()
        for r in caplog.records
    )


def test_remove_absent_by_non_owner_is_accepted() -> None:
    """A stranger removing a ghost id gets ``ack`` — ownership is never consulted.

    Staging orders ``is_present`` before the owner check, so an absent target
    short-circuits before ownership matters. This is the intended contract: a
    no-op on a non-existent element leaks nothing and mutates nothing, so the
    idempotent ``ack`` is correct even when the caller owns nothing in the scene.
    """
    hub_display = _seed_one_text()
    hub_display.register_client(_OTHER)
    writer = HubSceneWriter(hub_display)

    result = writer.apply(_OTHER, _SCENE, [{"id": "ghost", "remove": True}])

    assert isinstance(result, WriteAccepted)
    # The stranger's phantom remove left the owned element untouched.
    assert isinstance(hub_display.resolve(_SCENE, _ELEM_ID), TextElement)


def test_mixed_batch_absent_skip_does_not_abort_field_or_present_removal() -> None:
    """One batch: a field patch, an absent removal, and a present removal.

    The absent skip must not abort the committed field realization or the present
    removal — all three requests land in one ``apply``.
    """
    hub_display = _seed_two_texts()
    writer = HubSceneWriter(hub_display)

    result = writer.apply(
        _OWNER,
        _SCENE,
        [
            {"id": str(_ELEM_ID), "set": {"content": "patched"}},
            {"id": "ghost", "remove": True},
            {"id": str(_SECOND_ID), "remove": True},
        ],
    )

    assert isinstance(result, WriteAccepted)
    # The field patch committed.
    patched = hub_display.resolve(_SCENE, _ELEM_ID)
    assert isinstance(patched, TextElement)
    assert patched.content == "patched"
    # The present removal evicted t2.
    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, _SECOND_ID)


def test_remove_absent_element_is_idempotent_no_op() -> None:
    """A remove of an un-installed id is accepted; the store is untouched."""
    hub_display = _seed_one_text()
    writer = HubSceneWriter(hub_display)

    result = writer.apply(_OWNER, _SCENE, [{"id": "ghost", "remove": True}])

    assert isinstance(result, WriteAccepted)
    # The installed element survives, and the absent target stays absent.
    stored = hub_display.resolve(_SCENE, _ELEM_ID)
    assert isinstance(stored, TextElement)
    with pytest.raises(UnknownElementError):
        hub_display.resolve(_SCENE, ElementId("ghost"))


def test_remove_owned_by_another_connection_is_rejected() -> None:
    """A remove of an installed element owned by another connection fails loud."""
    hub_display = _seed_one_text()
    hub_display.register_client(_OTHER)
    writer = HubSceneWriter(hub_display)

    result = writer.apply(_OTHER, _SCENE, [{"id": str(_ELEM_ID), "remove": True}])

    assert isinstance(result, WriteRejected)
    # The rejection leaves the owned element in place.
    stored = hub_display.resolve(_SCENE, _ELEM_ID)
    assert isinstance(stored, TextElement)
