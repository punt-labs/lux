"""FramePlacement — the fit-all state shared by every frame in one render pass."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

__all__ = ["FramePlacement"]


@dataclasses.dataclass(frozen=True, slots=True)
class FramePlacement:
    """The fit-all state shared by every frame in one render pass."""

    fitting: bool
    tile_layout: Mapping[str, tuple[float, float, float, float]]
    default_size: tuple[float, float]
