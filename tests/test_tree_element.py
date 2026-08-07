"""Migration gate for the ABC ``tree`` leaf — Levels 1-5 + boundary validation.

A display-only leaf: an optional heading plus a recursive ``TreeNode`` value
family, no child elements and no interaction (Level 4 is N/A). Node
well-formedness is a wire-boundary concern (``TreeNode.decode_all`` raises on a
non-mapping or label-less node), the same composition ruling the draw-command
family follows, so an invalid tree is refused before it reaches the display.
Levels 3 and 5 drive the real Hub/Display boundary — the pickle scene wire and
the ``DisplayServer`` receive/rebind path — never a stub. The painted-rect test
proves the leaf adapter records geometry through the ``measuring`` group.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display import geometry_capture
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.tree import ImGuiTreeRenderer
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import GroupElement, TreeElement
from punt_lux.protocol.elements.tree_node import TreeNode
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.tools import show

from .geometry_doubles import EXPECTED_RECT, FakeGeomImgui, GeomFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


# -- helpers ----------------------------------------------------------------


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
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


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _tree() -> TreeElement:
    return TreeElement(
        id="tr",
        label="Project",
        nodes=(
            TreeNode(
                label="src",
                children=(TreeNode(label="main.py"), TreeNode(label="lib.py")),
            ),
            TreeNode(label="README.md"),
        ),
    )


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_tree_roundtrips_to_abc(self) -> None:
        restored = _decode(_tree().to_dict())
        assert isinstance(restored, TreeElement)
        assert restored.label == "Project"
        assert restored.nodes[0].label == "src"
        assert restored.nodes[0].children[0].label == "main.py"

    def test_tooltip_round_trips_through_abc_path(self) -> None:
        wire = TreeElement(id="tr", label="Files", tooltip="explorer").to_dict()
        assert wire["tooltip"] == "explorer"
        restored = _decode(wire)
        assert isinstance(restored, TreeElement)
        assert restored.tooltip == "explorer"

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        assert TreeElement(
            id="tr", label="Files", nodes=(TreeNode(label="a"),)
        ).to_dict() == {
            "kind": "tree",
            "id": "tr",
            "label": "Files",
            "nodes": [{"label": "a"}],
        }

    def test_defaults_omit_flat_and_tooltip(self) -> None:
        assert TreeElement(id="tr").to_dict() == {
            "kind": "tree",
            "id": "tr",
            "label": "",
            "nodes": [],
        }

    def test_flat_only_serialized_when_true(self) -> None:
        assert TreeElement(id="tr", flat=True).to_dict()["flat"] is True


# -- boundary validation (nodes are a typed value family) -------------------


class TestNodeBoundaryValidation:
    def test_well_formed_tree_passes_the_walk(self) -> None:
        assert ElementTreeValidator().validate_tree([_tree()]).ok

    def test_tree_exposes_no_child_elements(self) -> None:
        # A tree's nodes are values, not elements; the walk has nothing to recurse.
        assert _tree().child_elements() == ()

    def test_non_mapping_node_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"nodes\[0\] must be a mapping"):
            TreeElement.from_dict({"kind": "tree", "id": "tr", "nodes": [42]})

    def test_label_less_node_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"nodes\[0\] is missing a string 'label'"):
            TreeElement.from_dict(
                {"kind": "tree", "id": "tr", "nodes": [{"note": "no label"}]}
            )

    def test_non_list_nodes_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="nodes must be a list of nodes"):
            TreeElement.from_dict({"kind": "tree", "id": "tr", "nodes": "oops"})

    def test_malformed_grandchild_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"nodes\[0\].children\[0\] must be"):
            TreeElement.from_dict(
                {
                    "kind": "tree",
                    "id": "tr",
                    "nodes": [{"label": "root", "children": [42]}],
                }
            )


class TestShowRejectsMalformedTree:
    @patch(_CLIENT_GET)
    def test_show_rejects_label_less_node(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show("s1", [{"kind": "tree", "id": "tr", "nodes": [{"x": 1}]}])
        assert result.startswith("error: scene not rendered")
        assert "label" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_malformed_tree_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {"kind": "tree", "id": "bad", "nodes": [42]},
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        client.show.assert_not_called()


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_tree_crosses_as_pickled_entry(self) -> None:
        wire = message_to_dict(SceneMessage(id="s1", elements=[_tree()], frame_id="s1"))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC tree must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, TreeElement)
        assert r.nodes[0].label == "src"


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


class TestLevel3Crossing:
    def test_rebind_binds_the_tree_renderer_factory(self) -> None:
        received = message_from_dict(
            message_to_dict(SceneMessage(id="s1", elements=[_tree()], frame_id="s1"))
        )
        assert isinstance(received, SceneMessage)
        tree = received.elements[0]
        assert isinstance(tree, TreeElement)
        before = tree._renderer_factory
        assert isinstance(before, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert tree._renderer_factory is factory


# -- ABC decode nesting -----------------------------------------------------


class TestForkGate:
    def test_all_abc_group_with_tree_is_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "tree", "id": "tr", "nodes": [{"label": "a"}]}],
        }
        group = _decode(wire)
        assert isinstance(group, GroupElement)
        assert isinstance(group.children[0], TreeElement)

    def test_group_and_tree_child_are_recorded(self) -> None:
        group = GroupElement(id="g1", children=(_tree(),))
        resp = _inspect(_server(), group)
        assert _record(resp, "g1")["kind"] == "group"
        assert _record(resp, "tr")["kind"] == "tree"


# -- Level 5: introspection -------------------------------------------------


class TestLevel5Introspection:
    def test_tree_is_recorded(self) -> None:
        resp = _inspect(_server(), _tree())
        assert _record(resp, "tr")["kind"] == "tree"

    def test_tree_resolved_props_read_back_including_defaults(self) -> None:
        resp = _inspect(_server(), TreeElement(id="tr", label="Files"))
        props = _record(resp, "tr")["props"]
        assert props == {"label": "Files", "nodes": [], "flat": False, "tooltip": None}


class TestPatchPath:
    def test_apply_patch_replaces_nodes_in_place(self) -> None:
        tree = TreeElement(id="tr", nodes=(TreeNode(label="old"),))
        returned = tree.apply_patch({"nodes": [{"label": "new"}]})
        assert returned is tree
        assert tree.nodes == (TreeNode(label="new"),)

    def test_apply_patch_sets_label_and_flat(self) -> None:
        tree = TreeElement(id="tr")
        tree.apply_patch({"label": "Root", "flat": True})
        assert tree.label == "Root"
        assert tree.flat is True

    def test_apply_patch_rejects_malformed_nodes(self) -> None:
        tree = TreeElement(id="tr", nodes=(TreeNode(label="keep"),))
        with pytest.raises(ValueError, match="label"):
            tree.apply_patch({"nodes": [{"no": "label"}]})
        assert tree.nodes == (TreeNode(label="keep"),)


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_tree_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(
            TreeElement(id="tr", label="X", nodes=(TreeNode(label="a"),))
        )
        assert encoded == {
            "kind": "tree",
            "id": "tr",
            "label": "X",
            "nodes": [{"label": "a"}],
        }


# -- painted geometry: the leaf records a rect through the measuring group ---


def test_tree_adapter_records_a_painted_rect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geometry_capture, "imgui", FakeGeomImgui())
    monkeypatch.setattr("punt_lux.display.renderers.imgui.tree.imgui", MagicMock())
    factory = GeomFactory()
    factory.geometry.enter_scene("s1")

    adapter = ImGuiTreeRenderer(_tree(), cast("ImGuiRendererFactory", factory))
    adapter.paint()
    factory.geometry.complete()

    geom = factory.geometry.recorder.snapshot().element_for("s1", "tr")
    assert geom is not None
    assert geom.rect == EXPECTED_RECT


# -- anonymous id scope: two anonymous trees never share expansion state -----


def test_anonymous_tree_scopes_paint_under_object_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_imgui = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.tree.imgui", mock_imgui)
    tree = TreeElement(id="", nodes=(TreeNode(label="a"),))

    renderer = ImGuiTreeRenderer(tree, cast("ImGuiRendererFactory", MagicMock()))
    renderer._paint_widget()

    assert mock_imgui.push_id.call_args_list[0].args[0] == f"anon-{id(tree)}"
    mock_imgui.pop_id.assert_called_once()


def test_two_anonymous_trees_get_distinct_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_imgui = MagicMock()
    monkeypatch.setattr("punt_lux.display.renderers.imgui.tree.imgui", mock_imgui)
    factory = cast("ImGuiRendererFactory", MagicMock())
    first = TreeElement(id="", nodes=(TreeNode(label="a"),))
    second = TreeElement(id="", nodes=(TreeNode(label="a"),))

    ImGuiTreeRenderer(first, factory)._paint_widget()
    ImGuiTreeRenderer(second, factory)._paint_widget()

    scopes = [call.args[0] for call in mock_imgui.push_id.call_args_list]
    assert scopes[0] != scopes[1]
