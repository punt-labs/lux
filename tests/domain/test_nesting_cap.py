"""The Hub refuses a scene no reply could carry: one cap on how deep an element nests.

A display's ``inspect_scene`` reply carries the scene's element tree as nested JSON,
and the wire guard refuses a frame that nests past ``MAX_NESTING``. The Hub accepts
a scene only if its deepest element fits the cap the guard is derived from, so no
accepted scene can make a reply undecodable (which would retire the dial).
"""

from __future__ import annotations

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
from punt_lux.protocol.elements import GroupElement
from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING, MAX_NESTING
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

    def test_the_wire_guard_is_the_cap_plus_the_envelope(self) -> None:
        assert MAX_NESTING > MAX_ELEMENT_NESTING
