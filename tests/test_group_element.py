"""Migration gate for the ABC ``group`` container (rows / columns).

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation and the all-ABC
fork gate. Levels 3 and 5 drive the real Hub/Display boundary — the pickle
scene wire and the ``DisplayServer`` receive/rebind path — never a stub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    GroupElement,
    LegacyGroupElement,
    ModalElement,
    TableElement,
    TextElement,
    WindowElement,
)
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element


# -- builders ---------------------------------------------------------------


def _stack_group(layout: str) -> GroupElement:
    """Build an all-ABC group with a text and a button child."""
    return GroupElement(
        id="g1",
        layout=layout,  # type: ignore[arg-type]  # test drives both stack layouts
        children=(
            TextElement(id="t1", content="left"),
            ButtonElement(id="b1", label="right"),
        ),
    )


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_rows_group_roundtrips_to_abc(self) -> None:
        restored = _decode(_stack_group("rows").to_dict())
        assert isinstance(restored, GroupElement)
        assert restored.layout == "rows"
        assert [c.id for c in restored.children] == ["t1", "b1"]

    def test_columns_group_roundtrips_to_abc(self) -> None:
        restored = _decode(_stack_group("columns").to_dict())
        assert isinstance(restored, GroupElement)
        assert restored.layout == "columns"

    def test_abc_children_decode_to_abc(self) -> None:
        restored = _decode(_stack_group("rows").to_dict())
        assert isinstance(restored, GroupElement)
        assert isinstance(restored.children[0], TextElement)
        assert isinstance(restored.children[1], ButtonElement)

    def test_empty_group_roundtrips_to_abc(self) -> None:
        restored = _decode(GroupElement(id="g1").to_dict())
        assert isinstance(restored, GroupElement)
        assert restored.children == ()

    def test_wire_shape_matches_legacy_bytes(self) -> None:
        """The ABC encoder emits the identical structural wire dict."""
        assert _stack_group("columns").to_dict() == {
            "kind": "group",
            "id": "g1",
            "layout": "columns",
            "children": [
                {"kind": "text", "id": "t1", "content": "left"},
                {"kind": "button", "id": "b1", "label": "right"},
            ],
        }


# -- the all-ABC fork gate --------------------------------------------------


def _inner_abc_group() -> dict[str, Any]:
    """Return a fresh wire dict for an all-ABC rows group with one text child."""
    return {
        "kind": "group",
        "id": "inner",
        "children": [{"kind": "text", "id": "t", "content": "x"}],
    }


def _table_wire() -> dict[str, Any]:
    """Return a legacy-kind child that forces its enclosing subtree legacy."""
    return {"kind": "table", "id": "tbl", "columns": ["A"], "rows": []}


# Each always-legacy container kind wrapping an all-ABC inner group, paired with
# the concrete legacy class the whole tree must decode to. A ``group`` becomes
# legacy only alongside a legacy sibling; ``tab_bar``, ``window``, and ``modal``
# have no ABC form yet, so they are always legacy and force any nested group
# legacy too. ``collapsing_header`` is now conditionally-ABC and has its own
# fork-gate coverage in ``test_collapsing_header_element``.
_LEGACY_CONTAINER_CASES: tuple[tuple[str, dict[str, Any], type], ...] = (
    (
        "legacy_group",
        {"kind": "group", "id": "o", "children": [_table_wire(), _inner_abc_group()]},
        LegacyGroupElement,
    ),
    (
        "window",
        {"kind": "window", "id": "w", "children": [_inner_abc_group()]},
        WindowElement,
    ),
    (
        "modal",
        {"kind": "modal", "id": "m", "children": [_inner_abc_group()]},
        ModalElement,
    ),
)


class TestForkGate:
    def test_all_abc_stack_group_is_abc(self) -> None:
        assert JsonGroupDecoder.is_all_abc(_stack_group("rows").to_dict())

    def test_legacy_child_forces_legacy(self) -> None:
        wire = {
            "kind": "group",
            "children": [{"kind": "table", "id": "t", "columns": ["A"], "rows": []}],
        }
        assert not JsonGroupDecoder.is_all_abc(wire)
        assert isinstance(_decode(wire | {"id": "g"}), LegacyGroupElement)

    def test_paged_layout_stays_legacy(self) -> None:
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "paged",
            "children": [{"kind": "text", "id": "t", "content": "x"}],
        }
        assert not JsonGroupDecoder.is_all_abc(wire)
        assert isinstance(_decode(wire), LegacyGroupElement)

    def test_nonempty_paged_fields_force_legacy(self) -> None:
        # A rows-layout group carrying real paged data forks legacy so its
        # panels are not dropped by the ABC group (which has no paged fields).
        with_pages = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [],
            "pages": [[{"kind": "text", "id": "p", "content": "panel"}]],
        }
        assert not JsonGroupDecoder.is_all_abc(with_pages)
        with_source = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [],
            "page_source": "combo1",
        }
        assert not JsonGroupDecoder.is_all_abc(with_source)

    def test_empty_paged_fields_decode_abc(self) -> None:
        # Present-but-empty pages/page_source carry no panels, so nothing is
        # dropped and the group correctly decodes ABC (the truthiness gate is
        # intentional, not a falsy-key oversight).
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "children": [{"kind": "text", "id": "t", "content": "x"}],
            "pages": [],
            "page_source": "",
        }
        assert JsonGroupDecoder.is_all_abc(wire)
        assert isinstance(_decode(wire), GroupElement)

    def test_nested_all_abc_group_stays_abc(self) -> None:
        wire = {
            "kind": "group",
            "id": "outer",
            "children": [
                {
                    "kind": "group",
                    "id": "inner",
                    "children": [{"kind": "text", "id": "t", "content": "x"}],
                }
            ],
        }
        outer = _decode(wire)
        assert isinstance(outer, GroupElement)
        assert isinstance(outer.children[0], GroupElement)

    @pytest.mark.parametrize(
        ("wire", "expected"),
        [(wire, cls) for _, wire, cls in _LEGACY_CONTAINER_CASES],
        ids=[name for name, _, _ in _LEGACY_CONTAINER_CASES],
    )
    def test_all_abc_group_in_legacy_container_is_forced_legacy(
        self, wire: dict[str, Any], expected: type
    ) -> None:
        """An all-ABC group nested in any legacy container decodes legacy.

        Every legacy container kind — legacy group, tab_bar, window,
        collapsing_header, modal — must route a nested all-ABC group onto
        ``LegacyGroupElement`` (its ``child_elements()`` walk exposes it),
        never leaving an ABC container inside a legacy render subtree.
        """
        decoded = _decode(wire)
        assert isinstance(decoded, expected)
        assert isinstance(decoded, HasChildElements)
        nested = decoded.child_elements()
        assert any(isinstance(child, LegacyGroupElement) for child in nested)

    def test_deep_buried_legacy_forces_whole_tree_legacy(self) -> None:
        """A legacy leaf two groups deep forces the entire tree legacy."""
        wire = {
            "kind": "group",
            "id": "outer",
            "layout": "rows",
            "children": [
                {
                    "kind": "group",
                    "id": "inner",
                    "layout": "rows",
                    "children": [_table_wire()],
                }
            ],
        }
        assert not JsonGroupDecoder.is_all_abc(wire)
        assert isinstance(_decode(wire), LegacyGroupElement)

    def test_is_all_abc_rejects_non_mapping_child(self) -> None:
        """A non-mapping child yields False so the tree forks legacy (F6)."""
        wire = {"kind": "group", "children": ["not-a-dict"]}
        assert not JsonGroupDecoder.is_all_abc(wire)

    def test_from_dict_rejects_non_abc_subtree(self) -> None:
        """GroupElement.from_dict guards the all-ABC invariant at its boundary."""
        wire = {"kind": "group", "id": "g", "children": [_table_wire()]}
        with pytest.raises(ValueError, match="table"):
            GroupElement.from_dict(wire)

    def test_from_dict_rejects_paged_layout(self) -> None:
        """A paged layout is not a stack group — from_dict rejects it."""
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "paged",
            "children": [{"kind": "text", "id": "t", "content": "x"}],
        }
        with pytest.raises(ValueError, match="paged"):
            GroupElement.from_dict(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_group_crosses_as_pickled_entry_with_children(self) -> None:
        group = _stack_group("rows")
        wire = message_to_dict(SceneMessage(id="s1", elements=[group]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC group must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_group = restored.elements[0]
        assert isinstance(r_group, GroupElement)
        assert [c.id for c in r_group.children] == ["t1", "b1"]
        assert isinstance(r_group.children[0], TextElement)


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


def _received_scene(msg: SceneMessage) -> SceneMessage:
    restored = message_from_dict(message_to_dict(msg))
    assert isinstance(restored, SceneMessage)
    return restored


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


class TestLevel3Crossing:
    def test_rebind_recurses_into_group_children(self) -> None:
        scene = SceneMessage(id="s1", elements=[_stack_group("rows")])
        received = _received_scene(scene)
        r_group = received.elements[0]
        assert isinstance(r_group, GroupElement)
        child = r_group.children[0]

        # Read into locals so the isinstance narrowing does not stick to the
        # attribute across the rebind below.
        group_factory = r_group._renderer_factory
        child_factory = child._renderer_factory
        assert isinstance(group_factory, RaisingRendererFactory)
        assert isinstance(child_factory, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert r_group._renderer_factory is factory
        assert child._renderer_factory is factory


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_valid_stack_group_has_no_errors(self) -> None:
        assert ElementTreeValidator().validate_tree([_stack_group("rows")]).ok

    def test_group_has_no_structural_errors_of_its_own(self) -> None:
        """A rows/columns group has no self-structural constraint to check."""
        assert _stack_group("columns").validate() == ()

    def test_child_elements_returns_render_children_for_the_walk(self) -> None:
        """The inherited child_elements() bridges the walk to _children()."""
        group = _stack_group("rows")
        assert group.child_elements() == group.children

    def test_structural_guard_group_is_a_container(self) -> None:
        """The ABC group satisfies the container contract the walk relies on."""
        assert isinstance(GroupElement(id="g1"), HasChildElements)
        assert isinstance(GroupElement(id="g1"), AbcElement)


class TestTooltipRoundTrip:
    def test_tooltip_round_trips_through_abc_path(self) -> None:
        """A rows/columns group's tooltip survives encode → decode (F5)."""
        group = GroupElement(
            id="g1",
            layout="rows",
            children=(TextElement(id="t1", content="x"),),
            tooltip="hint",
        )
        restored = _decode(group.to_dict())
        assert isinstance(restored, GroupElement)
        assert restored.tooltip == "hint"

    def test_absent_tooltip_stays_absent(self) -> None:
        """A group without a tooltip omits it from the wire and decodes None."""
        wire = _stack_group("rows").to_dict()
        assert "tooltip" not in wire
        restored = _decode(wire)
        assert isinstance(restored, GroupElement)
        assert restored.tooltip is None


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_rows_group_without_raising(self) -> None:
        """A dedicated encode-path guard so the group branch cannot evaporate (F7)."""
        encoded = JsonEncoderFactory().encode(_stack_group("rows"))
        assert encoded["kind"] == "group"
        assert encoded["layout"] == "rows"
        children = cast("list[dict[str, Any]]", encoded["children"])
        assert [child["id"] for child in children] == ["t1", "b1"]


# -- Level 5: introspection (render_path recurses into children) ------------


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
    def test_group_and_children_report_abc_render_path(self) -> None:
        resp = _inspect(_server(), _stack_group("rows"))
        assert _record(resp, "g1")["render_path"] == "abc"
        # the recursion extension: the children flipped too.
        assert _record(resp, "t1")["render_path"] == "abc"
        assert _record(resp, "b1")["render_path"] == "abc"

    def test_group_resolved_props_read_back(self) -> None:
        resp = _inspect(_server(), _stack_group("columns"))
        props = _record(resp, "g1")["props"]
        assert isinstance(props, dict)
        assert props["layout"] == "columns"
        assert props["children"] == ["t1", "b1"]

    def test_mixed_group_reports_legacy_render_path(self) -> None:
        table = TableElement(id="tbl", columns=["A"], rows=[["x"]])
        legacy_group = LegacyGroupElement(id="g1", children=[table])
        resp = _inspect(_server(), legacy_group)
        assert _record(resp, "g1")["render_path"] == "legacy"


# -- scene-inspection recursion (unit) --------------------------------------


class TestSceneInspectionRecursion:
    def test_element_paths_include_nested_children(self) -> None:
        from punt_lux.scene_inspection import SceneInspection

        inspection = SceneInspection.from_scene(
            "s1", [_stack_group("rows")], mirror_ids=frozenset()
        ).to_dict()
        paths = inspection["element_paths"]
        assert isinstance(paths, list)
        ids = {r["id"] for r in paths}
        assert ids == {"g1", "t1", "b1"}
