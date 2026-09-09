"""FrameCloser — tear down the caller's own frame, or say truthfully why not.

Split out of ``SceneOperations`` (lux-03k6): closing a frame is a distinct
concern from installing, patching, and clearing scenes, and mirrors
``SceneClearer``/``SceneInstaller`` as its own single-purpose collaborator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker

__all__ = ["FrameCloser"]


@final
class FrameCloser:
    """Resolve the caller's own local frame name and tear it down, or refuse."""

    _display: HubDisplay
    _replicator: DirtyMarker
    __slots__ = ("_display", "_replicator")

    def __new__(cls, display: HubDisplay, replicator: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        return self

    def close(self, local_id: str, owner: ConnectionId) -> Ok | OpError:
        """Tear down ``owner``'s own ``local_id`` frame; report truthfully otherwise.

        Resolved through :meth:`FrameLifecycle.frame_id_for_local` against
        ``owner`` -- the same choke point every other write in this domain
        composes at. An unresolved name means ``owner`` never recorded a
        presentation under it, whether because no such frame exists at all or
        because it belongs to a different connection; the two are
        indistinguishable from here (DES-086's composition already refuses
        the collision), so both report the identical ``not_found`` rather
        than a blanket success that removed nothing.
        """
        frame_id = self._display.frames.frame_id_for_local(local_id, connection=owner)
        if frame_id is None:
            return OpError(code="not_found", reason=f"no frame named {local_id!r}")
        for scene_id in self._display.frames.remove_frame(frame_id):
            self._replicator.mark_dirty(scene_id)
        return Ok()
