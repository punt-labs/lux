"""DisplayStateProxy — the Display's own widget/frame state, scoped to the caller.

Structurally identical in shape to ``DisplayFactProxy``: one proxied round trip
over ``DisplayLink.query``, narrowed to a typed result or an ``OpError`` —
never installed as Hub state. The wire reply's scenes arrive as bare scalar
mappings, not the ``{"values": ...}`` shape :class:`WidgetSnapshot` wants, so
``_RawDisplayState`` validates that wire shape here, at the decode boundary
this proxy owns, before ``DisplayStateSnapshot`` is assembled.

The display holds every connection's scenes in one flat reply — its one client
is the Hub, not an end caller, so it has no notion of "whose scene is this."
This proxy is the only place that narrows the reply to the caller's own
connection before a composed id is stripped to its local one, so one agent's
widget values (a color picker's chosen color, a text field's typed content)
can never leak into another's read.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_state import (
    DisplayStateSnapshot,
    FramePresentation,
    WidgetSnapshot,
    WireScalar,
)

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.scope import Scope

__all__ = ["DisplayStateProxy"]

logger = logging.getLogger(__name__)


class _RawDisplayState(BaseModel):
    """The wire shape a ``display_state`` reply is validated against.

    Scenes arrive keyed by whatever id the display holds them under, spanning
    every connection the Hub has ever pushed to it — narrowing to the caller's
    own is :class:`DisplayStateProxy`'s job, after this stage confirms each
    scene's value is a curated widget-state mapping, required with no default.
    """

    model_config = ConfigDict(frozen=True)

    scenes: dict[str, dict[str, WireScalar]]
    frames: list[FramePresentation]

    def to_snapshot(self) -> DisplayStateSnapshot:
        """Assemble the curated snapshot this validated wire shape describes."""
        scenes = {
            scene_id: WidgetSnapshot(values=values)
            for scene_id, values in self.scenes.items()
        }
        return DisplayStateSnapshot(scenes=scenes, frames=self.frames)


@final
class DisplayStateProxy:
    """Proxy the Display's own widget/frame state, scoped to the caller's own scenes."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def snapshot(self, scope: Scope) -> DisplayStateSnapshot | OpError:
        """Return ``scope``'s own widget/frame state, scene ids normalized."""
        payload = self._port.query("display_state", {}).resolve()
        if isinstance(payload, OpError):
            return payload
        try:
            raw = _RawDisplayState.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
        return self._scoped(raw.to_snapshot(), scope)

    @staticmethod
    def _scoped(snapshot: DisplayStateSnapshot, scope: Scope) -> DisplayStateSnapshot:
        """Narrow to ``scope``'s own scenes, then normalize composed ids to local ones.

        Frame positioning (visibility, cascade index) is not scene content and
        stays reported for every frame, same as ``list_frames``; only the one
        field that names a scene -- ``active_tab`` -- is hidden when it names a
        scene this caller does not own, so the identity of another connection's
        scene never rides an otherwise-unscoped read.
        """
        scenes = DisplayStateProxy._owned_scenes(snapshot.scenes, scope)
        frames = [
            frame.model_copy(
                update={"active_tab": DisplayStateProxy._owned_tab(frame, scope)}
            )
            for frame in snapshot.frames
        ]
        return DisplayStateSnapshot(scenes=scenes, frames=frames)

    @staticmethod
    def _owned_scenes(
        scenes: dict[str, WidgetSnapshot], scope: Scope
    ) -> dict[str, WidgetSnapshot]:
        """Return only ``scope``'s own scenes, keyed by local id.

        Filtering to one connection before stripping the composed prefix is
        what closes the collision the unscoped version of this method used to
        have: two different connections choosing the identical local scene
        name (``"chart"``) no longer land in the same dict together to
        overwrite each other, because only one connection's entries ever
        reach this loop. Within that one connection, a duplicate local id is
        additionally impossible by construction: ``ConnectionScopedId``'s
        composed form is ``connection_id + SEPARATOR + local_id``, and
        partitioning on the first separator recovers that exact string --
        two distinct composed keys can never decode to the same
        (connection, local) pair, so no scene from ``scope``'s own set is
        ever silently overwritten here either.
        """
        owned: dict[str, WidgetSnapshot] = {}
        for scene_id, widget in scenes.items():
            local_id = DisplayStateProxy._local_id_if_owned(scene_id, scope)
            if local_id is not None:
                owned[local_id] = widget
        return owned

    @staticmethod
    def _owned_tab(frame: FramePresentation, scope: Scope) -> str | None:
        """Normalize the frame's active tab, hiding one owned by another connection."""
        active_tab = frame.active_tab
        if active_tab is None:
            return None
        return DisplayStateProxy._local_id_if_owned(active_tab, scope)

    @staticmethod
    def _local_id_if_owned(scene_id: str, scope: Scope) -> str | None:
        """Return ``scene_id``'s local id when ``scope`` owns it, else ``None``."""
        try:
            composed = ConnectionScopedId.from_composed(scene_id)
        except ValueError:
            logger.warning("non-composed store key at display_state: %r", scene_id)
            return None
        if composed.connection_id != scope.connection_id:
            return None
        return composed.local_id
