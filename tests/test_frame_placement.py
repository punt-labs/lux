"""FramePlacement — a frozen value carrying the fit-all state for one render pass."""

from __future__ import annotations

import pytest

from punt_lux.display.frame_placement import FramePlacement


def test_frame_placement_holds_its_fields() -> None:
    placement = FramePlacement(
        fitting=True,
        tile_layout={"f1": (0.0, 0.0, 100.0, 100.0)},
        default_size=(1.0, 2.0),
    )
    assert placement.fitting is True
    assert placement.tile_layout == {"f1": (0.0, 0.0, 100.0, 100.0)}
    assert placement.default_size == (1.0, 2.0)


def test_frame_placement_is_frozen() -> None:
    placement = FramePlacement(fitting=False, tile_layout={}, default_size=(1.0, 2.0))
    with pytest.raises(AttributeError):
        placement.fitting = True  # type: ignore[misc]
