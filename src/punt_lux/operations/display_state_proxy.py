"""DisplayStateProxy — the Display's own widget/frame state, as a bounded read.

Structurally identical in shape to ``DisplayFactProxy``: one proxied round trip
over ``DisplayLink.query``, narrowed to a typed result or an ``OpError`` —
never installed as Hub state. The wire reply's scenes arrive as bare scalar
mappings, not the ``{"values": ...}`` shape :class:`WidgetSnapshot` wants, so
``_RawDisplayState`` validates that wire shape here, at the decode boundary
this proxy owns, before ``DisplayStateSnapshot`` is assembled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_state import (
    DisplayStateSnapshot,
    FramePresentation,
    WidgetSnapshot,
    WireScalar,
)
from punt_lux.operations.scene_listing import SceneListing

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort

__all__ = ["DisplayStateProxy"]


class _RawDisplayState(BaseModel):
    """The wire shape a ``display_state`` reply is validated against.

    Scenes arrive keyed by whatever id the display holds them under; the
    caller normalizes each key to its own local id afterward
    (``DisplayStateProxy.snapshot``), so this stage only needs to know each
    scene's value is a curated widget-state mapping.
    """

    model_config = ConfigDict(frozen=True)

    scenes: dict[str, dict[str, WireScalar]] = Field(default_factory=dict)
    frames: list[FramePresentation] = Field(default_factory=list[FramePresentation])

    def to_snapshot(self) -> DisplayStateSnapshot:
        """Assemble the curated snapshot this validated wire shape describes."""
        scenes = {
            scene_id: WidgetSnapshot(values=values)
            for scene_id, values in self.scenes.items()
        }
        return DisplayStateSnapshot(scenes=scenes, frames=self.frames)


@final
class DisplayStateProxy:
    """Proxy the Display's own widget/frame state, narrowed to a snapshot."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def snapshot(self) -> DisplayStateSnapshot | OpError:
        """Return the display's curated widget/frame state, scene ids normalized."""
        payload = self._port.query("display_state", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        try:
            raw = _RawDisplayState.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
        return self._normalized(raw.to_snapshot())

    @staticmethod
    def _normalized(snapshot: DisplayStateSnapshot) -> DisplayStateSnapshot:
        """Strip every composed scene id back to the caller's own local id.

        The display keys ``scenes``, and each frame's ``active_tab``, by
        whatever id the Hub last pushed under — the composed store key — so a
        caller can correlate this snapshot against ``inspect_scene``/
        ``list_scenes`` results it already holds, with no re-composition of
        its own.
        """
        scenes = {
            SceneListing.local_id_of(scene_id): widget
            for scene_id, widget in snapshot.scenes.items()
        }
        frames = [
            frame.model_copy(update={"active_tab": DisplayStateProxy._local_tab(frame)})
            for frame in snapshot.frames
        ]
        return DisplayStateSnapshot(scenes=scenes, frames=frames)

    @staticmethod
    def _local_tab(frame: FramePresentation) -> str | None:
        """Normalize a frame's active-tab scene id, preserving "no scenes" as None."""
        active_tab = frame.active_tab
        return None if active_tab is None else SceneListing.local_id_of(active_tab)
