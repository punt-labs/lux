"""What each interaction event publishes — one pinned payload per event kind.

A ``publish``-decorated handler sends whatever the event renders, so these
tests are the contract a subscriber reads. Every kind opens with the same
three keys — what happened, and the scene and element it happened on — and
then carries its own data.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, cast

import pytest

from punt_lux.domain.container_interaction import HeaderToggled, ModalClosed, TabChanged
from punt_lux.domain.event_kinds import EventKind
from punt_lux.domain.event_payload import EventPayload
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.interaction import ButtonClicked, ValueChanged
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.domain.wire_event import WireEvent

_SCENE = SceneId("scene-1")
_ELEMENT = ElementId("elem-1")
_OWNER = ClientId("client-1")

# Every event a remote dispatch can produce, beside the payload it publishes.
# A seventh EventKind with no entry fails test_every_event_kind_is_covered.
_EVENTS_AND_PAYLOADS: list[tuple[WireEvent, dict[str, object]]] = [
    (
        ButtonClicked(scene_id=_SCENE, element_id=_ELEMENT, owner_id=_OWNER),
        {"kind": "button_clicked", "scene_id": "scene-1", "element_id": "elem-1"},
    ),
    (
        ValueChanged(scene_id=_SCENE, element_id=_ELEMENT, owner_id=_OWNER, value=42.5),
        {
            "kind": "value_changed",
            "scene_id": "scene-1",
            "element_id": "elem-1",
            "value": 42.5,
        },
    ),
    (
        TabChanged(
            scene_id=_SCENE, element_id=_ELEMENT, owner_id=_OWNER, tab_id="details"
        ),
        {
            "kind": "tab_changed",
            "scene_id": "scene-1",
            "element_id": "elem-1",
            "tab_id": "details",
        },
    ),
    (
        HeaderToggled(
            scene_id=_SCENE, element_id=_ELEMENT, owner_id=_OWNER, open_=True
        ),
        {
            "kind": "header_toggled",
            "scene_id": "scene-1",
            "element_id": "elem-1",
            "open": True,
        },
    ),
    (
        ModalClosed(scene_id=_SCENE, element_id=_ELEMENT, owner_id=_OWNER),
        {"kind": "modal_closed", "scene_id": "scene-1", "element_id": "elem-1"},
    ),
    (
        RowSelectionChanged(
            scene_id=_SCENE,
            element_id=_ELEMENT,
            owner_id=_OWNER,
            row_ids=("album-3", "album-7"),
            anchor="album-7",
        ),
        {
            "kind": "row_selection_changed",
            "scene_id": "scene-1",
            "element_id": "elem-1",
            "row_ids": ["album-3", "album-7"],
            "anchor": "album-7",
        },
    ),
]


class _Kinded(Protocol):
    """Read-only view of a concrete event's wire ``kind`` tag."""

    kind: ClassVar[str]


@pytest.mark.parametrize(("event", "expected"), _EVENTS_AND_PAYLOADS)
def test_each_event_publishes_its_own_data(
    event: WireEvent, expected: dict[str, object]
) -> None:
    assert event.to_payload() == expected


@pytest.mark.parametrize(("event", "expected"), _EVENTS_AND_PAYLOADS)
def test_the_payload_names_the_event_and_where_it_happened(
    event: WireEvent, expected: dict[str, object]
) -> None:
    # The identity keys belong to EventPayload — no event may shadow one with a
    # field of its own.
    payload = event.to_payload()
    assert payload["kind"] == cast("_Kinded", event).kind
    assert payload["scene_id"] == event.scene_id
    assert payload["element_id"] == event.element_id
    assert expected["kind"] == cast("_Kinded", event).kind


def test_every_event_kind_is_covered() -> None:
    published = {payload["kind"] for _, payload in _EVENTS_AND_PAYLOADS}
    assert published == set(EventKind.__value__.__args__)


def test_a_row_selection_payload_is_json_ready() -> None:
    # row_ids is a tuple on the event and a list in the payload: the mapping
    # crosses to the agent as JSON, which has no tuple.
    event, _ = _EVENTS_AND_PAYLOADS[-1]
    assert isinstance(event.to_payload()["row_ids"], list)


def test_the_anchor_survives_when_the_selection_is_empty() -> None:
    # An empty selection is a real state (the user deselected everything); the
    # anchor is "" and the payload still says which element it happened on.
    event = RowSelectionChanged(
        scene_id=_SCENE,
        element_id=_ELEMENT,
        owner_id=_OWNER,
        row_ids=(),
        anchor="",
    )
    assert event.to_payload() == {
        "kind": "row_selection_changed",
        "scene_id": "scene-1",
        "element_id": "elem-1",
        "row_ids": [],
        "anchor": "",
    }


def test_the_owner_stays_out_of_the_payload() -> None:
    # Publish fan-out is scoped to the publishing connection, so a subscriber
    # only ever sees its own scope's events — the owning client's id would
    # answer nothing it can ask.
    for event, _ in _EVENTS_AND_PAYLOADS:
        assert "owner_id" not in event.to_payload()


class TestEventPayload:
    def test_identity_keys_come_first_then_the_events_own_fields(self) -> None:
        payload = EventPayload(
            kind="value_changed", scene_id=_SCENE, element_id=_ELEMENT
        ).to_mapping(value=7)
        assert list(payload) == ["kind", "scene_id", "element_id", "value"]

    def test_an_event_with_no_data_of_its_own_publishes_identity_alone(self) -> None:
        payload = EventPayload(
            kind="button_clicked", scene_id=_SCENE, element_id=_ELEMENT
        ).to_mapping()
        assert payload == {
            "kind": "button_clicked",
            "scene_id": "scene-1",
            "element_id": "elem-1",
        }
