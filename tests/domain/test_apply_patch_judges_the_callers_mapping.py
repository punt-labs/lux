"""Every element kind shows the judge the very mapping the caller wrote.

The batch judge passes a pre-judged write by the identity of its element and its
mapping; a kind that rebinds the mapping before it reaches the base class would be
judged a second time, mid-commit. A reorder lives in ``_SETTER_PRIORITY``, which only
orders the keys the judge has already approved.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.handler_writes import HandlerWrites
from punt_lux.domain.hub.batch_judge import BatchJudge
from punt_lux.protocol.elements import ImageElement, MarkdownElement, TextElement
from punt_lux.protocol.elements.abc_kind_table import DEFAULT_ABC_REGISTRY
from punt_lux.protocol.elements.tree import TreeElement

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element

# Kinds that cannot be built from an id alone.
_NEEDS: dict[type, dict[str, object]] = {
    TextElement: {"content": "x"},
    MarkdownElement: {"content": "x"},
    ImageElement: {"path": "x.png"},
}


def _built(kind: type[Element]) -> Element:
    return kind(id="e", **_NEEDS.get(kind, {}))  # type: ignore[arg-type, call-arg]  # per kind


@pytest.mark.parametrize(
    "kind", DEFAULT_ABC_REGISTRY.abc_types, ids=lambda kind: kind.__name__
)
def test_the_judge_is_shown_the_callers_own_mapping(kind: type[Element]) -> None:
    element = _built(kind)
    patch: Mapping[str, object] = {"label": "x"}
    seen: list[tuple[object, Mapping[str, object]]] = []

    def judge(target: object, written: Mapping[str, object]) -> None:
        seen.append((target, written))

    with (
        HandlerWrites.judged(BatchJudge(judge, [])),
        contextlib.suppress(Exception),  # the kind may reject the field
    ):
        element.apply_patch(patch)

    assert len(seen) == 1
    assert seen[0][0] is element
    assert seen[0][1] is patch


def test_a_reorder_can_only_order_the_keys_the_judge_approved() -> None:
    patch: dict[str, object] = {
        "label": "x",
        "anchor_node_id": "n",
        "nodes": [],
        "selected_node_ids": [],
    }

    ordered = TreeElement._SETTER_PRIORITY.arrange(patch)

    assert list(ordered)[:3] == ["nodes", "selected_node_ids", "anchor_node_id"]
    assert ordered == patch
    assert len(ordered) == len(patch)
