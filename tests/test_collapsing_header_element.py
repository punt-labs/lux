"""Migration gate for the ABC ``collapsing_header`` — an interactive container.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the all-ABC fork gate,
the built-in state-sync, and the echo-suppression safety property. Levels 2,
3, and 5 drive the real Hub/Display boundary — the pickle scene wire and the
``DisplayServer`` receive/rebind path — never a stub. The Level-4 interactive and
child-forwarding round trips live in the business-event-loop harness
(``tests/e2e/scenario.py``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.collapsing_header import (
    ImGuiCollapsingHeaderRenderer,
)
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    CollapsingHeaderElement,
    LegacyCollapsingHeaderElement,
    ProgressElement,
    TextElement,
)
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


# -- builders ---------------------------------------------------------------


def _abc_header(
    *, open: bool = False, label: str = "Section"
) -> CollapsingHeaderElement:
    """Build an all-ABC collapsing_header holding a text and a button."""
    return CollapsingHeaderElement(
        id="ch",
        label=label,
        open=open,
        children=(
            TextElement(id="t1", content="left"),
            ButtonElement(id="b1", label="right"),
        ),
    )


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_open_header_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_header(open=True).to_dict())
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.open is True
        assert restored.label == "Section"
        assert [c.id for c in restored.children] == ["t1", "b1"]

    def test_closed_header_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_header(open=False).to_dict())
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.open is False

    def test_default_open_alias_decodes_to_open(self) -> None:
        # Pre-migration wire used ``default_open``; the ABC decoder honours it
        # as an alias for ``open`` so older payloads still open the header.
        wire = {
            "kind": "collapsing_header",
            "id": "ch",
            "label": "Section",
            "default_open": True,
            "children": [],
        }
        restored = _decode(wire)
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.open is True

    def test_open_wins_over_default_open_alias(self) -> None:
        # When both fields are present, the canonical ``open`` field decides.
        wire = {
            "kind": "collapsing_header",
            "id": "ch",
            "label": "Section",
            "open": False,
            "default_open": True,
            "children": [],
        }
        restored = _decode(wire)
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.open is False

    def test_abc_children_decode_to_abc(self) -> None:
        restored = _decode(_abc_header().to_dict())
        assert isinstance(restored, CollapsingHeaderElement)
        assert isinstance(restored.children[0], TextElement)
        assert isinstance(restored.children[1], ButtonElement)

    def test_empty_header_roundtrips_to_abc(self) -> None:
        restored = _decode(CollapsingHeaderElement(id="ch", label="S").to_dict())
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.children == ()

    def test_wire_shape_carries_open_and_children(self) -> None:
        assert _abc_header(open=True).to_dict() == {
            "kind": "collapsing_header",
            "id": "ch",
            "label": "Section",
            "open": True,
            "children": [
                {"kind": "text", "id": "t1", "content": "left"},
                {"kind": "button", "id": "b1", "label": "right"},
            ],
        }

    def test_nested_in_abc_group_stays_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "children": [_abc_header(open=True).to_dict()],
        }
        group = _decode(wire)
        assert isinstance(group, HasChildElements)
        header = group.child_elements()[0]
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is True


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_header_is_abc(self) -> None:
        assert ContainerAbcGate.is_all_abc(_abc_header().to_dict())

    def test_legacy_child_forces_legacy(self) -> None:
        wire = {
            "kind": "collapsing_header",
            "id": "ch",
            "label": "S",
            "children": [{"kind": "table", "id": "t", "columns": ["A"], "rows": []}],
        }
        assert not ContainerAbcGate.is_all_abc(wire)
        assert isinstance(_decode(wire), LegacyCollapsingHeaderElement)

    def test_from_dict_rejects_non_abc_subtree(self) -> None:
        wire = {
            "kind": "collapsing_header",
            "id": "ch",
            "label": "S",
            "children": [{"kind": "table", "id": "t", "columns": ["A"], "rows": []}],
        }
        with pytest.raises(ValueError, match="table"):
            CollapsingHeaderElement.from_dict(wire)

    def test_header_in_legacy_container_is_forced_legacy(self) -> None:
        # A header nested inside a legacy window (a legacy sibling table forces
        # the window legacy) must itself decode legacy — an ABC container never
        # nests inside a legacy render subtree.
        wire = {
            "kind": "window",
            "id": "w",
            "children": [
                {"kind": "table", "id": "tbl", "columns": ["A"], "rows": []},
                _abc_header().to_dict(),
            ],
        }
        window = _decode(wire)
        assert isinstance(window, HasChildElements)
        header = window.child_elements()[1]
        assert isinstance(header, LegacyCollapsingHeaderElement)


# -- self-validation --------------------------------------------------------


class TestSelfValidation:
    def test_valid_header_has_no_errors(self) -> None:
        assert ElementTreeValidator().validate_tree([_abc_header()]).ok

    def test_empty_label_is_reported(self) -> None:
        report = ElementTreeValidator().validate_tree(
            [CollapsingHeaderElement(id="ch", label="")]
        )
        assert not report.ok
        assert report.errors[0].element_id == "ch"
        assert report.errors[0].element_kind == "collapsing_header"
        assert "non-empty label" in report.errors[0].message

    def test_nested_malformed_child_is_collected_by_the_walk(self) -> None:
        # A progress with an out-of-range fraction nested in the header is
        # surfaced by the hierarchy walk, not silently rendered.
        header = CollapsingHeaderElement(
            id="ch",
            label="S",
            children=(ProgressElement(id="p", fraction=5.0),),
        )
        report = ElementTreeValidator().validate_tree([header])
        assert not report.ok
        assert any(e.element_id == "p" for e in report.errors)

    def test_child_elements_bridges_the_walk(self) -> None:
        header = _abc_header()
        assert header.child_elements() == header.children

    def test_structural_guard_header_is_a_container(self) -> None:
        header = CollapsingHeaderElement(id="ch", label="S")
        assert isinstance(header, HasChildElements)
        assert isinstance(header, AbcElement)


class TestShowRejectsInvalidHeader:
    @patch(_CLIENT_GET)
    def test_show_rejects_empty_label(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [{"kind": "collapsing_header", "id": "ch", "label": "", "children": []}],
        )
        assert result.startswith("error: scene not rendered")
        assert "[collapsing_header 'ch']" in result
        assert "non-empty label" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_progress_nested_in_header(self, mock_get: MagicMock) -> None:
        """A bad progress nested in the header body is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "collapsing_header",
                    "id": "ch",
                    "label": "Section",
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
    def test_header_crosses_as_pickled_entry_with_children(self) -> None:
        header = _decode(_abc_header(open=True).to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[header]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC header must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_header = restored.elements[0]
        assert isinstance(r_header, CollapsingHeaderElement)
        assert r_header.open is True
        assert [c.id for c in r_header.children] == ["t1", "b1"]

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        # The Display's wrap depends on the built-in HeaderToggled handler
        # being present after the pickle crossing.
        header = _decode(_abc_header().to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[header]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_header = restored.elements[0]
        assert isinstance(r_header, CollapsingHeaderElement)
        assert r_header.handler_count(HeaderToggled) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


def _received(msg: SceneMessage) -> SceneMessage:
    restored = message_from_dict(message_to_dict(msg))
    assert isinstance(restored, SceneMessage)
    return restored


class TestLevel3Crossing:
    def test_rebind_recurses_into_header_children(self) -> None:
        header = _decode(_abc_header().to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        received = _received(SceneMessage(id="s1", elements=[header]))
        r_header = received.elements[0]
        assert isinstance(r_header, CollapsingHeaderElement)
        child = r_header.children[0]

        header_factory = r_header._renderer_factory
        child_factory = child._renderer_factory
        assert isinstance(header_factory, RaisingRendererFactory)
        assert isinstance(child_factory, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert r_header._renderer_factory is factory
        assert child._renderer_factory is factory


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    def test_builtin_handler_syncs_open_on_the_hub_copy(self) -> None:
        # Firing HeaderToggled on an unwrapped (Hub-side) copy runs the built-in
        # state-sync handler, mirroring the new open flag onto the element.
        header = _decode(_abc_header(open=False).to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        header.fire(
            HeaderToggled(
                scene_id=SceneId("s"),
                element_id=ElementId("ch"),
                owner_id=ClientId("c"),
                open_=True,
            )
        )
        assert header.open is True

    def test_hub_driven_change_does_not_refire(self) -> None:
        # ECHO-SUPPRESSION: a Hub-driven change to ``open`` (what a re-push's
        # new state carries) must NOT emit a RemoteEventHandlerInvocation, or a
        # fire -> Hub -> re-push -> fire loop would run forever. A genuine user
        # gesture DOES emit exactly one.
        header = _decode(_abc_header(open=False).to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        sent: list[RemoteEventHandlerInvocation] = []
        header.wrap_handlers_for_remote(sent.append)

        header.apply_patch({"open": True})
        assert sent == [], "a Hub-set open must not fire an interaction"

        header.fire(
            HeaderToggled(
                scene_id=SceneId("s"),
                element_id=ElementId("ch"),
                owner_id=ClientId("c"),
                open_=False,
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "header_toggled"
        assert sent[0].value is False

    def test_renderer_honours_hub_value_without_firing(self) -> None:
        # The renderer's fire decision is the source of echo-suppression: when
        # ImGui reports the same state the Hub owns (an honoured value), it
        # returns no event; a divergent reported state is a user toggle.
        header = _abc_header(open=False)
        factory = _server()._imgui_renderer_factory
        renderer = ImGuiCollapsingHeaderRenderer(header, factory)
        assert renderer._toggle_event(reported=False) is None
        toggled = renderer._toggle_event(reported=True)
        assert toggled is not None
        assert toggled.open is True


# -- Level 5: introspection (render_path + reported view-state) --------------


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    return sock


def _inspect(server: DisplayServer, *elements: Element) -> QueryResponse:
    server._handle_message(_mock_sock(), SceneMessage(id="s1", elements=list(elements)))
    return server.query_dispatcher.handle_query("inspect_scene", {"scene_id": "s1"})


def _record(resp: QueryResponse, element_id: str) -> dict[str, object]:
    result = resp.result
    assert result is not None, resp.error
    paths = result["element_paths"]
    assert isinstance(paths, list)
    return next(r for r in paths if r["id"] == element_id)


class TestLevel5Introspection:
    def test_header_and_children_report_abc_render_path(self) -> None:
        header = _decode(_abc_header().to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        resp = _inspect(_server(), header)
        assert _record(resp, "ch")["render_path"] == "abc"
        assert _record(resp, "t1")["render_path"] == "abc"
        assert _record(resp, "b1")["render_path"] == "abc"

    def test_resolved_props_reports_the_open_view_state(self) -> None:
        header = _decode(_abc_header(open=True).to_dict())
        assert isinstance(header, CollapsingHeaderElement)
        resp = _inspect(_server(), header)
        props = _record(resp, "ch")["props"]
        assert isinstance(props, dict)
        assert props["open"] is True
        assert props["label"] == "Section"
        assert props["children"] == ["t1", "b1"]

    def test_legacy_header_reports_legacy_render_path(self) -> None:
        legacy = LegacyCollapsingHeaderElement(
            id="ch",
            label="S",
            children=[TextElement(id="t1", content="x")],
        )
        resp = _inspect(_server(), legacy)
        assert _record(resp, "ch")["render_path"] == "legacy"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_header_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(_abc_header(open=True))
        assert encoded["kind"] == "collapsing_header"
        assert encoded["open"] is True
        children = cast("list[dict[str, Any]]", encoded["children"])
        assert [child["id"] for child in children] == ["t1", "b1"]


class TestTooltipRoundTrip:
    def test_tooltip_round_trips_through_abc_path(self) -> None:
        header = CollapsingHeaderElement(
            id="ch",
            label="S",
            children=(TextElement(id="t1", content="x"),),
            tooltip="hint",
        )
        restored = _decode(header.to_dict())
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.tooltip == "hint"

    def test_absent_tooltip_stays_absent(self) -> None:
        wire = _abc_header().to_dict()
        assert "tooltip" not in wire
        restored = _decode(wire)
        assert isinstance(restored, CollapsingHeaderElement)
        assert restored.tooltip is None
