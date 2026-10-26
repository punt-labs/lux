"""A Hub-side handler's write to an element is judged by the seam, at run time.

An agent's write goes through ``WriteSeam``, which refuses one that would nest the
scene past the cap. A handler writes too: when the display reports a click, the
handler patches the Hub's own copy. The seam fires the event, and every patch a
handler writes while it runs is judged first, so a handler that patches a container
field deeper than the cap is refused whatever field it patched and however it named it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handler_writes import HandlerWrites
from punt_lux.domain.hub.handler_firing import HandlerFiring
from punt_lux.domain.hub.write_errors import NestingExceededError
from punt_lux.domain.ids import ClientId, ElementId
from punt_lux.domain.interaction import ButtonClicked
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol.elements import ButtonElement, TreeElement
from tests.domain.test_nesting_cap_at_the_seam import (
    _DEEP,
    _SCENE,
    _nodes,
    _store_with,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class _WritesNodes:
    """A handler that patches a tree's nodes, as a buggy new handler might."""

    _tree: TreeElement
    _levels: int

    def __init__(self, tree: TreeElement, levels: int) -> None:
        self._tree = tree
        self._levels = levels

    def __call__(self, event: ButtonClicked) -> None:
        self._tree.apply_patch({"nodes": [_nodes(self._levels)]})


def _click() -> ButtonClicked:
    return ButtonClicked(
        scene_id=_SCENE, element_id=ElementId("b"), owner_id=ClientId("local")
    )


def _scene_with_a_handler(levels: int) -> tuple[ButtonElement, TreeElement]:
    button = ButtonElement(id="b", label="x")
    tree = TreeElement(id="t")
    button.add_handler(ButtonClicked, _WritesNodes(tree, levels))
    return button, tree


class TestAHandlerWriteThroughTheSeam:
    def test_a_write_that_would_nest_too_deeply_is_refused_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        button, tree = _scene_with_a_handler(_DEEP)
        store = _store_with(button, tree)

        with caplog.at_level(logging.ERROR):
            HandlerFiring(store.write_seam).fire(_SCENE, button, _click())

        assert tree.nodes == ()
        assert "handler raised on ButtonClicked for element b" in caplog.text

    def test_a_shallow_write_is_applied(self) -> None:
        button, tree = _scene_with_a_handler(2)
        store = _store_with(button, tree)

        HandlerFiring(store.write_seam).fire(_SCENE, button, _click())

        assert tree.nodes != ()

    def test_the_refusal_is_the_seams_own_error(self) -> None:
        refused: list[BaseException] = []
        tree = TreeElement(id="t")
        button = ButtonElement(id="b", label="x")

        def writes_and_notes(event: ButtonClicked) -> None:
            try:
                tree.apply_patch({"nodes": [_nodes(_DEEP)]})
            except NestingExceededError as exc:
                refused.append(exc)

        button.add_handler(ButtonClicked, writes_and_notes)
        store = _store_with(button, tree)

        HandlerFiring(store.write_seam).fire(_SCENE, button, _click())

        assert [str(exc) for exc in refused] == [NestingCap.reason()]


class TestTheJudgeIsScopedToTheFire:
    def test_a_write_outside_a_fire_is_not_judged_here(self) -> None:
        button, tree = _scene_with_a_handler(2)
        store = _store_with(button, tree)
        HandlerFiring(store.write_seam).fire(_SCENE, button, _click())

        tree.apply_patch({"nodes": [_nodes(3)]})  # no judge is installed any more

        assert tree.nodes != ()

    def test_a_judge_that_writes_is_not_judged_in_turn(self) -> None:
        tree = TreeElement(id="t")
        seen: list[str] = []

        def judge(target: Element, patch: Mapping[str, object]) -> None:
            seen.append(target.id)
            target.apply_patch({"label": "judged"})  # would recurse if it were judged

        with HandlerWrites.judged(judge):
            tree.apply_patch({"label": "x"})

        assert seen == ["t"]

    def test_the_scope_ends_when_the_handler_raises(self) -> None:
        tree = TreeElement(id="t")

        def refuse(target: Element, patch: Mapping[str, object]) -> None:
            raise ValueError("refused")

        with pytest.raises(ValueError, match="refused"), HandlerWrites.judged(refuse):
            tree.apply_patch({"label": "x"})
        tree.apply_patch({"label": "y"})

        assert tree.label == "y"
