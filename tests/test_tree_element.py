"""Migration gate for the ABC ``tree`` leaf — Levels 1-5 + boundary validation.

A display-only leaf: an optional heading plus a recursive ``TreeNode`` value
family, no child elements and no interaction (Level 4 is N/A). Node
well-formedness is a wire-boundary concern (``TreeNode.decode_all`` raises on a
non-mapping or label-less node), the same composition ruling the draw-command
family follows, so an invalid tree is refused before it reaches the display.
Levels 3 and 5 drive the real Hub/Display boundary — the pickle scene wire and
the ``RenderLoop`` receive/rebind path — never a stub. The painted-rect test
proves the leaf adapter records geometry through the ``measuring`` group.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from punt_lux.display import geometry_capture
from punt_lux.display.render_loop import RenderLoop
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.tree import ImGuiTreeRenderer
from punt_lux.domain.validation_walk import ElementTreeValidator
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.agent_factory import agent_element_factory
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


def _server() -> RenderLoop:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return RenderLoop(socket_path=str(Path(raw_dir) / "display.sock"))


def _mock_sock() -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = 7
    sock.send.side_effect = len  # a real socket accepts the bytes and returns the count
    return sock


def _inspect(server: RenderLoop, *elements: Element) -> QueryResponse:
    # A scene installs only from an identified 'hub' fd (bead lux-2kv9 / W1).
    server._socket_listener.register_client_identity(
        7, kind="hub", name="test-hub", connect_time=0.0
    )
    server._handle_message(
        _mock_sock(), SceneMessage(id="s1", elements=list(elements), frame_id="s1")
    )
    return server.query_router.handle_query("inspect_scene", {"scene_id": "s1"})


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

    def test_node_id_roundtrips_to_abc(self) -> None:
        tree = TreeElement(
            id="tr", nodes=(TreeNode(label="src", id="n0", children=()),)
        )
        restored = _decode(tree.to_dict())
        assert isinstance(restored, TreeElement)
        assert restored.nodes[0].id == "n0"

    def test_selection_state_roundtrips_to_abc(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="multi",
            selected_node_ids=frozenset({"n0", "n1"}),
            anchor_node_id="n1",
        )
        restored = _decode(tree.to_dict())
        assert isinstance(restored, TreeElement)
        assert restored.selection_mode == "multi"
        assert restored.selected_node_ids == frozenset({"n0", "n1"})
        assert restored.anchor_node_id == "n1"

    def test_every_public_field_survives_one_full_roundtrip(self) -> None:
        # A composite roundtrip, distinct from the field-at-a-time tests above:
        # catches an interaction bug (e.g. flat corrupting node decode) that a
        # test touching only one field at a time could miss.
        tree = TreeElement(
            id="tr",
            label="Project",
            nodes=(
                TreeNode(
                    label="src", id="n0", children=(TreeNode(label="main.py", id="n1"),)
                ),
            ),
            flat=True,
            tooltip="explorer",
            selection_mode="multi",
            selected_node_ids=frozenset({"n0", "n1"}),
            anchor_node_id="n1",
        )
        restored = _decode(tree.to_dict())
        assert isinstance(restored, TreeElement)
        assert restored.label == tree.label
        assert restored.nodes == tree.nodes
        assert restored.flat == tree.flat
        assert restored.tooltip == tree.tooltip
        assert restored.selection_mode == tree.selection_mode
        assert restored.selected_node_ids == tree.selected_node_ids
        assert restored.anchor_node_id == tree.anchor_node_id

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

    def test_defaults_omit_selection_fields(self) -> None:
        wire = TreeElement(id="tr").to_dict()
        assert "selection_mode" not in wire
        assert "selected_node_ids" not in wire
        assert "anchor_node_id" not in wire

    def test_node_id_omitted_when_empty(self) -> None:
        assert TreeElement(id="tr", nodes=(TreeNode(label="a"),)).to_dict()[
            "nodes"
        ] == [{"label": "a"}]

    def test_node_id_emitted_when_present(self) -> None:
        assert TreeElement(id="tr", nodes=(TreeNode(label="a", id="n0"),)).to_dict()[
            "nodes"
        ] == [{"label": "a", "id": "n0"}]

    def test_selection_fields_serialized_when_set(self) -> None:
        wire = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n0",
        ).to_dict()
        assert wire["selection_mode"] == "single"
        assert wire["selected_node_ids"] == ["n0"]
        assert wire["anchor_node_id"] == "n0"

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

    def test_non_string_node_id_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match=r"nodes\[0\]\.id must be a string"):
            TreeElement.from_dict(
                {"kind": "tree", "id": "tr", "nodes": [{"label": "a", "id": 42}]}
            )

    def test_invalid_selection_mode_rejected_at_boundary(self) -> None:
        with pytest.raises(ValueError, match="selection_mode must be one of"):
            TreeElement.from_dict(
                {"kind": "tree", "id": "tr", "selection_mode": "bogus"}
            )

    def test_unhashable_selection_mode_list_raises_value_error(self) -> None:
        # A list is unhashable; SelectionWire.decode_mode must check isinstance(str)
        # before the frozenset membership test, or this raises TypeError instead.
        with pytest.raises(ValueError, match="selection_mode must be one of"):
            TreeElement.from_dict({"kind": "tree", "id": "tr", "selection_mode": []})

    def test_unhashable_selection_mode_mapping_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="selection_mode must be one of"):
            TreeElement.from_dict({"kind": "tree", "id": "tr", "selection_mode": {}})


class TestShowRejectsMalformedTree:
    @patch(_CLIENT_GET)
    def test_show_rejects_label_less_node(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        with pytest.raises(ToolError) as _exc:
            show("s1", [{"kind": "tree", "id": "tr", "nodes": [{"x": 1}]}])
        result = str(_exc.value)
        assert result.startswith("error: scene not rendered")
        assert "label" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_malformed_tree_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client
        with pytest.raises(ToolError) as _exc:
            show(
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
        result = str(_exc.value)
        assert result.startswith("error: scene not rendered")
        client.show.assert_not_called()


class TestShowGatesOnSelectionValidation:
    """A selection-content violation is a ``validate()`` concern (DES-039),
    not a decode error, so it must ALSO gate ``show()`` — mirroring
    ``TestShowRejectsMalformedTree``'s node-shape coverage above."""

    @patch(_CLIENT_GET)
    def test_show_rejects_a_selected_id_naming_no_node(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client
        with pytest.raises(ToolError) as _exc:
            show(
                "s1",
                [
                    {
                        "kind": "tree",
                        "id": "tr",
                        "nodes": [{"label": "a", "id": "n0"}],
                        "selection_mode": "single",
                        "selected_node_ids": ["ghost"],
                    }
                ],
            )
        result = str(_exc.value)
        assert result.startswith("error: scene not rendered")
        assert "names no node" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_a_selection_invalid_tree_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client
        with pytest.raises(ToolError):
            show(
                "s1",
                [
                    {
                        "kind": "group",
                        "id": "g1",
                        "children": [
                            {"kind": "text", "id": "ok", "content": "fine"},
                            {
                                "kind": "tree",
                                "id": "bad",
                                "nodes": [{"label": "a", "id": "n0"}],
                                "selection_mode": "single",
                                "selected_node_ids": ["ghost"],
                            },
                        ],
                    }
                ],
            )
        client.show.assert_not_called()

    def test_a_selection_valid_tree_reaches_the_real_render_path(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
        )
        resp = _inspect(_server(), tree)
        assert _record(resp, "tr")["kind"] == "tree"


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

    def test_selection_set_on_the_hub_replicates_to_the_display(self) -> None:
        """A Hub-authoritative selection survives the Hub-to-Display wire.

        Mirrors the table's Level-2 pickled-entry crossing: the pickle wire IS
        the Hub-to-Display transport (tests/CLAUDE.md Level 2), so a
        ``TreeSelectionModel`` set on the Hub-side element and pushed across it
        must read back identically on what the Display receives — the
        Replication Policy's "the Hub may resend the whole UI; the Display
        replaces its previous copy" (target.md), applied to selection state.
        """
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n0",
        )
        wire = message_to_dict(SceneMessage(id="s1", elements=[tree], frame_id="s1"))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, TreeElement)
        assert r.selection_mode == "single"
        assert r.selected_node_ids == frozenset({"n0"})
        assert r.anchor_node_id == "n0"

    def test_every_public_field_survives_the_pickle_wire(self) -> None:
        # A composite crossing, distinct from the selection-only test above:
        # a loss in node data, label, flat, or tooltip could coexist with a
        # passing selection-only wire test.
        tree = TreeElement(
            id="tr",
            label="Project",
            nodes=(
                TreeNode(
                    label="src", id="n0", children=(TreeNode(label="main.py", id="n1"),)
                ),
            ),
            flat=True,
            tooltip="explorer",
            selection_mode="multi",
            selected_node_ids=frozenset({"n0", "n1"}),
            anchor_node_id="n1",
        )
        wire = message_to_dict(SceneMessage(id="s1", elements=[tree], frame_id="s1"))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r = restored.elements[0]
        assert isinstance(r, TreeElement)
        assert r.label == tree.label
        assert r.nodes == tree.nodes
        assert r.flat == tree.flat
        assert r.tooltip == tree.tooltip
        assert r.selection_mode == tree.selection_mode
        assert r.selected_node_ids == tree.selected_node_ids
        assert r.anchor_node_id == tree.anchor_node_id


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
        assert props == {
            "label": "Files",
            "nodes": [],
            "flat": False,
            "tooltip": None,
            "selection_mode": "none",
            "selected_node_ids": [],
            "anchor_node_id": "",
        }

    def test_hub_authoritative_selection_is_visible_through_inspection(self) -> None:
        # Drives the real RenderLoop install (``_handle_message``), not a stub —
        # the same "Hub installs, Display receives" path the wire-roundtrip test
        # in TestLevel2WireRoundtrip exercises at the message-codec layer.
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n0",
        )
        resp = _inspect(_server(), tree)
        props = cast("dict[str, object]", _record(resp, "tr")["props"])
        assert props["selection_mode"] == "single"
        assert props["selected_node_ids"] == ["n0"]
        assert props["anchor_node_id"] == "n0"


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


class TestPatchSelection:
    """apply_patch on the composed TreeSelectionModel, mirroring TableElement."""

    def _tree(self) -> TreeElement:
        return TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="multi",
        )

    def test_apply_patch_sets_selected_node_ids(self) -> None:
        tree = self._tree()
        tree.apply_patch({"selected_node_ids": ["n0", "n1"]})
        assert tree.selected_node_ids == frozenset({"n0", "n1"})

    def test_apply_patch_sets_anchor_node_id(self) -> None:
        tree = self._tree()
        tree.apply_patch({"selected_node_ids": ["n0", "n1"], "anchor_node_id": "n1"})
        assert tree.anchor_node_id == "n1"

    def test_selected_ids_are_reconciled_against_live_nodes(self) -> None:
        # A ghost id (one naming no live node) never lands in the authoritative
        # set — mirrors TableElement._set_selected_row_ids's live-id intersect.
        tree = self._tree()
        tree.apply_patch({"selected_node_ids": ["n0", "ghost"]})
        assert tree.selected_node_ids == frozenset({"n0"})

    def test_bad_selection_patch_names_the_public_field(self) -> None:
        # SelectionWire.decode_ids raises ValueError (mirroring TableWire.str_list),
        # not PatchField's TypeError — this setter routes through the shared
        # selection-ids wire coercion, not PatchField.
        tree = self._tree()
        with pytest.raises(ValueError, match="selected_node_ids"):
            tree.apply_patch({"selected_node_ids": "not-a-list"})

    def test_selection_survives_when_patch_lists_it_before_the_new_nodes(
        self,
    ) -> None:
        # apply_patch dispatches setters in the caller's dict order; a naive
        # dict-order dispatch would intersect "n1" against the pre-patch node
        # set (only n0) and silently drop it before "nodes" installs n1.
        tree = TreeElement(
            id="tr", nodes=(TreeNode(label="a", id="n0"),), selection_mode="single"
        )
        tree.apply_patch(
            {"selected_node_ids": ["n1"], "nodes": [{"label": "b", "id": "n1"}]}
        )
        assert tree.selected_node_ids == frozenset({"n1"})

    def test_anchor_survives_when_patch_lists_it_before_its_selection(self) -> None:
        tree = self._tree()
        tree.apply_patch({"anchor_node_id": "n1", "selected_node_ids": ["n0", "n1"]})
        assert tree.anchor_node_id == "n1"


class TestNodesReconcileSelection:
    """A ``nodes`` patch drops stale selection, mirroring TableElement._set_rows."""

    def test_nodes_patch_dropping_a_selected_id_reconciles(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="multi",
            selected_node_ids=frozenset({"n0", "n1"}),
            anchor_node_id="n1",
        )
        tree.apply_patch({"nodes": [{"label": "a", "id": "n0"}]})
        assert tree.selected_node_ids == frozenset({"n0"})
        assert tree.anchor_node_id == "n0"

    def test_nodes_patch_keeping_the_selection_survives(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n0",
        )
        tree.apply_patch({"nodes": [{"label": "renamed", "id": "n0"}]})
        assert tree.selected_node_ids == frozenset({"n0"})
        assert tree.anchor_node_id == "n0"

    def test_live_ids_are_collected_recursively(self) -> None:
        # A selection naming a grandchild's id survives a nodes patch that keeps
        # the grandchild — proves the recursive ``TreeNode.ids()`` walk, not just
        # a top-level scan.
        tree = TreeElement(
            id="tr",
            nodes=(
                TreeNode(
                    label="src", id="n0", children=(TreeNode(label="deep", id="n1"),)
                ),
            ),
            selection_mode="single",
            selected_node_ids=frozenset({"n1"}),
        )
        assert tree.selected_node_ids == frozenset({"n1"})
        tree.apply_patch(
            {
                "nodes": [
                    {
                        "label": "src",
                        "id": "n0",
                        "children": [{"label": "deep", "id": "n1"}],
                    }
                ]
            }
        )
        assert tree.selected_node_ids == frozenset({"n1"})


class TestValidate:
    """Selection self-validation (DES-039), mirroring TableValidator."""

    def test_display_only_tree_with_duplicate_ids_is_valid(self) -> None:
        # A ``none``-mode tree has no selection machinery to protect.
        tree = TreeElement(
            id="tr", nodes=(TreeNode(label="a", id="x"), TreeNode(label="b", id="x"))
        )
        assert tree.validate() == ()

    def test_selectable_duplicate_id_is_rejected(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="x"), TreeNode(label="b", id="x")),
            selection_mode="single",
        )
        errors = tree.validate()
        assert any("duplicate node id" in e.message for e in errors)

    def test_selected_id_naming_no_node_is_rejected(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"ghost"}),
        )
        errors = tree.validate()
        assert any("names no node" in e.message for e in errors)

    def test_single_select_with_two_ids_is_rejected(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="single",
            selected_node_ids=frozenset({"n0", "n1"}),
        )
        errors = tree.validate()
        assert any("more than one node" in e.message for e in errors)

    def test_anchor_not_in_selection_is_rejected(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"), TreeNode(label="b", id="n1")),
            selection_mode="multi",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n1",
        )
        errors = tree.validate()
        assert any("is not a selected node" in e.message for e in errors)

    def test_well_formed_selectable_tree_is_valid(self) -> None:
        tree = TreeElement(
            id="tr",
            nodes=(TreeNode(label="a", id="n0"),),
            selection_mode="single",
            selected_node_ids=frozenset({"n0"}),
            anchor_node_id="n0",
        )
        assert tree.validate() == ()

    def test_invalid_tree_is_collected_by_the_walk(self) -> None:
        group = GroupElement(
            id="g1",
            children=(
                TreeElement(
                    id="bad",
                    nodes=(TreeNode(label="a", id="n0"),),
                    selection_mode="single",
                    selected_node_ids=frozenset({"ghost"}),
                ),
            ),
        )
        result = ElementTreeValidator().validate_tree([group])
        assert not result.ok


class TestNodeIdsWalk:
    """``TreeNode.ids()`` — the recursive live-id source (PY-OO-5)."""

    def test_yields_own_id_when_present(self) -> None:
        assert list(TreeNode(label="a", id="n0").ids()) == ["n0"]

    def test_omits_own_id_when_empty(self) -> None:
        assert list(TreeNode(label="a").ids()) == []

    def test_yields_descendant_ids_depth_first(self) -> None:
        node = TreeNode(
            label="root",
            id="r",
            children=(
                TreeNode(
                    label="child", id="c", children=(TreeNode(label="gc", id="g"),)
                ),
            ),
        )
        assert list(node.ids()) == ["r", "c", "g"]

    def test_skips_unset_ids_among_set_ones(self) -> None:
        node = TreeNode(
            label="root", children=(TreeNode(label="a", id="x"), TreeNode(label="b"))
        )
        assert list(node.ids()) == ["x"]


class TestNodePositionalConstruction:
    """``id`` sits after ``children`` so the historical ``TreeNode(label,
    children)`` two-positional-arg call keeps binding to the same fields
    (PL-PP-1) — the field order change ``id`` requires stays additive."""

    def test_two_positional_args_bind_label_and_children(self) -> None:
        child = TreeNode(label="leaf")
        node = TreeNode("root", (child,))
        assert node.label == "root"
        assert node.children == (child,)
        assert node.id == ""

    def test_positionally_constructed_node_roundtrips_through_the_codec(self) -> None:
        node = TreeNode("root", (TreeNode(label="leaf", id="n0"),))
        restored = TreeNode.decode_all([TreeNode.to_dict(node)], "nodes")[0]
        assert restored == node


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


class TestNodeKeyStability:
    """A node's ImGui widget key follows its stable ``id``, not its sibling
    position — otherwise expand/collapse state migrates to the wrong node
    when the tree is reordered or a node is inserted."""

    def test_node_with_id_uses_the_id_not_the_position(self) -> None:
        key = ImGuiTreeRenderer._node_key(TreeNode(label="a", id="n0"), 3)
        assert key == "id:n0"

    def test_anonymous_node_falls_back_to_position(self) -> None:
        key = ImGuiTreeRenderer._node_key(TreeNode(label="a"), 3)
        assert key == "pos:3"

    def test_key_is_unchanged_when_the_node_moves_position(self) -> None:
        node = TreeNode(label="a", id="n0")
        assert ImGuiTreeRenderer._node_key(node, 0) == ImGuiTreeRenderer._node_key(
            node, 5
        )

    def test_stable_and_positional_keys_never_collide(self) -> None:
        # A stable id that happens to look like "pos:3" must not be mistaken
        # for the positional-fallback scheme, and vice versa.
        by_id = ImGuiTreeRenderer._node_key(TreeNode(label="a", id="3"), 0)
        by_pos = ImGuiTreeRenderer._node_key(TreeNode(label="b"), 3)
        assert by_id != by_pos
