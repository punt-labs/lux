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

from unittest.mock import MagicMock, patch

from punt_lux.domain.error import DuplicateIdError
from punt_lux.domain.hub import hub_display
from punt_lux.domain.id_uniqueness import DuplicateIdScanner
from punt_lux.domain.ids import ElementId, SceneId
from punt_lux.protocol.elements import (
    GroupElement,
    SeparatorElement,
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
