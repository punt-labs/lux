"""WriteSeam judges a batch's nesting jointly, and only when a patch can deepen it.

The realizations here are fakes: ``FieldRealization`` is a Protocol, and no real
element kind lets two patches nest inside one another, so the joint judgement is
only reachable with realizations that say what they would become.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from punt_lux.domain.hub.field_realization import FieldRealization
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.hub.write_seam import WriteSeam
from punt_lux.domain.ids import SceneId
from punt_lux.protocol.json_payload import MAX_ELEMENT_NESTING

if TYPE_CHECKING:
    from punt_lux.domain.hub.element_index import ElementIndex

_SCENE = SceneId("s")


def _chain(levels: int, leaf: object) -> object:
    """``leaf`` wrapped in ``levels`` single-key objects."""
    value = leaf
    for _ in range(levels):
        value = {"k": value}
    return value


@dataclass(frozen=True)
class _Wired:
    """Something with a wire form, which is all the cap asks of an element."""

    wire: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return self.wire


@dataclass(frozen=True)
class _Fake:
    """A realization that would turn ``element_id`` into ``wire``."""

    element_id: str
    wire: dict[str, object]
    deepens: bool = True

    def rejection(self) -> WriteRejected | None:
        return None

    def can_deepen(self) -> bool:
        return self.deepens

    def projected(self) -> tuple[str, object]:
        return self.element_id, _Wired(self.wire)

    def commit(self) -> None:
        """Unused: the seam only judges."""

    def restore(self) -> None:
        """Unused: the seam only judges."""


class _Index:
    """The one scene the seam reads: a root holding an element called ``inner``."""

    def scene_roots(self, scene_id: SceneId) -> list[object]:
        assert scene_id == _SCENE
        return [
            _Wired(
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


class TestOnlyADeepeningPatchIsProjected:
    """A batch no field of which can hold elements costs no projection."""

    def test_a_batch_with_no_deepening_patch_projects_nothing(self) -> None:
        class _Exploding(_Fake):
            def projected(self) -> tuple[str, object]:
                raise AssertionError("a scalar patch must not be projected")

        scalar = _Exploding("inner", {"kind": "box", "id": "inner"}, deepens=False)

        assert _seam().nesting_refusal(_SCENE, [scalar]) is None

    def test_a_non_deepening_patch_does_not_hide_a_deepening_one(self) -> None:
        scalar = _Fake("r", {"kind": "box", "id": "r"}, deepens=False)
        deep = _Fake("inner", {"kind": "box", "id": "inner", "b": _chain(60, 1)})

        assert _seam().nesting_refusal(_SCENE, [scalar, deep]) is not None


def test_the_fakes_satisfy_the_realization_contract() -> None:
    realization: FieldRealization = _Fake("x", {})

    assert realization.can_deepen()
