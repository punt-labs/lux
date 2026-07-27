"""Migration gate for the ABC ``modal`` — an interactive composite.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the all-ABC fork gate,
and the dismiss round trip. A user close routes to the Hub as a ``ModalClosed``
interaction whose built-in handler drives ``model.close`` -> ``mark_removed``, so
the removal cascade drops the modal from both tiers — the D21 path a dialog
dismiss uses. Levels 2, 3, and 5 drive the real Hub/Display boundary — the pickle
scene wire and the ``DisplayServer`` receive/rebind path — never a stub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    CollapsingHeaderElement,
    GroupElement,
    ModalElement,
    ProgressElement,
    TextElement,
    WindowElement,
)
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


# -- builders ---------------------------------------------------------------


def _abc_modal(
    *,
    open: bool = True,
    title: str = "Confirm",
    children: Iterable[AbcElement] | None = None,
) -> ModalElement:
    """Build an all-ABC modal holding a text and a button by default."""
    modal = ModalElement(id="m", title=title, open=open)
    body: tuple[AbcElement, ...] = (
        (TextElement(id="t1", content="Delete?"), ButtonElement(id="b1", label="Yes"))
        if children is None
        else tuple(children)
    )
    modal.install_children(body)
    return modal


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_open_modal_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(restored, ModalElement)
        assert restored.open is True
        assert restored.title == "Confirm"
        assert [c.id for c in restored.children] == ["t1", "b1"]

    def test_closed_modal_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_modal(open=False).to_dict())
        assert isinstance(restored, ModalElement)
        assert restored.open is False

    def test_abc_children_decode_to_abc(self) -> None:
        restored = _decode(_abc_modal().to_dict())
        assert isinstance(restored, ModalElement)
        assert isinstance(restored.children[0], TextElement)
        assert isinstance(restored.children[1], ButtonElement)

    def test_empty_modal_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_modal(children=()).to_dict())
        assert isinstance(restored, ModalElement)
        assert restored.children == ()

    def test_wire_shape_carries_open_title_and_children(self) -> None:
        assert _abc_modal(open=True).to_dict() == {
            "kind": "modal",
            "id": "m",
            "title": "Confirm",
            "open": True,
            "children": [
                {"kind": "text", "id": "t1", "content": "Delete?"},
                {"kind": "button", "id": "b1", "label": "Yes"},
            ],
        }

    def test_nested_in_abc_group_stays_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "children": [_abc_modal(open=True).to_dict()],
        }
        group = _decode(wire)
        assert isinstance(group, HasChildElements)
        modal = group.child_elements()[0]
        assert isinstance(modal, ModalElement)
        assert modal.open is True


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_from_dict_rejects_non_abc_subtree(self) -> None:
        wire = {
            "kind": "modal",
            "id": "m",
            "title": "T",
            "children": [
                {"kind": "group", "id": "lg", "layout": "paged", "children": []}
            ],
        }
        with pytest.raises(ValueError, match="paged"):
            ModalElement.from_dict(wire)


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_modal_has_no_errors(self) -> None:
        assert ElementTreeValidator().validate_tree([_abc_modal()]).ok

    def test_nested_malformed_child_is_collected_by_the_walk(self) -> None:
        # A progress with an out-of-range fraction nested in the modal body is
        # surfaced by the hierarchy walk, not silently rendered.
        modal = _abc_modal(children=(ProgressElement(id="p", fraction=5.0),))
        report = ElementTreeValidator().validate_tree([modal])
        assert not report.ok
        assert any(e.element_id == "p" for e in report.errors)

    def test_child_elements_bridges_the_walk(self) -> None:
        modal = _abc_modal()
        assert modal.child_elements() == modal.children

    def test_structural_guard_modal_is_a_container(self) -> None:
        modal = ModalElement(id="m", title="T")
        assert isinstance(modal, HasChildElements)
        assert isinstance(modal, AbcElement)


class TestForbidWindowInModal:
    """A window always floats top-level, so it cannot nest inside a modal.

    Forbidden at both boundaries anywhere in the subtree; a group or a
    collapsing_header is the sanctioned way to panel a modal's body.
    """

    _MSG = "window cannot nest inside a modal"

    def test_validate_rejects_a_direct_window_child(self) -> None:
        modal = _abc_modal(children=(WindowElement(id="w"),))
        report = ElementTreeValidator().validate_tree([modal])
        assert not report.ok
        assert any(self._MSG in e.message for e in report.errors)
        assert any(e.element_kind == "modal" for e in report.errors)

    def test_validate_rejects_a_window_nested_in_a_group(self) -> None:
        modal = _abc_modal(
            children=(GroupElement(id="g", children=(WindowElement(id="w"),)),)
        )
        report = ElementTreeValidator().validate_tree([modal])
        assert not report.ok
        assert any(self._MSG in e.message for e in report.errors)

    def test_from_dict_rejects_a_window_descendant(self) -> None:
        wire = {
            "kind": "modal",
            "id": "m",
            "children": [{"kind": "window", "id": "w"}],
        }
        with pytest.raises(ValueError, match=self._MSG):
            ModalElement.from_dict(wire)

    def test_from_dict_rejects_a_window_in_a_group_in_a_modal(self) -> None:
        window = {"kind": "window", "id": "w"}
        wire = {
            "kind": "modal",
            "id": "m",
            "children": [{"kind": "group", "id": "g", "children": [window]}],
        }
        with pytest.raises(ValueError, match=self._MSG):
            ModalElement.from_dict(wire)

    def test_group_and_header_children_are_fine(self) -> None:
        modal = _abc_modal(
            children=(
                GroupElement(id="g", children=(TextElement(id="t", content="hi"),)),
                CollapsingHeaderElement(
                    id="h", label="More", children=(ButtonElement(id="b", label="Go"),)
                ),
            )
        )
        assert ElementTreeValidator().validate_tree([modal]).ok

    def test_window_at_scene_level_is_unaffected(self) -> None:
        # A window as a top-level scene element (not inside a modal) is valid;
        # only the modal nesting is forbidden.
        scene = [WindowElement(id="w"), _abc_modal()]
        assert ElementTreeValidator().validate_tree(scene).ok

    @patch(_CLIENT_GET)
    def test_show_rejects_a_window_in_a_modal(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "modal",
                    "id": "m",
                    "title": "Confirm",
                    "children": [{"kind": "window", "id": "w"}],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert self._MSG in result
        client.show.assert_not_called()


class TestShowRejectsInvalidModal:
    @patch(_CLIENT_GET)
    def test_show_rejects_progress_nested_in_modal(self, mock_get: MagicMock) -> None:
        """A bad progress nested in the modal body is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "modal",
                    "id": "m",
                    "title": "Confirm",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "progress", "id": "bad", "fraction": -0.5},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[progress 'bad']" in result
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_modal_crosses_as_pickled_entry_with_children(self) -> None:
        modal = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(modal, ModalElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[modal], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC modal must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_modal = restored.elements[0]
        assert isinstance(r_modal, ModalElement)
        assert r_modal.open is True
        assert [c.id for c in r_modal.children] == ["t1", "b1"]

    def test_builtin_dismiss_handler_survives_the_wire(self) -> None:
        # The Display's wrap depends on the built-in ModalClosed handler being
        # present after the pickle crossing.
        modal = _decode(_abc_modal().to_dict())
        assert isinstance(modal, ModalElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[modal], frame_id="s1"))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_modal = restored.elements[0]
        assert isinstance(r_modal, ModalElement)
        assert r_modal.handler_count(ModalClosed) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


def _received(msg: SceneMessage) -> SceneMessage:
    restored = message_from_dict(message_to_dict(msg))
    assert isinstance(restored, SceneMessage)
    return restored


class TestLevel3Crossing:
    def test_rebind_recurses_into_modal_children(self) -> None:
        modal = _decode(_abc_modal().to_dict())
        assert isinstance(modal, ModalElement)
        received = _received(SceneMessage(id="s1", elements=[modal], frame_id="s1"))
        r_modal = received.elements[0]
        assert isinstance(r_modal, ModalElement)
        child = r_modal.children[0]

        modal_factory = r_modal._renderer_factory
        child_factory = child._renderer_factory
        assert isinstance(modal_factory, RaisingRendererFactory)
        assert isinstance(child_factory, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert r_modal._renderer_factory is factory
        assert child._renderer_factory is factory


# -- dismiss round trip (the D21 removal path) ------------------------------


class TestDismiss:
    def test_builtin_handler_dismisses_and_removes_on_the_hub_copy(self) -> None:
        # Firing ModalClosed on an unwrapped (Hub-side) copy runs the built-in
        # dismiss handler: the model closes and the removal cascade fires.
        modal = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(modal, ModalElement)
        modal.fire(
            ModalClosed(
                scene_id=SceneId("s"),
                element_id=ElementId("m"),
                owner_id=ClientId("c"),
            )
        )
        assert modal.open is False
        assert modal.removed is True

    def test_close_notifies_a_parent_observer(self) -> None:
        # The removal cascade a HubDisplay root relies on: the model dismiss
        # reaches the observer registered on the element.
        modal = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(modal, ModalElement)
        seen: list[str] = []
        modal.add_observer(seen.append)
        modal.fire(
            ModalClosed(
                scene_id=SceneId("s"),
                element_id=ElementId("m"),
                owner_id=ClientId("c"),
            )
        )
        assert seen == ["removed"]

    def test_wrapped_close_sends_one_invocation_and_does_not_run_locally(self) -> None:
        # On the Display copy the bucket is wrapped: a close sends exactly one
        # RemoteEventHandlerInvocation and never runs the dismiss locally.
        modal = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(modal, ModalElement)
        sent: list[RemoteEventHandlerInvocation] = []
        modal.wrap_handlers_for_remote(sent.append)

        modal.fire(
            ModalClosed(
                scene_id=SceneId("s"),
                element_id=ElementId("m"),
                owner_id=ClientId("c"),
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "modal_closed"
        assert sent[0].element_id == "m"
        assert sent[0].value is None
        # The display replica did not dismiss locally — the Hub owns removal.
        assert modal.open is True
        assert modal.removed is False


# -- Level 5: introspection (render_path + resolved props) ------------------


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


class TestLevel5Introspection:
    def test_modal_and_children_report_abc_render_path(self) -> None:
        modal = _decode(_abc_modal().to_dict())
        assert isinstance(modal, ModalElement)
        resp = _inspect(_server(), modal)
        assert _record(resp, "m")["render_path"] == "abc"
        assert _record(resp, "t1")["render_path"] == "abc"
        assert _record(resp, "b1")["render_path"] == "abc"

    def test_resolved_props_reports_the_open_flag(self) -> None:
        modal = _decode(_abc_modal(open=True).to_dict())
        assert isinstance(modal, ModalElement)
        resp = _inspect(_server(), modal)
        props = _record(resp, "m")["props"]
        assert isinstance(props, dict)
        assert props["open"] is True
        assert props["title"] == "Confirm"
        assert props["children"] == ["t1", "b1"]


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_modal_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(_abc_modal(open=True))
        assert encoded["kind"] == "modal"
        assert encoded["open"] is True
        children = cast("list[dict[str, Any]]", encoded["children"])
        assert [child["id"] for child in children] == ["t1", "b1"]


class TestTooltipRoundTrip:
    def test_tooltip_round_trips_through_abc_path(self) -> None:
        modal = ModalElement(id="m", title="T", tooltip="hint")
        modal.install_children((TextElement(id="t1", content="x"),))
        restored = _decode(modal.to_dict())
        assert isinstance(restored, ModalElement)
        assert restored.tooltip == "hint"

    def test_absent_tooltip_stays_absent(self) -> None:
        wire = _abc_modal().to_dict()
        assert "tooltip" not in wire
        restored = _decode(wire)
        assert isinstance(restored, ModalElement)
        assert restored.tooltip is None
