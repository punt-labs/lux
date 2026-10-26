"""An exception raised through a ``@contextmanager`` comes out as the same instance.

``contextlib`` assigns ``__traceback__`` to whatever passes through a generator
manager, and a frozen dataclass refuses every attribute write. The refusals the judge
raises and the Hub's other typed errors are therefore plain exception classes, built by
``__new__`` with their fields as properties; no exception class in ``src`` is a frozen
dataclass.
"""

from __future__ import annotations

import contextlib
import copy
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.element_index import UnknownElementError, UnknownSceneError
from punt_lux.domain.hub.ownership_error import HubOwnershipError
from punt_lux.domain.hub.write_errors import ImmutableFieldError, MalformedPatchError
from punt_lux.domain.hub.write_refusals import NestingExceededError, UnheldTargetError
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.interaction_errors import WrongKindError
from tests.exception_scan import ExceptionScan

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_S, _E = SceneId("s"), ElementId("e")

_MADE: list[Callable[[], BaseException]] = [
    lambda: NestingExceededError.at("too deep"),
    lambda: UnheldTargetError.of("e"),
    lambda: HubOwnershipError.of(_S, _E, ConnectionId("a"), ConnectionId("b")),
    lambda: ImmutableFieldError.of(_E, "id"),
    lambda: MalformedPatchError.of(_E, "bad"),
    lambda: MalformedPatchError.of(None, "bad"),
    lambda: StructuralFieldWriteError.of(_E, "children"),
    lambda: UnknownSceneError.of(_S),
    lambda: UnknownElementError.of(_S, _E),
    lambda: WrongKindError.of(_S, _E, "button", "slider"),
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


@contextlib.contextmanager
def _passing_through() -> Generator[None]:
    yield


@pytest.mark.parametrize("make", _MADE, ids=_IDS)
def test_it_comes_out_of_a_context_manager_as_the_same_instance(
    make: Callable[[], BaseException],
) -> None:
    raised = make()

    with pytest.raises(type(raised)) as caught, _passing_through():
        raise raised

    assert caught.value is raised


@pytest.mark.parametrize("make", _MADE, ids=_IDS)
def test_it_survives_a_copy_with_the_same_message(
    make: Callable[[], BaseException],
) -> None:
    raised = make()

    again = copy.deepcopy(raised)  # the same ``__reduce__`` a pickle uses

    assert (type(again), str(again)) == (type(raised), str(raised))


def test_no_exception_class_in_src_is_a_frozen_dataclass() -> None:
    src = Path(__file__).resolve().parents[2] / "src"

    assert ExceptionScan(src).frozen_exceptions() == []


def test_the_scan_sees_a_planted_frozen_exception(tmp_path: Path) -> None:
    (tmp_path / "planted.py").write_text(
        "from dataclasses import dataclass\n"
        "class Base(ValueError): ...\n"
        "@dataclass(frozen=True, slots=True)\n"
        "class Planted(Base):\n"
        "    reason: str\n"
        "@dataclass(frozen=True)\n"
        "class NotAnException:\n"
        "    reason: str\n",
        encoding="utf-8",
    )

    found = ExceptionScan(tmp_path).frozen_exceptions()

    assert [line.split(" at ")[0] for line in found] == ["Planted"]
