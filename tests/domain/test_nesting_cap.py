"""The Hub refuses a scene no reply could carry: one cap on how deep an element nests.

A display's ``inspect_scene`` reply carries the scene's element tree as nested JSON,
and the wire guard refuses a frame that nests past ``MAX_NESTING``. The Hub accepts
a scene only if its deepest element fits the cap the guard is derived from, so no
accepted scene can make a reply undecodable (which would retire the dial).
"""

from __future__ import annotations

from typing import cast

from punt_lux.display.scene_inspection import SceneInspection
from punt_lux.domain.ids import SceneId
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.domain.submission_gate import SubmissionGate
from punt_lux.protocol import (
    FrameReader,
    QueryResponse,
    TextElement,
    encode_message,
)
from punt_lux.protocol.elements import GroupElement, TreeElement
from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING, MAX_NESTING
from punt_lux.protocol.messages import message_to_dict
from punt_lux.protocol.messages.wire_vocabulary import DISPLAY_VOCABULARY


def _chain(levels: int) -> GroupElement:
    """Groups nested ``levels`` deep, the innermost holding one text."""
    node = GroupElement(id="g0", children=(TextElement(id="leaf", content="x"),))
    for i in range(1, levels):
        node = GroupElement(id=f"g{i}", children=(node,))
    return node


def _deepest_within_the_cap() -> GroupElement:
    levels = 1
    while NestingCap().refusal([_chain(levels + 1)]) is None:
        levels += 1
    return _chain(levels)


class TestTheHubRefusesWhatNoReplyCouldCarry:
    def test_a_scene_nested_past_the_cap_is_refused_with_the_reason(self) -> None:
        deep = _chain(MAX_ELEMENT_NESTING)  # two brackets a level: far past the cap

        reason = SubmissionGate().first_rejection(SceneId("s"), [deep])

        assert reason is not None
        assert str(MAX_ELEMENT_NESTING) in reason

    def test_a_scene_at_the_cap_is_accepted(self) -> None:
        assert (
            SubmissionGate().first_rejection(SceneId("s"), [_deepest_within_the_cap()])
            is None
        )

    def test_the_deepest_accepted_scene_s_inspection_reply_is_decoded(self) -> None:
        tree = _deepest_within_the_cap()
        reply = QueryResponse(
            method="inspect_scene",
            result=SceneInspection.from_scene("s", [tree]).to_dict(),
        )
        reader = FrameReader()
        reader.feed(encode_message(reply))

        (decoded,) = list(reader.iter_typed(DISPLAY_VOCABULARY))

        assert decoded == reply


def _brackets(value: object) -> int:
    """How many brackets deep ``value`` nests as JSON."""
    if isinstance(value, dict):
        return 1 + max(
            (_brackets(v) for v in cast("dict[str, object]", value).values()), default=0
        )
    if isinstance(value, list | tuple):
        return 1 + max((_brackets(v) for v in cast("list[object]", value)), default=0)
    return 0


def _nodes(depth: int) -> dict[str, object]:
    node: dict[str, object] = {"label": "leaf"}
    for i in range(depth):
        node = {"label": f"n{i}", "children": [node]}
    return node


def _tree(depth: int) -> TreeElement:
    return TreeElement(id="t").apply_patch({"nodes": [_nodes(depth)]})


def _deepest_tree_within_the_cap() -> TreeElement:
    depth = 0
    while (
        NestingCap().refusal(
            [TreeElement(id="t").apply_patch({"nodes": [_nodes(depth + 1)]})]
        )
        is None
    ):
        depth += 1
    return _tree(depth)


class TestTheEnvelopeIsPinnedToTheDeepestRealReply:
    """The wire guard is the cap plus the reply's envelope; both ends are pinned."""

    @staticmethod
    def _envelope(element: GroupElement | TreeElement) -> int:
        """Brackets the reply adds around ``element``'s own wire form."""
        reply = QueryResponse(
            method="inspect_scene",
            result=SceneInspection.from_scene("s", [element]).to_dict(),
        )
        framed = _brackets(message_to_dict(reply))
        return framed - _brackets(element.to_dict())

    def test_the_guard_leaves_room_for_the_deepest_reply_of_a_scene_at_the_cap(
        self,
    ) -> None:
        elements = (_deepest_within_the_cap(), _deepest_tree_within_the_cap())

        for element in elements:
            reply = QueryResponse(
                method="inspect_scene",
                result=SceneInspection.from_scene("s", [element]).to_dict(),
            )
            assert _brackets(message_to_dict(reply)) <= MAX_NESTING

    def test_the_envelope_is_not_below_the_deepest_real_envelope(self) -> None:
        observed = max(
            self._envelope(e)
            for e in (_deepest_within_the_cap(), _deepest_tree_within_the_cap())
        )

        assert observed <= MAX_NESTING - MAX_ELEMENT_NESTING

    def test_the_envelope_is_not_far_above_it_either(self) -> None:
        observed = max(
            self._envelope(e)
            for e in (_deepest_within_the_cap(), _deepest_tree_within_the_cap())
        )

        assert observed + 1 >= MAX_NESTING - MAX_ELEMENT_NESTING


class _Wire:
    """An element that is nothing but a wire form."""

    def __init__(self, wire: dict[str, object]) -> None:
        self._wire = wire

    def to_dict(self) -> dict[str, object]:
        return self._wire


def _nested_lists(levels: int) -> object:
    value: object = []
    for _ in range(levels - 1):
        value = [value]
    return value


def _group(element_id: str, children: object) -> dict[str, object]:
    return {"kind": "group", "id": element_id, "children": children}


class TestABatchIsJudgedAsAWhole:
    """Patches that nest inside one another are measured with each other in place."""

    _ROOT = _Wire(_group("outer", [_group("inner", [])]))

    def _inner_at_the_cap(self) -> _Wire:
        # object + children list + (levels - 1) more: 2 above it, so exactly the cap.
        return _Wire(_group("inner", _nested_lists(MAX_ELEMENT_NESTING - 3)))

    def _outer_that_wraps_its_child(self) -> _Wire:
        # The same child, four brackets deeper under its parent than before.
        return _Wire(_group("outer", [[[[_group("inner", [])]]]]))

    def test_each_patch_alone_is_within_the_cap(self) -> None:
        cap = NestingCap()

        assert (
            cap.refusal_if_patched([self._ROOT], {"inner": self._inner_at_the_cap()})
            is None
        )
        assert (
            cap.refusal_if_patched(
                [self._ROOT], {"outer": self._outer_that_wraps_its_child()}
            )
            is None
        )

    def test_the_two_together_exceed_it_and_are_refused(self) -> None:
        reason = NestingCap().refusal_if_patched(
            [self._ROOT],
            {
                "inner": self._inner_at_the_cap(),
                "outer": self._outer_that_wraps_its_child(),
            },
        )

        assert reason is not None
        assert str(MAX_ELEMENT_NESTING) in reason

    def test_the_order_the_patches_are_listed_in_makes_no_difference(self) -> None:
        reason = NestingCap().refusal_if_patched(
            [self._ROOT],
            {
                "outer": self._outer_that_wraps_its_child(),
                "inner": self._inner_at_the_cap(),
            },
        )

        assert reason is not None

    def test_patches_in_different_branches_do_not_add(self) -> None:
        root = _Wire(_group("outer", [_group("a", []), _group("b", [])]))
        deep = MAX_ELEMENT_NESTING - 3

        reason = NestingCap().refusal_if_patched(
            [root],
            {
                "a": _Wire(_group("a", _nested_lists(deep))),
                "b": _Wire(_group("b", _nested_lists(deep))),
            },
        )

        assert reason is None
