"""OperationsConcerns -- the ten-field bundle Operations.__new__ takes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from punt_lux.operations.concerns import OperationsConcerns


def _concerns() -> OperationsConcerns:
    # Plain sentinels: OperationsConcerns is a pure carrier with no runtime
    # type validation, so a stand-in per field proves the bundle shape without
    # constructing nine real, heavily-collaborating concern classes.
    return OperationsConcerns(
        scenes=object(),  # type: ignore[arg-type]  # sentinel; carrier has no runtime type check
        pubsub=object(),  # type: ignore[arg-type]  # sentinel
        config=object(),  # type: ignore[arg-type]  # sentinel
        display=object(),  # type: ignore[arg-type]  # sentinel
        queries=object(),  # type: ignore[arg-type]  # sentinel
        menus=object(),  # type: ignore[arg-type]  # sentinel
        identity=object(),  # type: ignore[arg-type]  # sentinel
        callbacks=object(),  # type: ignore[arg-type]  # sentinel
        frame_remover=object(),  # type: ignore[arg-type]  # sentinel
        link=object(),  # type: ignore[arg-type]  # sentinel
    )


def test_every_field_round_trips() -> None:
    concerns = _concerns()
    assert concerns.scenes is not None
    assert concerns.pubsub is not None
    assert concerns.config is not None
    assert concerns.display is not None
    assert concerns.queries is not None
    assert concerns.menus is not None
    assert concerns.identity is not None
    assert concerns.callbacks is not None
    assert concerns.frame_remover is not None
    assert concerns.link is not None


def test_is_frozen() -> None:
    concerns = _concerns()
    with pytest.raises(FrozenInstanceError):
        concerns.scenes = object()  # type: ignore[assignment,misc]  # proving frozen=True raises
