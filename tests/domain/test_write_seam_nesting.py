"""WriteSeam judges a batch's nesting jointly, and only when an element got deeper.

The realizations here are fakes: ``FieldRealization`` is a Protocol, and no real
element kind lets two patches nest inside one another, so the joint judgement is
only reachable with realizations that say what they would become. Whether a write
deepens the wire form is read off the element's own depth before and after, never
off which field it names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from punt_lux.domain.hub.field_realization import FieldRealization
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import SceneId
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING
from tests.domain.wire_doubles import WireOnly

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pytest

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.element_index import ElementIndex

_SCENE = SceneId("s")


def _chain(levels: int, leaf: object) -> object:
    """``leaf`` wrapped in ``levels`` single-key objects."""
    value = leaf
    for _ in range(levels):
        value = {"k": value}
    return value


@dataclass(frozen=True)
class _Fake:
    """A realization that would turn ``element_id`` into ``wire``, from ``before``."""

    element_id: str
    wire: dict[str, object]
    before: dict[str, object] | None = None  # None: the element is as shallow as can be

    def rejection(self) -> WriteRejected | None:
        return None

    def current(self) -> WireElement:
        start = self.before or {"kind": "box", "id": self.element_id}
        return WireOnly(start)

    def projected(self) -> tuple[str, WireElement]:
        return self.element_id, WireOnly(self.wire)

    def commit(self) -> None:
        """Unused: the seam only judges."""

    def restore(self) -> None:
        """Unused: the seam only judges."""


class _Index:
    """The one scene the seam reads: a root holding an element called ``inner``."""

    def scene_roots(self, scene_id: SceneId) -> list[WireElement]:
        assert scene_id == _SCENE
        return [
            WireOnly(
                {
                    "kind": "box",
                    "id": "r",
                    "body": {"kind": "box", "id": "inner"},
                }
            )
        ]


def _seam() -> WriteSeam:
    return WriteSeam(cast("ElementIndex", _Index()))


def _outer(levels: int) -> _Fake:
    """Replace the root with one that buries ``inner`` ``levels`` deep."""
    return _Fake(
        "r",
        {
            "kind": "box",
            "id": "r",
            "body": _chain(levels, {"kind": "box", "id": "inner"}),
        },
    )


def _inner(levels: int) -> _Fake:
    """Replace ``inner`` with ``levels`` of nesting."""
    return _Fake("inner", {"kind": "box", "id": "inner", "body": _chain(levels, 1)})


_HALF = MAX_ELEMENT_NESTING * 5 // 8


class TestAWholeBatchIsJudgedAtOnce:
    """Two patches that fit alone but nest past the cap together are refused."""

    def test_each_patch_alone_is_within_the_cap(self) -> None:
        seam = _seam()

        assert seam.nesting_refusal(_SCENE, [_outer(_HALF)]) is None
        assert seam.nesting_refusal(_SCENE, [_inner(_HALF)]) is None

    def test_the_two_together_are_refused(self) -> None:
        reason = _seam().nesting_refusal(_SCENE, [_outer(_HALF), _inner(_HALF)])

        assert reason is not None
        assert str(MAX_ELEMENT_NESTING) in reason

    def test_the_order_they_are_listed_in_makes_no_difference(self) -> None:
        reason = _seam().nesting_refusal(_SCENE, [_inner(_HALF), _outer(_HALF)])

        assert reason is not None


class TestOnlyAnElementThatGotDeeperIsProjected:
    """A batch in which no element got deeper costs no projection of the scene."""

    def test_a_batch_in_which_nothing_got_deeper_projects_no_scene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def exploding(
            self: NestingCap,
            roots: Sequence[WireElement],
            patched: Mapping[str, WireElement],
        ) -> str | None:
            raise AssertionError("a patch that deepens nothing must not project")

        monkeypatch.setattr(NestingCap, "refusal_if_patched", exploding)
        same = _Fake("inner", {"kind": "box", "id": "inner"})

        assert _seam().nesting_refusal(_SCENE, [same]) is None

    def test_a_patch_that_only_got_shallower_is_not_projected(self) -> None:
        deep_before = {"kind": "box", "id": "inner", "b": _chain(5, 1)}
        shallower = _Fake("inner", {"kind": "box", "id": "inner"}, before=deep_before)

        assert _seam().nesting_refusal(_SCENE, [shallower]) is None

    def test_a_patch_that_did_not_get_deeper_does_not_hide_one_that_did(self) -> None:
        as_it_is: dict[str, object] = {
            "kind": "box",
            "id": "r",
            "body": {"kind": "box", "id": "inner"},
        }
        same = _Fake("r", as_it_is, before=as_it_is)
        deep = _Fake("inner", {"kind": "box", "id": "inner", "b": _chain(60, 1)})

        assert _seam().nesting_refusal(_SCENE, [same, deep]) is not None

    def test_the_depth_is_judged_whatever_field_carries_it(self) -> None:
        # No field is named: arbitrary JSON in any field deepens the wire form.
        deep = _Fake("inner", {"kind": "box", "id": "inner", "payload": _chain(60, 1)})

        assert _seam().nesting_refusal(_SCENE, [deep]) is not None


def test_the_fakes_satisfy_the_realization_contract() -> None:
    realization: FieldRealization = _Fake("x", {})

    assert realization.current().id == "x"
