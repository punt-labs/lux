"""Migration gate for the ABC ``tab_bar`` — an interactive tabbed container.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the all-ABC fork gate,
id-addressed reconciliation, the D21 built-in state-sync, and the
echo-suppression safety property. Levels 2, 3, and 5 drive the real Hub/Display
boundary — never a stub. The Level-4 interactive and child-forwarding round trips
live in the business-event-loop harness (``tests/e2e/scenario.py``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.server import DisplayServer
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.container_interaction import TabChanged
from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.ids import ClientId, ElementId, SceneId
from punt_lux.domain.validation_walk import ElementTreeValidator, HasChildElements
from punt_lux.protocol import SceneMessage
from punt_lux.protocol.elements import (
    ButtonElement,
    LegacyTabBarElement,
    ProgressElement,
    Tab,
    TabBarElement,
    TextElement,
)
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.encoder_factory import JsonEncoderFactory
from punt_lux.protocol.messages import message_from_dict, message_to_dict
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element


# -- builders ---------------------------------------------------------------


def _abc_tab_bar(*, active_tab: str = "tab-1") -> TabBarElement:
    """Build an all-ABC tab bar with two tabs, each holding one ABC child."""
    return TabBarElement(
        id="tb",
        tabs=(
            Tab(
                tab_id="tab-1",
                label="One",
                children=(TextElement(id="t1", content="a"),),
            ),
            Tab(
                tab_id="tab-2",
                label="Two",
                children=(ButtonElement(id="b1", label="go"),),
            ),
        ),
        active_tab=active_tab,
    )


def _decode(wire: Mapping[str, object]) -> object:
    """Decode a wire dict through the shared agent-side factory."""
    return agent_element_factory().element_from_dict(cast("dict[str, Any]", dict(wire)))


def _server() -> DisplayServer:
    raw_dir = tempfile.mkdtemp(prefix="lux-")
    return DisplayServer(socket_path=str(Path(raw_dir) / "display.sock"))


# -- Level 1: serialization roundtrip ---------------------------------------


class TestLevel1Serialization:
    def test_tab_bar_roundtrips_to_abc(self) -> None:
        restored = _decode(_abc_tab_bar().to_dict())
        assert isinstance(restored, TabBarElement)
        assert [t.tab_id for t in restored.tabs] == ["tab-1", "tab-2"]
        assert [t.label for t in restored.tabs] == ["One", "Two"]
        assert restored.active_tab == "tab-1"

    def test_flattened_children_are_abc(self) -> None:
        restored = _decode(_abc_tab_bar().to_dict())
        assert isinstance(restored, TabBarElement)
        children = restored.child_elements()
        assert [c.id for c in children] == ["t1", "b1"]
        assert isinstance(children[0], TextElement)
        assert isinstance(children[1], ButtonElement)

    def test_empty_tab_bar_roundtrips_with_empty_active(self) -> None:
        restored = _decode(TabBarElement(id="tb").to_dict())
        assert isinstance(restored, TabBarElement)
        assert restored.tabs == ()
        assert restored.active_tab == ""

    def test_wire_tab_id_synthesized_from_index_when_absent(self) -> None:
        wire = {
            "kind": "tab_bar",
            "id": "tb",
            "tabs": [
                {
                    "label": "One",
                    "children": [{"kind": "text", "id": "t", "content": "x"}],
                },
                {"label": "Two", "children": []},
            ],
        }
        restored = _decode(wire)
        assert isinstance(restored, TabBarElement)
        assert [t.tab_id for t in restored.tabs] == ["tab-0", "tab-1"]
        # The decoder seeds the active tab to the first tab's id.
        assert restored.active_tab == "tab-0"

    def test_explicit_active_tab_round_trips(self) -> None:
        restored = _decode(_abc_tab_bar(active_tab="tab-2").to_dict())
        assert isinstance(restored, TabBarElement)
        assert restored.active_tab == "tab-2"


# -- the all-ABC fork gate --------------------------------------------------


class TestForkGate:
    def test_all_abc_tab_bar_is_abc(self) -> None:
        assert ContainerAbcGate.is_all_abc(_abc_tab_bar().to_dict())

    def test_legacy_child_forces_legacy(self) -> None:
        wire = {
            "kind": "tab_bar",
            "id": "tb",
            "tabs": [
                {
                    "label": "One",
                    "children": [
                        {"kind": "table", "id": "t", "columns": ["A"], "rows": []}
                    ],
                }
            ],
        }
        assert not ContainerAbcGate.is_all_abc(wire)
        assert isinstance(_decode(wire), LegacyTabBarElement)

    def test_from_dict_rejects_non_abc_subtree(self) -> None:
        wire = {
            "kind": "tab_bar",
            "id": "tb",
            "tabs": [
                {
                    "label": "One",
                    "children": [
                        {"kind": "table", "id": "t", "columns": ["A"], "rows": []}
                    ],
                }
            ],
        }
        with pytest.raises(ValueError, match="table"):
            TabBarElement.from_dict(wire)

    def test_tab_bar_in_legacy_container_is_forced_legacy(self) -> None:
        wire = {
            "kind": "window",
            "id": "w",
            "children": [
                {"kind": "table", "id": "tbl", "columns": ["A"], "rows": []},
                _abc_tab_bar().to_dict(),
            ],
        }
        window = _decode(wire)
        assert isinstance(window, HasChildElements)
        tab_bar = window.child_elements()[1]
        assert isinstance(tab_bar, LegacyTabBarElement)


# -- self-validation (DES-039) ----------------------------------------------


class TestSelfValidation:
    def test_valid_tab_bar_has_no_errors(self) -> None:
        assert ElementTreeValidator().validate_tree([_abc_tab_bar()]).ok

    def test_empty_label_is_reported(self) -> None:
        bar = TabBarElement(
            id="tb", tabs=(Tab(tab_id="a", label="", children=()),), active_tab="a"
        )
        report = ElementTreeValidator().validate_tree([bar])
        assert not report.ok
        assert any("empty label" in e.message for e in report.errors)

    def test_duplicate_tab_ids_are_reported(self) -> None:
        bar = TabBarElement(
            id="tb",
            tabs=(
                Tab(tab_id="dup", label="One", children=()),
                Tab(tab_id="dup", label="Two", children=()),
            ),
            active_tab="dup",
        )
        report = ElementTreeValidator().validate_tree([bar])
        assert not report.ok
        assert any("duplicate tab id" in e.message for e in report.errors)

    def test_active_tab_naming_no_tab_is_reported(self) -> None:
        # Bypass __new__'s reconciliation to plant a dangling selection so the
        # validate() invariant guard has something to catch.
        bar = _abc_tab_bar()
        bar._active_tab = "ghost"
        report = ElementTreeValidator().validate_tree([bar])
        assert not report.ok
        assert any("names no tab" in e.message for e in report.errors)

    def test_nested_malformed_child_is_collected(self) -> None:
        bar = TabBarElement(
            id="tb",
            tabs=(
                Tab(
                    tab_id="a",
                    label="One",
                    children=(ProgressElement(id="p", fraction=5.0),),
                ),
            ),
            active_tab="a",
        )
        report = ElementTreeValidator().validate_tree([bar])
        assert not report.ok
        assert any(e.element_id == "p" for e in report.errors)

    def test_structural_guard_tab_bar_is_a_container(self) -> None:
        bar = TabBarElement(id="tb")
        assert isinstance(bar, HasChildElements)
        assert isinstance(bar, AbcElement)


# -- reconciliation on structural change (design §4.8) ----------------------


class TestReconciliation:
    def test_empty_tab_bar_has_empty_active(self) -> None:
        assert TabBarElement(id="tb").active_tab == ""

    def test_construction_seeds_first_tab_when_active_absent(self) -> None:
        bar = _abc_tab_bar(active_tab="")
        assert bar.active_tab == "tab-1"

    def test_added_tab_leaves_selection_unchanged(self) -> None:
        bar = TabBarElement(
            id="tb",
            tabs=(
                Tab(tab_id="a", label="A", children=()),
                Tab(tab_id="b", label="B", children=()),
            ),
            active_tab="b",
        )
        assert bar.active_tab == "b"

    def test_removed_active_tab_resets_to_first(self) -> None:
        # active_tab names a tab that is not in the set → reconcile to tabs[0].
        bar = TabBarElement(
            id="tb",
            tabs=(Tab(tab_id="a", label="A", children=()),),
            active_tab="gone",
        )
        assert bar.active_tab == "a"

    def test_relabel_keeps_selection_stable(self) -> None:
        # A relabel does not change tab_ids, so the id-addressed selection holds.
        bar = TabBarElement(
            id="tb",
            tabs=(Tab(tab_id="a", label="Renamed", children=()),),
            active_tab="a",
        )
        assert bar.active_tab == "a"


# -- Level 2: pickle scene wire ---------------------------------------------


class TestLevel2WireRoundtrip:
    def test_tab_bar_crosses_as_pickled_entry_with_children(self) -> None:
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[bar]))
        entry = wire["elements"][0]
        assert "_pickled" in entry, "ABC tab_bar must use native pickle wire"
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_bar = restored.elements[0]
        assert isinstance(r_bar, TabBarElement)
        assert [t.tab_id for t in r_bar.tabs] == ["tab-1", "tab-2"]

    def test_builtin_state_sync_handler_survives_the_wire(self) -> None:
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        wire = message_to_dict(SceneMessage(id="s1", elements=[bar]))
        restored = message_from_dict(wire)
        assert isinstance(restored, SceneMessage)
        r_bar = restored.elements[0]
        assert isinstance(r_bar, TabBarElement)
        assert r_bar.handler_count(TabChanged) == 1


# -- Level 3: Hub/Display crossing + factory rebind -------------------------


def _received(msg: SceneMessage) -> SceneMessage:
    restored = message_from_dict(message_to_dict(msg))
    assert isinstance(restored, SceneMessage)
    return restored


class TestLevel3Crossing:
    def test_rebind_recurses_into_tab_children(self) -> None:
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        received = _received(SceneMessage(id="s1", elements=[bar]))
        r_bar = received.elements[0]
        assert isinstance(r_bar, TabBarElement)
        child = r_bar.child_elements()[0]
        # Read into locals so the isinstance narrowing does not stick to the
        # attribute across the rebind below.
        bar_factory = r_bar._renderer_factory
        child_factory = child._renderer_factory
        assert isinstance(bar_factory, RaisingRendererFactory)
        assert isinstance(child_factory, RaisingRendererFactory)

        server = _server()
        server._wrap_abc_elements(received)

        factory = server._imgui_renderer_factory
        assert isinstance(factory, ImGuiRendererFactory)
        assert r_bar._renderer_factory is factory
        assert child._renderer_factory is factory


# -- D21 built-in state-sync + echo-suppression -----------------------------


class TestInteraction:
    def test_builtin_handler_syncs_active_tab_on_the_hub_copy(self) -> None:
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        bar.fire(
            TabChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("tb"),
                owner_id=ClientId("c"),
                tab_id="tab-2",
            )
        )
        assert bar.active_tab == "tab-2"

    def test_hub_driven_change_does_not_refire(self) -> None:
        # ECHO-SUPPRESSION: a Hub-set active_tab (a re-push's new state) must NOT
        # emit a RemoteEventHandlerInvocation, or a fire -> Hub -> re-push -> fire
        # loop would run. A user switch DOES emit exactly one.
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        sent: list[RemoteEventHandlerInvocation] = []
        bar.wrap_handlers_for_remote(sent.append)

        bar.apply_patch({"active_tab": "tab-2"})
        assert sent == [], "a Hub-set active_tab must not fire an interaction"

        bar.fire(
            TabChanged(
                scene_id=SceneId("s"),
                element_id=ElementId("tb"),
                owner_id=ClientId("c"),
                tab_id="tab-2",
            )
        )
        assert len(sent) == 1
        assert sent[0].event_kind == "tab_changed"
        assert sent[0].value == "tab-2"

    def test_renderer_honours_hub_value_without_firing(self) -> None:
        # The renderer's fire decision is the source of echo-suppression: a
        # reported selection equal to the active tab, or a frame that just
        # honoured a fresh Hub value (active != last), is no user switch.
        bar = _abc_tab_bar()
        factory = _server()._imgui_renderer_factory
        renderer = ImGuiTabBarRenderer(bar, factory)
        # honoured value / no change → no fire
        assert not renderer._is_user_switch(
            selected=True, tab_id="tab-1", active="tab-1", last="tab-1"
        )
        # fresh Hub write echo (active moved since last frame) → no fire
        assert not renderer._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-2", last="tab-1"
        )
        # genuine user switch → fire
        assert renderer._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-1", last="tab-1"
        )


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
    def test_tab_bar_and_children_report_abc_render_path(self) -> None:
        bar = _decode(_abc_tab_bar().to_dict())
        assert isinstance(bar, TabBarElement)
        resp = _inspect(_server(), bar)
        assert _record(resp, "tb")["render_path"] == "abc"
        assert _record(resp, "t1")["render_path"] == "abc"
        assert _record(resp, "b1")["render_path"] == "abc"

    def test_resolved_props_reports_active_tab_and_tabs(self) -> None:
        bar = _decode(_abc_tab_bar(active_tab="tab-2").to_dict())
        assert isinstance(bar, TabBarElement)
        resp = _inspect(_server(), bar)
        props = _record(resp, "tb")["props"]
        assert isinstance(props, dict)
        assert props["active_tab"] == "tab-2"
        tabs = props["tabs"]
        assert isinstance(tabs, list)
        assert [t["tab_id"] for t in tabs] == ["tab-1", "tab-2"]

    def test_legacy_tab_bar_reports_legacy_render_path(self) -> None:
        legacy = LegacyTabBarElement(
            id="tb",
            tabs=[{"label": "One", "children": [TextElement(id="t1", content="x")]}],
        )
        resp = _inspect(_server(), legacy)
        assert _record(resp, "tb")["render_path"] == "legacy"


class TestEncoderFactoryGuard:
    def test_encoder_factory_encodes_tab_bar_without_raising(self) -> None:
        encoded = JsonEncoderFactory().encode(_abc_tab_bar())
        assert encoded["kind"] == "tab_bar"
        assert encoded["active_tab"] == "tab-1"
        tabs = cast("list[dict[str, Any]]", encoded["tabs"])
        assert [t["id"] for t in tabs] == ["tab-1", "tab-2"]
