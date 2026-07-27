"""Migration gate for the ABC ``group`` container (rows / columns).

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation and the all-ABC
fork gate. Levels 3 and 5 drive the real Hub/Display boundary — the pickle
scene wire and the ``DisplayServer`` receive/rebind path — never a stub.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.group import ImGuiGroupRenderer
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    GroupElement,
    TextElement,
)
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.renderer import ColumnsRenderer, Renderer
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


# -- the group's paged rejection --------------------------------------------


class TestPagedRejection:
    """The removed ``paged`` layout is rejected at the decode boundary.

    A group renders only ``rows`` or ``columns``; the decoder rejects any
    other layout and the removed ``pages`` / ``page_source`` wire fields with
    a named error, on both the tier-factory and standalone ``from_dict`` paths.
    """

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

    def test_from_dict_rejects_paged_layout(self) -> None:
        """A paged layout is not a stack group — from_dict rejects it by name."""
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "paged",
            "children": [{"kind": "text", "id": "t", "content": "x"}],
        }
        with pytest.raises(ValueError, match="unknown layout 'paged'"):
            GroupElement.from_dict(wire)

    def test_factory_rejects_paged_layout(self) -> None:
        """The tier factory rejects a paged group, never silently coercing it."""
        wire = {"kind": "group", "id": "g", "layout": "paged", "children": []}
        with pytest.raises(ValueError, match="'paged' layout was removed"):
            _decode(wire)

    def test_factory_rejects_nested_paged_group(self) -> None:
        """A paged group nested inside a stack group is rejected too."""
        wire = {
            "kind": "group",
            "id": "outer",
            "children": [{"kind": "group", "id": "inner", "layout": "paged"}],
        }
        with pytest.raises(ValueError, match="'paged' layout was removed"):
            _decode(wire)

    def test_rejects_pages_wire_field(self) -> None:
        """The removed ``pages`` wire field is rejected on a stack group."""
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "pages": [[{"kind": "text", "id": "p", "content": "x"}]],
        }
        with pytest.raises(ValueError, match="'pages' is no longer supported"):
            _decode(wire)

    def test_rejects_page_source_wire_field(self) -> None:
        """The removed ``page_source`` wire field is rejected on a stack group."""
        wire = {
            "kind": "group",
            "id": "g",
            "layout": "rows",
            "page_source": "combo1",
        }
        with pytest.raises(ValueError, match="'page_source' is no longer supported"):
            _decode(wire)

    def test_rejects_empty_pages_wire_field(self) -> None:
        """An empty ``pages`` list is rejected on PRESENCE, not truthiness."""
        wire = {"kind": "group", "id": "g", "layout": "rows", "pages": []}
        with pytest.raises(ValueError, match="'pages' is no longer supported"):
            _decode(wire)

    def test_rejects_empty_page_source_wire_field(self) -> None:
        """An empty ``page_source`` string is rejected on PRESENCE, not truthiness."""
        wire = {"kind": "group", "id": "g", "layout": "rows", "page_source": ""}
        with pytest.raises(ValueError, match="'page_source' is no longer supported"):
            _decode(wire)


# -- child-decode boundary --------------------------------------------------


class TestChildDecodeBoundary:
    """A malformed child names its parent container and slot, never AttributeErrors.

    Every wire-shape failure inside a container's children — a non-mapping child
    or a wrong-typed shape a decoder rejects with ``TypeError`` — is caught at the
    child-decode boundary and re-raised naming the parent kind, id, and index.
    """

    def test_non_mapping_child_names_parent_and_index(self) -> None:
        # A bare ``42`` where an element belongs must not reach ``d.get`` and
        # escape as an AttributeError — it becomes a named, parent-prefixed
        # TypeError (a non-mapping is a wire-shape error, not a bad value).
        wire = {"kind": "group", "id": "g1", "children": [42]}
        with pytest.raises(TypeError, match=r"group 'g1' child 0:.*mapping"):
            _decode(wire)

    def test_type_error_child_shape_is_parent_prefixed(self) -> None:
        # The nested window rejects a non-list ``children`` with a TypeError; the
        # enclosing group prefixes it with its own kind, id, and the slot, and the
        # shape distinction survives as a TypeError.
        wire = {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "window", "id": "w1", "children": 5}],
        }
        with pytest.raises(TypeError, match=r"group 'g1' child 0:.*must be a list"):
            _decode(wire)

    def test_group_present_non_list_children_fails_loud(self) -> None:
        # A present non-list ``children`` on a group must fail loud like the other
        # containers, not silently drop the subtree by decoding to an empty group.
        wire = {"kind": "group", "id": "g1", "children": 5}
        with pytest.raises(TypeError, match="group children must be a list"):
            _decode(wire)


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_group_crosses_as_pickled_entry_with_children(self) -> None:
        group = _stack_group("rows")
        wire = message_to_dict(SceneMessage(id="s1", elements=[group], frame_id="s1"))
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
        scene = SceneMessage(id="s1", elements=[_stack_group("rows")], frame_id="s1")
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


# -- columns block painting (unit) ------------------------------------------


class _Recorder:
    """Shared ordered event log for the columns-painter drive tests."""

    events: list[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.events = []
        return self


class _RecordingChildRenderer:
    """A child ``Renderer`` that logs its element id when the skeleton renders it."""

    _id: str
    _rec: _Recorder

    def __new__(cls, elem: Element, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._id = elem.id
        self._rec = rec
        return self

    def begin(self) -> bool:
        self._rec.events.append(f"render:{self._id}")
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...


class _RecordingFactory:
    """A ``RendererFactory`` binding each child to a ``_RecordingChildRenderer``."""

    _rec: _Recorder

    def __new__(cls, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._rec = rec
        return self

    def __call__(self, elem: object) -> Renderer:
        return _RecordingChildRenderer(cast("Element", elem), self._rec)


class _SpyColumnsRenderer:
    """A ``ColumnsRenderer`` that logs each child-block bracket in order."""

    _rec: _Recorder

    def __new__(cls, rec: _Recorder) -> Self:
        self = super().__new__(cls)
        self._rec = rec
        return self

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...

    def begin_child_block(self, *, first: bool) -> None:
        self._rec.events.append(f"begin_block(first={first})")

    def end_child_block(self) -> None:
        self._rec.events.append("end_block")


class _PlainGroupRenderer:
    """A base ``Renderer`` with no columns block surface — not a ColumnsRenderer."""

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...


class _Layout:
    """A minimal columns layout model: columns left-to-right, items top-to-bottom.

    Faithful to the fix's structure, deliberately simpler than ImGui: a per-child
    block advances the column origin (``same_line`` past the previous column) and
    resets to the row top, and items painted inside a block advance ``y``. Enough
    to assert the two geometry invariants the defect broke — disjoint increasing
    ``x`` across children and increasing ``y`` within one child.
    """

    _col_x: float
    _col_w: float
    _y: float
    rects: dict[str, list[tuple[float, float, float, float]]]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._col_x = 0.0
        self._col_w = 0.0
        self._y = 0.0
        self.rects = {}
        return self

    def next_column(self, *, first: bool) -> None:
        """Open a column: after the first, ``same_line`` past the previous one."""
        if not first:
            self._col_x += self._col_w
        self._col_w = 0.0
        self._y = 0.0

    def paint_item(self, elem_id: str, size: tuple[float, float]) -> None:
        """Record one item at the cursor and advance ``y`` (vertical flow)."""
        width, height = size
        self.rects.setdefault(elem_id, []).append((self._col_x, self._y, width, height))
        self._y += height
        self._col_w = max(self._col_w, width)


class _LayoutColumnsRenderer:
    """A ``ColumnsRenderer`` that drives ``_Layout`` — one column per child block."""

    _layout: _Layout

    def __new__(cls, layout: _Layout) -> Self:
        self = super().__new__(cls)
        self._layout = layout
        return self

    def begin(self) -> bool:
        return True

    def paint(self) -> None: ...

    def end(self, *, opened: bool) -> None: ...

    def begin_child_block(self, *, first: bool) -> None:
        self._layout.next_column(first=first)

    def end_child_block(self) -> None: ...


class _LayoutChildRenderer:
    """A child ``Renderer`` painting its element's items with known sizes."""

    _id: str
    _layout: _Layout
    _sizes: Mapping[str, list[tuple[float, float]]]

    def __new__(
        cls,
        elem: Element,
        layout: _Layout,
        sizes: Mapping[str, list[tuple[float, float]]],
    ) -> Self:
        self = super().__new__(cls)
        self._id = elem.id
        self._layout = layout
        self._sizes = sizes
        return self

    def begin(self) -> bool:
        return True

    def paint(self) -> None:
        for size in self._sizes[self._id]:
            self._layout.paint_item(self._id, size)

    def end(self, *, opened: bool) -> None: ...


class _LayoutFactory:
    """A ``RendererFactory`` binding each child to a ``_LayoutChildRenderer``."""

    _layout: _Layout
    _sizes: Mapping[str, list[tuple[float, float]]]

    def __new__(
        cls, layout: _Layout, sizes: Mapping[str, list[tuple[float, float]]]
    ) -> Self:
        self = super().__new__(cls)
        self._layout = layout
        self._sizes = sizes
        return self

    def __call__(self, elem: object) -> Renderer:
        return _LayoutChildRenderer(cast("Element", elem), self._layout, self._sizes)


class TestColumnsBlockPainting:
    """The columns painter brackets each child in its own vertical block.

    Regression for the horizontal-stack defect: an expandable child in a
    columns group spread its content along one row. Each child must render
    inside its own ``begin_group``/``end_group`` block so it grows DOWN.
    """

    def test_columns_brackets_each_child_in_its_own_block(self) -> None:
        rec = _Recorder()
        group = _stack_group("columns")
        group.bind_renderer_factory(_RecordingFactory(rec))
        group._render_children(_SpyColumnsRenderer(rec))
        assert rec.events == [
            "begin_block(first=True)",
            "render:t1",
            "end_block",
            "begin_block(first=False)",
            "render:b1",
            "end_block",
        ]

    def test_columns_place_children_in_disjoint_increasing_x_columns(self) -> None:
        # ``t1`` stands in for a multi-item child (a tree's label + two nodes);
        # ``b1`` for a single-item child. The defect flowed a multi-item child's
        # items along the row, so the collapsed tree's nodes landed at INCREASING
        # x and the next column overlapped them. Assert the fixed geometry.
        sizes: dict[str, list[tuple[float, float]]] = {
            "t1": [(10.0, 5.0), (10.0, 5.0), (10.0, 5.0)],
            "b1": [(20.0, 5.0)],
        }
        layout = _Layout()
        group = _stack_group("columns")
        group.bind_renderer_factory(_LayoutFactory(layout, sizes))
        group._render_children(_LayoutColumnsRenderer(layout))

        t1 = layout.rects["t1"]
        b1 = layout.rects["b1"]
        # The multi-item child's items grow DOWN one column: one x, increasing y.
        assert {x for x, _y, _w, _h in t1} == {0.0}
        assert [y for _x, y, _w, _h in t1] == [0.0, 5.0, 10.0]
        # The second child is a disjoint column to the RIGHT, back at the row top —
        # not chained below the first, not overlapping its x-range.
        t1_right = max(x + w for x, _y, w, _h in t1)
        assert b1[0][0] >= t1_right
        assert b1[0][1] == 0.0

    def test_columns_requires_a_columns_renderer(self) -> None:
        group = _stack_group("columns")
        # Premise: the plain renderer is a valid base Renderer lacking only the
        # columns block surface, so the rejection is about the missing surface.
        assert isinstance(_PlainGroupRenderer(), Renderer)
        with pytest.raises(TypeError, match="ColumnsRenderer"):
            group._render_children(_PlainGroupRenderer())

    def test_rows_use_default_recursion_without_block_brackets(self) -> None:
        rec = _Recorder()
        group = _stack_group("rows")
        group.bind_renderer_factory(_RecordingFactory(rec))
        # Rows never require the columns surface: a plain Renderer is accepted
        # and no per-child block bracket is emitted.
        group._render_children(_PlainGroupRenderer())
        assert rec.events == ["render:t1", "render:b1"]

    def test_imgui_group_renderer_satisfies_columns_protocol(self) -> None:
        # The renderer the display actually builds must satisfy the gate the
        # group enforces for columns.
        factory = _server()._imgui_renderer_factory
        renderer = ImGuiGroupRenderer(_stack_group("columns"), factory)
        assert isinstance(renderer, ColumnsRenderer)
