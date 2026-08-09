"""The display-side commands that act on a frame: its minimize state, and raising it.

Two queries the Hub sends about one frame, kept together because they answer the
same question from different ends — where in the window stack a frame sits.
``set_state`` is the transient minimize flag a caller sets directly; ``raise_it``
is the whole gesture behind a user asking for a frame by name: restore it if it
is in the dock, and put it in front on the next render.

Raising is deliberately not an error when the frame is unknown. A caller asking
for a frame that is not up is not making a mistake — it is discovering that it
has to push one — so the answer is ``raised: false`` rather than a fault it would
have to catch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from punt_lux.display.replica import SceneReplica

__all__ = ["FrameCommands"]


@final
class FrameCommands:
    """The query handlers for one display's frames, over its scene manager."""

    _scenes: SceneReplica
    __slots__ = ("_scenes",)

    def __new__(cls, scenes: SceneReplica) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        return self

    def set_state(self, frame_id: str = "", **kwargs: Any) -> dict[str, Any]:
        """Change the named frame's minimize state and report what actually changed."""
        frame = self._scenes.frames.get(self._required(frame_id))
        if frame is None:
            msg = f"frame '{frame_id}' not found"
            raise LookupError(msg)
        changed: dict[str, Any] = {}
        if "minimized" in kwargs:
            frame.minimized = bool(kwargs["minimized"])
            changed["minimized"] = frame.minimized
        elif "collapsed" in kwargs:
            frame.minimized = bool(kwargs["collapsed"])
            changed["minimized"] = frame.minimized
        return {"frame_id": frame_id, "changed": changed}

    def raise_it(self, frame_id: str = "", **_kwargs: Any) -> dict[str, Any]:
        """Bring the named frame to the front, restoring it if it was minimized.

        Restoring and focusing are one gesture, not two: a frame that took focus
        while still in the dock would have answered the request without becoming
        visible. A frame this display does not hold answers ``raised: false``, so
        the caller learns to push one rather than having to read an error.
        """
        frame = self._scenes.frames.get(self._required(frame_id))
        if frame is None:
            return {"frame_id": frame_id, "raised": False}
        frame.minimized = False
        self._scenes.request_focus(frame_id)
        return {"frame_id": frame_id, "raised": True}

    @staticmethod
    def _required(frame_id: str) -> str:
        """Return ``frame_id``, or raise: every frame command names one frame."""
        if not frame_id:
            msg = "frame_id is required"
            raise ValueError(msg)
        return frame_id
