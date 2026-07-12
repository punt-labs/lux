"""HubSceneWriter removal semantics — idempotent absent, loud cross-connection.

``RemoveElement`` is idempotent: removing an id that is not installed is a no-op,
not a batch rejection, so a client can re-issue a remove without racing the
store. Ownership is still enforced loud — a remove of an installed element owned
by another connection is refused whole.
"""

from __future__ import annotations

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


def _seed_one_text() -> HubDisplay:
    """Install a single ABC text root owned by ``_OWNER``."""
    hub_display = HubDisplay()
    hub_display.register_client(_OWNER)
    text = TextElement(id=str(_ELEM_ID), content="hello")
    hub_display.apply(_OWNER, AddElement(scene_id=_SCENE, element=text, parent_id=None))
    return hub_display


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
