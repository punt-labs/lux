"""The Hub's typed errors are built by ``__new__``, checked at run time, and sealed."""

from __future__ import annotations

import copy
import pickle
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.write_errors import ImmutableFieldError, MalformedPatchError
from punt_lux.domain.hub.write_refusals import NestingExceededError, UnheldTargetError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.interaction_errors import WrongKindError

if TYPE_CHECKING:
    from collections.abc import Callable

_S, _E = SceneId("s"), ElementId("e")

_BUILT: list[tuple[Callable[[], BaseException], Callable[[], BaseException]]] = [
    (
        lambda: NestingExceededError("too deep"),
        lambda: NestingExceededError.of("too deep"),
    ),
    (lambda: UnheldTargetError("e"), lambda: UnheldTargetError.of("e")),
    (
        lambda: HubOwnershipError(_S, _E, ConnectionId("a"), ConnectionId("b")),
        lambda: HubOwnershipError.of(_S, _E, ConnectionId("a"), ConnectionId("b")),
    ),
    (lambda: ImmutableFieldError(_E, "id"), lambda: ImmutableFieldError.of(_E, "id")),
    (lambda: MalformedPatchError(_E, "bad"), lambda: MalformedPatchError.of(_E, "bad")),
    (
        lambda: MalformedPatchError(None, "bad"),
        lambda: MalformedPatchError.of(None, "bad"),
    ),
    (
        lambda: StructuralFieldWriteError(_E, "tabs"),
        lambda: StructuralFieldWriteError.of(_E, "tabs"),
    ),
    (lambda: UnknownSceneError(_S), lambda: UnknownSceneError.of(_S)),
    (lambda: UnknownElementError(_S, _E), lambda: UnknownElementError.of(_S, _E)),
    (
        lambda: WrongKindError(_S, _E, "button", "slider"),
        lambda: WrongKindError.of(_S, _E, "button", "slider"),
    ),
]
_IDS = [
    "nesting",
    "unheld",
    "ownership",
    "immutable",
    "malformed",
    "malformed-no-id",
    "structural",
    "unknown-scene",
    "unknown-element",
    "wrong-kind",
]
_CLASSES = [type(plain()) for plain, _ in _BUILT]


@pytest.mark.parametrize(("plain", "named"), _BUILT, ids=_IDS)
def test_plain_construction_and_the_named_constructor_agree(
    plain: Callable[[], BaseException], named: Callable[[], BaseException]
) -> None:
    assert (type(plain()), str(plain()), plain().args) == (
        type(named()),
        str(named()),
        named().args,
    )


@pytest.mark.parametrize(("plain", "_named"), _BUILT, ids=_IDS)
def test_a_pickle_round_trip_keeps_the_class_the_message_and_the_fields(
    plain: Callable[[], BaseException], _named: Callable[[], BaseException]
) -> None:
    raised = plain()

    pickle.dumps(raised)  # must not raise: the instance is picklable
    again = copy.deepcopy(raised)  # the same ``__reduce__`` a pickle rebuilds by

    assert (type(again), str(again), repr(again)) == (
        type(raised),
        str(raised),
        repr(raised),
    )


@pytest.mark.parametrize("error", _CLASSES, ids=lambda c: c.__name__)
def test_wrong_arguments_raise_a_type_error_naming_the_class(
    error: type[BaseException],
) -> None:
    with pytest.raises(TypeError, match=error.__name__):
        error(object(), object(), object(), object(), object())


def test_the_fields_read_back_as_properties() -> None:
    owned = HubOwnershipError(_S, _E, ConnectionId("a"), ConnectionId("b"))
    kind = WrongKindError(_S, _E, "button", "slider")

    assert (owned.scene_id, owned.element_id, owned.attempting, owned.owning) == (
        _S,
        _E,
        "a",
        "b",
    )
    assert (kind.expected, kind.got) == ("button", "slider")


def test_an_ownership_error_has_a_meaningful_repr() -> None:
    owned = HubOwnershipError(_S, _E, ConnectionId("a"), ConnectionId("b"))

    assert repr(owned) == ("HubOwnershipError('s', 'e', attempting='a', owning='b')")


@pytest.mark.parametrize("error", _CLASSES, ids=lambda c: c.__name__)
def test_every_leaf_error_is_final(error: type[BaseException]) -> None:
    assert error.__dict__.get("__final__", False) is True
