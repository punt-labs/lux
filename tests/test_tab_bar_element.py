"""Migration gate for the ABC ``tab_bar`` — an interactive tabbed container.

Levels 1-5 per ``tests/CLAUDE.md`` plus self-validation, the all-ABC fork gate,
id-addressed reconciliation, the built-in state-sync, and the echo-suppression
safety property. Levels 2, 3, and 5 drive the real Hub/Display boundary — never
a stub. The Level-4 interactive and child-forwarding round trips live in the
business-event-loop harness (``tests/e2e/scenario.py``).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.tab_bar import ImGuiTabBarRenderer
from punt_lux.display.renderers.imgui.tab_selection import (
    _UNHONOURED,
    TabSelectionArbiter,
)
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
from punt_lux.scene import SceneManager, WidgetState
from punt_lux.tools import show

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol import QueryResponse
    from punt_lux.protocol.elements import Element

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"


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


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _honoured_key(element_id: str = "tb") -> str:
    """Return the WidgetState key holding a tab bar's last-honoured active tab."""
    return f"{element_id}{WidgetState.HONOURED_SUFFIX}"


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

    def test_wire_tab_id_synthesized_from_label_when_absent(self) -> None:
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
        # The synthesized key is a content slug of the label, never a position.
        assert [t.tab_id for t in restored.tabs] == ["one", "two"]
        # The decoder seeds the active tab to the first tab's id.
        assert restored.active_tab == "one"

    def test_duplicate_labels_get_suffixed_slugs(self) -> None:
        wire = {
            "kind": "tab_bar",
            "id": "tb",
            "tabs": [
                {"label": "Log", "children": []},
                {"label": "Log", "children": []},
                {"label": "Log", "children": []},
            ],
        }
        restored = _decode(wire)
        assert isinstance(restored, TabBarElement)
        # A repeated label keeps ids unique with a numeric suffix.
        assert [t.tab_id for t in restored.tabs] == ["log", "log-2", "log-3"]

    def test_empty_label_slug_falls_back_to_tab(self) -> None:
        wire = {"kind": "tab_bar", "id": "tb", "tabs": [{"label": "", "children": []}]}
        restored = _decode(wire)
        assert isinstance(restored, TabBarElement)
        assert [t.tab_id for t in restored.tabs] == ["tab"]

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


# -- malformed-wire rejection (reject, do not silently empty) ----------------


class TestMalformedWireRejected:
    def test_non_list_tabs_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            TabBarElement.from_dict(
                {"kind": "tab_bar", "id": "tb", "tabs": {"not": "a list"}}
            )

    def test_non_list_tab_children_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be a list"):
            TabBarElement.from_dict(
                {
                    "kind": "tab_bar",
                    "id": "tb",
                    "tabs": [{"id": "a", "label": "One", "children": {"x": 1}}],
                }
            )


# -- self-validation --------------------------------------------------------


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


class TestShowRejectsInvalidTabBar:
    @patch(_CLIENT_GET)
    def test_show_rejects_empty_tab_label(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "tab_bar",
                    "id": "tb",
                    "active_tab": "a",
                    "tabs": [{"id": "a", "label": "", "children": []}],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[tab_bar 'tb']" in result
        assert "empty label" in result
        client.show.assert_not_called()

    @patch(_CLIENT_GET)
    def test_show_rejects_progress_nested_in_tab(self, mock_get: MagicMock) -> None:
        """A bad progress nested in a tab's children is collected by the walk."""
        client = _mock_client()
        mock_get.return_value = client
        result = show(
            "s1",
            [
                {
                    "kind": "tab_bar",
                    "id": "tb",
                    "active_tab": "a",
                    "tabs": [
                        {
                            "id": "a",
                            "label": "One",
                            "children": [
                                {"kind": "text", "id": "ok", "content": "fine"},
                                {"kind": "progress", "id": "bad", "fraction": -0.5},
                            ],
                        }
                    ],
                }
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[progress 'bad']" in result
        client.show.assert_not_called()


# -- reconciliation on structural change ------------------------------------


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

    def test_apply_patch_reconciles_a_dangling_active_tab(self) -> None:
        # The reconciliation invariant holds on EVERY mutation, not only at
        # construction: a patch naming a tab the set does not hold (a stale
        # click after the tabs changed) resets to the first live tab rather than
        # installing a dangling selection that would fire a spurious TabChanged.
        bar = _abc_tab_bar()
        bar.apply_patch({"active_tab": "ghost-not-a-tab"})
        assert bar.active_tab == "tab-1"
        # The module docstring's "maintained on every mutation" claim is now true.
        assert not ElementTreeValidator().validate_tree([bar]).errors

    def test_apply_patch_to_empty_tab_bar_clears_selection(self) -> None:
        bar = TabBarElement(id="tb")
        bar.apply_patch({"active_tab": "ghost"})
        assert bar.active_tab == ""


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


# -- built-in state-sync + echo-suppression ---------------------------------


class TestInteraction:
    """The fire decision, proven at the pure-function level via the arbiter.

    ``begin_tab``/``end`` cannot run headless: ``imgui.begin_tab_item`` requires a
    live ImGui frame inside an OpenGL context, which the unit tier has no window
    for. So the echo-suppression guarantee — a Hub-driven ``active_tab`` change or
    a first-frame honour never fires, only a genuine user switch does — is proven
    through ``TabSelectionArbiter``, the pure fire/honour decision the renderer
    delegates to, not through a driven ``end()``-then-``begin_tab()`` sequence. The
    full interactive leg (a real click firing across the socket) is the
    business-event-loop harness's job (``tests/e2e/scenario.py``).
    """

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

    def test_arbiter_honours_hub_value_without_firing(self) -> None:
        # The arbiter's fire decision is the source of echo-suppression: a
        # reported selection equal to the active tab, or a frame that just
        # honoured a fresh Hub value (active != honoured), is no user switch.
        def arbiter(honoured: str) -> TabSelectionArbiter:
            ws = WidgetState()
            ws.set(_honoured_key(), honoured)
            return TabSelectionArbiter(ws, "tb")

        # honoured value / no change → no fire
        assert not arbiter("tab-1")._is_user_switch(
            selected=True, tab_id="tab-1", active="tab-1"
        )
        # fresh Hub write echo (active moved since last frame) → no fire
        assert not arbiter("tab-1")._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-2"
        )
        # genuine user switch → fire
        assert arbiter("tab-1")._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-1"
        )

    def test_renderer_end_records_the_honoured_active_tab(self) -> None:
        # end() is headless when the surface did not open (no ImGui call); it must
        # still record the Hub active tab so the next frame reads it as honoured
        # and cannot mistake the echo for a user switch.
        bar = _abc_tab_bar(active_tab="tab-2")
        factory = _server()._imgui_renderer_factory
        renderer = ImGuiTabBarRenderer(bar, factory)
        renderer.end(opened=False)
        assert factory.widget_state.get(_honoured_key()) == "tab-2"

    def test_pending_window_fires_exactly_once(self) -> None:
        # NO REPEATED FIRE: through the click-to-re-push latency window ImGui
        # keeps reporting the clicked tab while the Hub active tab has not yet
        # moved. ``should_fire`` fires on the first such frame and records the tab
        # pending; every later frame in the window sees it pending and stays
        # silent, so the window fires exactly once. Under the old code (no
        # pending slot) each frame re-fired — the guard's ``active == honoured``
        # held every frame. Drives the real ``WidgetState``, not a stub.
        ws = WidgetState()
        # A prior frame honoured the Hub active tab.
        ws.set(_honoured_key(), "tab-1")
        arbiter = TabSelectionArbiter(ws, "tb")
        # Frame of the click: ImGui reports tab-2, Hub still on tab-1 → fire once.
        assert arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")
        # Same window, Hub not caught up, ImGui still on tab-2 → no re-fire.
        assert not arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")
        assert not arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")

    def test_repush_reset_reopens_firing_after_the_window(self) -> None:
        # The pending slot must not gag a genuine switch once the window closes.
        # After a fire records tab-2 pending, the re-push reset clears the slot
        # (reset_honoured / discard_for), so a later switch fires again.
        ws = WidgetState()
        ws.set(_honoured_key(), "tab-1")
        arbiter = TabSelectionArbiter(ws, "tb")
        assert arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")
        assert not arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")
        # The re-push resets both session slots.
        ws.reset_honoured()
        ws.set(_honoured_key(), "tab-1")
        # A genuine switch to tab-2 now fires again — the slot no longer gags it.
        assert arbiter.should_fire(selected=True, tab_id="tab-2", active="tab-1")

    def test_first_frame_force_selects_declared_active_without_firing(self) -> None:
        # The Level-4 scenarios inject via fire and bypass begin_tab; this
        # covers the first-frame decision directly. With no value yet honoured,
        # the slot defaults to _UNHONOURED, so a non-first declared active_tab is
        # force-selected AND does not fire — ImGui's own tab-0 default can never
        # clobber the declared selection with a bogus event.
        ws = WidgetState()
        assert ws.get(_honoured_key(), _UNHONOURED) is _UNHONOURED
        arbiter = TabSelectionArbiter(ws, "tb")
        # frame 1: the declared active tab (tab-2, not tab 0) is force-selected
        assert arbiter.should_force_select("tab-2", "tab-2")
        # frame 1: ImGui reporting tab-1 selected before SetSelected must NOT fire
        assert not arbiter._is_user_switch(
            selected=True, tab_id="tab-1", active="tab-2"
        )
        # frame 1: the force-selected active tab itself must NOT fire
        assert not arbiter._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-2"
        )
        # a genuine later user switch (after honouring) DOES fire
        ws.set(_honoured_key(), "tab-2")
        assert arbiter._is_user_switch(selected=True, tab_id="tab-1", active="tab-2")


class TestEchoSuppressionLifecycle:
    """The honoured key resets on re-push and removal — no spurious TabChanged.

    These drive the real ``SceneManager`` re-push path and the display's
    per-scene factory re-thread, so a stale honoured value cannot survive into a
    frame where a leftover ImGui selection would masquerade as a user switch.
    """

    def _install(
        self, server: DisplayServer, *, active_tab: str = "tab-1"
    ) -> tuple[SceneManager, ImGuiRendererFactory]:
        """Install a tab bar and re-thread the factory as the display would."""
        bar = _abc_tab_bar(active_tab=active_tab)
        sm = server._scene_manager
        sm.handle_scene(SceneMessage(id="s1", elements=[bar]), owner_fd=0)
        ws = sm.widget_state_for("s1")
        assert ws is not None
        factory = server._imgui_renderer_factory
        factory.widget_state = ws
        return sm, factory

    def test_whole_scene_repush_resets_honoured_no_spurious_fire(self) -> None:
        sm, factory = self._install(_server())
        # Render session 1 honoured the Hub active tab.
        factory.widget_state.set(_honoured_key(), "tab-1")
        # A whole-scene re-push of the same surviving tab bar.
        sm.handle_scene(
            SceneMessage(id="s1", elements=[_abc_tab_bar(active_tab="tab-1")]),
            owner_fd=0,
        )
        repushed = sm.widget_state_for("s1")
        assert repushed is not None
        factory.widget_state = repushed
        assert factory.widget_state.get(_honoured_key(), _UNHONOURED) is _UNHONOURED
        arbiter = TabSelectionArbiter(factory.widget_state, "tb")
        # First post-re-push frame re-honours tab-1; a stale tab-2 selection
        # reported by ImGui is the echo, not a user switch, and must not fire.
        assert arbiter.should_force_select("tab-1", "tab-1")
        assert not arbiter._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-1"
        )

    def test_remove_then_readd_same_id_resets_honoured(self) -> None:
        # Integration coverage of the removal + re-add lifecycle: a re-push that
        # drops the tab bar clears its honoured value, so a re-added same-id bar
        # starts fresh. This does NOT isolate ``discard_for`` — the removal runs
        # through ``_replace_scene_state``, where both ``discard_for(stale)`` and
        # ``reset_honoured()`` clear the honoured key, so either alone would pass
        # it. ``discard_for``'s own honoured-clearing is isolated by the
        # WidgetState unit test in test_scene_manager.py.
        sm, factory = self._install(_server())
        factory.widget_state.set(_honoured_key(), "tab-1")
        # Re-push without the tab bar → it is removed.
        sm.handle_scene(
            SceneMessage(id="s1", elements=[TextElement(id="only", content="x")]),
            owner_fd=0,
        )
        removed = sm.widget_state_for("s1")
        assert removed is not None
        assert removed.get(_honoured_key(), _UNHONOURED) is _UNHONOURED
        # Re-add the same-id tab bar: it starts fresh, no stale honoured value.
        sm.handle_scene(
            SceneMessage(id="s1", elements=[_abc_tab_bar(active_tab="tab-1")]),
            owner_fd=0,
        )
        readded = sm.widget_state_for("s1")
        assert readded is not None
        factory.widget_state = readded
        assert factory.widget_state.get(_honoured_key(), _UNHONOURED) is _UNHONOURED
        arbiter = TabSelectionArbiter(factory.widget_state, "tb")
        assert not arbiter._is_user_switch(
            selected=True, tab_id="tab-2", active="tab-1"
        )

    def test_element_renderer_setter_rethreads_the_factory(self) -> None:
        # Production wiring: the display sets the ElementRenderer's widget_state
        # per scene; that re-thread must reach the ABC factory the tab bar paints
        # through, or the honoured reset never touches the value it reads.
        server = _server()
        fresh = WidgetState()
        server._element_renderer.widget_state = fresh
        assert server._imgui_renderer_factory.widget_state is fresh

    def test_reset_does_not_over_suppress_a_genuine_switch(self) -> None:
        # Complement to the no-spurious-fire tests: the honoured reset must not
        # gag genuine switches. This drives the real re-push reset path, then —
        # once the new session has re-honoured tab-1 — a user switch to tab-2
        # (Hub active unchanged) still fires. It passes under the old code too,
        # by design: the reset touches the honoured *bookkeeping*, never the
        # ``_is_user_switch`` fire decision, so this guards against a future
        # over-suppression regression rather than pinning the reset itself (the
        # no-spurious-fire tests above do that, failing under the old code).
        sm, factory = self._install(_server())
        factory.widget_state.set(_honoured_key(), "tab-1")
        sm.handle_scene(
            SceneMessage(id="s1", elements=[_abc_tab_bar(active_tab="tab-1")]),
            owner_fd=0,
        )
        repushed = sm.widget_state_for("s1")
        assert repushed is not None
        factory.widget_state = repushed
        assert factory.widget_state.get(_honoured_key(), _UNHONOURED) is _UNHONOURED
        # The next frame re-honours tab-1; a later genuine user switch fires.
        factory.widget_state.set(_honoured_key(), "tab-1")
        arbiter = TabSelectionArbiter(factory.widget_state, "tb")
        assert arbiter._is_user_switch(selected=True, tab_id="tab-2", active="tab-1")


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
