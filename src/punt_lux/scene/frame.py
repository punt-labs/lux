"""Frame dataclass — a named inner window holding one or more scenes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from punt_lux.protocol import SceneMessage


@dataclass
class Frame:
    """A named inner window in the workspace.

    Each frame owns one or more scenes contributed by one or more clients.
    When ``layout`` is ``"tab"`` (default), multiple scenes appear as tabs;
    when ``"stack"``, they stack vertically with collapsing headers.
    """

    frame_id: str
    title: str
    owner_fds: set[int]
    scenes: dict[str, SceneMessage]
    scene_order: list[str]
    active_tab: str | None = None
    minimized: bool = False
    cascade_index: int = 0
    initial_size: tuple[int, int] | None = None
    flags: dict[str, bool] | None = None
    layout: Literal["tab", "stack"] = "tab"
