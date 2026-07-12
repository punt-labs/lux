"""Regression gate for tree-level element-id uniqueness.

Id uniqueness is a tree-level invariant: a named id may not repeat across a
submitted scene tree, whether the repeat is two roots sharing an id or a
root id reused by a buried child. ``DuplicateIdScanner`` is the Hub's
pre-install gate; ``show()`` rejects a colliding tree before any install so
the Hub never holds a partial or self-colliding tree — mirroring the
Display's element-by-element ``DuplicateIdError`` for full Hub/Display
symmetry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from punt_lux.domain.error import DuplicateIdError
from punt_lux.domain.hub import hub_display
from punt_lux.domain.id_uniqueness import DuplicateIdScanner
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.protocol.elements import (
    CollapsingHeaderElement,
    GroupElement,
    LegacyGroupElement,
    LegacyTabBarElement,
    SeparatorElement,
    Tab,
    TabBarElement,
    TextElement,
)
from punt_lux.tools import show

_CLIENT_GET = "punt_lux.domain.hub.clients.client_registry.get"
_SCENE = SceneId("id-uniqueness-scene")


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


# -- DuplicateIdScanner unit ------------------------------------------------


class TestDuplicateIdScanner:
    def test_unique_tree_has_no_duplicate(self) -> None:
        roots = [
            TextElement(id="a", content="one"),
            GroupElement(
                id="g", layout="rows", children=(TextElement(id="b", content="two"),)
            ),
        ]
        assert DuplicateIdScanner().first_duplicate(_SCENE, roots) is None

    def test_two_roots_sharing_an_id_are_caught(self) -> None:
        roots = [
            TextElement(id="x", content="one"),
            TextElement(id="x", content="two"),
        ]
        found = DuplicateIdScanner().first_duplicate(_SCENE, roots)
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("x"))

    def test_root_id_reused_by_buried_child_is_caught(self) -> None:
        roots = [
            TextElement(id="dup", content="root"),
            GroupElement(
                id="g",
                layout="rows",
                children=(TextElement(id="dup", content="child"),),
            ),
        ]
        found = DuplicateIdScanner().first_duplicate(_SCENE, roots)
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_child_id_reused_across_two_containers_is_caught(self) -> None:
        roots = [
            GroupElement(
                id="g1", layout="rows", children=(TextElement(id="c", content="a"),)
            ),
            GroupElement(
                id="g2", layout="rows", children=(TextElement(id="c", content="b"),)
            ),
        ]
        found = DuplicateIdScanner().first_duplicate(_SCENE, roots)
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("c"))

    def test_anonymous_ids_may_repeat(self) -> None:
        roots = [
            SeparatorElement(),
            TextElement(id="a", content="one"),
            SeparatorElement(),
        ]
        assert DuplicateIdScanner().first_duplicate(_SCENE, roots) is None

    def test_duplicate_buried_in_abc_tab_bar_tab_is_caught(self) -> None:
        bar = TabBarElement(
            id="tb",
            tabs=[
                Tab("t1", "One", (TextElement(id="dup", content="a"),)),
                Tab("t2", "Two", (TextElement(id="dup", content="b"),)),
            ],
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [bar])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_duplicate_buried_in_legacy_tab_bar_tab_is_caught(self) -> None:
        bar = LegacyTabBarElement(
            id="ltb",
            tabs=[
                {"label": "One", "children": [TextElement(id="dup", content="a")]},
                {"label": "Two", "children": [TextElement(id="dup", content="b")]},
            ],
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [bar])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_duplicate_in_legacy_group_page_is_caught(self) -> None:
        group = LegacyGroupElement(
            id="lg",
            layout="paged",
            children=[TextElement(id="dup", content="nav")],
            pages=[[TextElement(id="dup", content="page")]],
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [group])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_duplicate_in_collapsing_header_is_caught(self) -> None:
        header = CollapsingHeaderElement(
            id="ch",
            label="Section",
            children=(
                TextElement(id="dup", content="a"),
                TextElement(id="dup", content="b"),
            ),
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [header])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_duplicate_across_two_nesting_levels_is_caught(self) -> None:
        inner = GroupElement(id="inner", children=(TextElement(id="dup", content="a"),))
        outer = GroupElement(
            id="outer",
            children=(inner, TextElement(id="dup", content="b")),
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [outer])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_anonymous_separators_repeat_inside_a_container(self) -> None:
        group = LegacyGroupElement(
            id="g", children=[SeparatorElement(), SeparatorElement()]
        )
        assert DuplicateIdScanner().first_duplicate(_SCENE, [group]) is None

    def test_named_duplicate_caught_amid_anonymous_repeats(self) -> None:
        group = LegacyGroupElement(
            id="g",
            children=[
                SeparatorElement(),
                TextElement(id="dup", content="a"),
                SeparatorElement(),
                TextElement(id="dup", content="b"),
            ],
        )
        found = DuplicateIdScanner().first_duplicate(_SCENE, [group])
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("dup"))

    def test_first_duplicate_in_install_order_wins(self) -> None:
        roots = [
            TextElement(id="a", content="1"),
            TextElement(id="b", content="2"),
            TextElement(id="a", content="3"),
            TextElement(id="b", content="4"),
        ]
        found = DuplicateIdScanner().first_duplicate(_SCENE, roots)
        assert found == DuplicateIdError(scene_id=_SCENE, element_id=ElementId("a"))


# -- show() refuses to render a colliding tree ------------------------------


class TestShowRejectsDuplicateIds:
    @patch(_CLIENT_GET)
    def test_show_rejects_root_id_reused_as_child(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        scene = "dup-root-child"
        result = show(
            scene,
            [
                {"kind": "text", "id": "dup", "content": "root"},
                {
                    "kind": "group",
                    "id": "g",
                    "layout": "rows",
                    "children": [{"kind": "text", "id": "dup", "content": "child"}],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "duplicate element id 'dup'" in result
        assert "unique" in result
        client.show.assert_not_called()
        assert hub_display.scene_roots(SceneId(scene)) == []

    @patch(_CLIENT_GET)
    def test_show_rejects_two_roots_sharing_an_id(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        scene = "dup-two-roots"
        result = show(
            scene,
            [
                {"kind": "text", "id": "x", "content": "a"},
                {"kind": "text", "id": "x", "content": "b"},
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "duplicate element id 'x'" in result
        client.show.assert_not_called()
        assert hub_display.scene_roots(SceneId(scene)) == []


def _assert_show_rejects_dup(
    client: MagicMock, scene: str, elements: list[dict[str, Any]], dup_id: str
) -> None:
    """Drive ``show()`` and assert the tree is rejected without install."""
    result = show(scene, elements)
    assert result.startswith("error: scene not rendered")
    assert f"duplicate element id '{dup_id}'" in result
    assert "unique" in result
    client.show.assert_not_called()
    assert hub_display.scene_roots(SceneId(scene)) == []


class TestShowRejectsNestedDuplicates:
    """A duplicate buried in every child-bearing container is rejected."""

    @patch(_CLIENT_GET)
    def test_show_rejects_dup_in_abc_tab_bar_tab(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        _assert_show_rejects_dup(
            client,
            "dup-abc-tab-bar",
            [
                {
                    "kind": "tab_bar",
                    "id": "tb",
                    "tabs": [
                        {
                            "label": "One",
                            "children": [{"kind": "text", "id": "dup", "content": "a"}],
                        },
                        {
                            "label": "Two",
                            "children": [{"kind": "text", "id": "dup", "content": "b"}],
                        },
                    ],
                }
            ],
            "dup",
        )

    @patch(_CLIENT_GET)
    def test_show_rejects_dup_in_legacy_tab_bar_tab(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        # A separator (not a migrated-ABC kind) forks the whole tab_bar legacy.
        _assert_show_rejects_dup(
            client,
            "dup-legacy-tab-bar",
            [
                {
                    "kind": "tab_bar",
                    "id": "tb",
                    "tabs": [
                        {
                            "label": "One",
                            "children": [
                                {"kind": "text", "id": "dup", "content": "a"},
                                {"kind": "separator"},
                            ],
                        },
                        {
                            "label": "Two",
                            "children": [{"kind": "text", "id": "dup", "content": "b"}],
                        },
                    ],
                }
            ],
            "dup",
        )

    @patch(_CLIENT_GET)
    def test_show_rejects_dup_in_legacy_group_page(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        # A paged layout forks the group legacy; the dup hides on an off-screen page.
        _assert_show_rejects_dup(
            client,
            "dup-legacy-group-page",
            [
                {
                    "kind": "group",
                    "id": "g",
                    "layout": "paged",
                    "children": [{"kind": "text", "id": "dup", "content": "nav"}],
                    "pages": [[{"kind": "text", "id": "dup", "content": "page"}]],
                }
            ],
            "dup",
        )

    @patch(_CLIENT_GET)
    def test_show_rejects_dup_in_collapsing_header(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        _assert_show_rejects_dup(
            client,
            "dup-collapsing-header",
            [
                {
                    "kind": "collapsing_header",
                    "id": "ch",
                    "label": "Section",
                    "children": [
                        {"kind": "text", "id": "dup", "content": "a"},
                        {"kind": "text", "id": "dup", "content": "b"},
                    ],
                }
            ],
            "dup",
        )

    @patch(_CLIENT_GET)
    def test_show_rejects_dup_across_nested_groups(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client
        _assert_show_rejects_dup(
            client,
            "dup-nested-groups",
            [
                {
                    "kind": "group",
                    "id": "outer",
                    "layout": "rows",
                    "children": [
                        {
                            "kind": "group",
                            "id": "inner",
                            "layout": "rows",
                            "children": [{"kind": "text", "id": "dup", "content": "a"}],
                        },
                        {"kind": "text", "id": "dup", "content": "b"},
                    ],
                }
            ],
            "dup",
        )
