"""The display-side commands that act on a frame: its dock state, and raising it.

Two queries the Hub sends about one frame, kept together because they answer the
same question from different ends — where in the window stack a frame sits.
``set_state`` docks or restores a frame directly; ``raise_it`` is the whole
gesture behind a user asking for a frame by name: bring it back wherever it was
put away to, and put it in front on the next render.

Raising is deliberately not an error when the frame is unknown. A caller asking
for a frame that is not up is not making a mistake — it is discovering that it
has to push one — so the answer is ``raised: false`` rather than a fault it would
have to catch. A frame the user *closed* is still held, so it answers
``raised: true`` and comes back with what it was holding.

The two are not interchangeable, and that asymmetry is the point. ``raise_it``
is the named user gesture, so it reaches a closed frame; ``set_state`` is a
client adjusting a dock state, so it does not. Making a closed frame reachable
by anything else would put the user's decision back where DES-088 took it from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from punt_lux.display.replica import Frame, SceneReplica

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
        """Dock or undock the named frame and report what actually changed.

        ``minimized`` and its older spelling ``collapsed`` are the wire's whole
        vocabulary here, and the state they toggle runs between *on screen* and
        *docked*. A frame the user closed is in neither, and this command refuses
        it in **both** directions: undocking one would put back a window the user
        shut, and docking one would give it a pill they never asked for. Both are
        the same invariant broken — a closed frame is reachable only by a named
        user gesture, which is :meth:`raise_it` and nothing else.

        The refusal is loud. A caller cannot see a frame's visibility from the
        request it is making, so answering "nothing changed" would let it believe
        it had collapsed something; that silence is exactly how a content-side
        path came to undo the user's decision in the first place (DES-088).
        """
        frame = self._held(frame_id)
        docked = self._dock_request(kwargs)
        if docked is None:
            return {"frame_id": frame_id, "changed": {}}
        self._dock(frame, docked=docked)
        return {"frame_id": frame_id, "changed": {"minimized": frame.is_docked}}

    def _held(self, frame_id: str) -> Frame:
        """Return the named frame, or raise: this caller expected it to exist.

        Unlike :meth:`raise_it`, which answers rather than faults — a caller
        adjusting a named frame's dock state is not discovering whether one is up.
        """
        frame = self._scenes.frames.get(self._required(frame_id))
        if frame is None:
            msg = f"frame '{frame_id}' not found"
            raise LookupError(msg)
        return frame

    @staticmethod
    def _dock(frame: Frame, *, docked: bool) -> None:
        """Move a frame between on screen and the dock; a closed one refuses both.

        This is the whole policy, in one place: the dock state runs between those
        two values, and a frame the user closed is in neither. Only a named
        gesture brings that one back.
        """
        if frame.is_closed:
            msg = (
                f"frame '{frame.frame_id}' is closed; dock state applies only to a "
                "frame that is up. Use raise_frame to bring back a closed frame."
            )
            raise ValueError(msg)
        if docked:
            frame.minimize()
        else:
            frame.restore()

    def raise_it(self, frame_id: str = "", **_kwargs: Any) -> dict[str, Any]:
        """Bring the named frame to the front, from wherever it was put away.

        Restoring and focusing are one gesture, not two: a frame that took focus
        while still in the dock would have answered the request without becoming
        visible. It works identically on a frame that is on screen behind others,
        one the user docked, and one the user closed — the last being why closing
        is a visibility state and not the erasure of the frame. A frame this
        display does not hold answers ``raised: false``, so the caller learns to
        push one rather than having to read an error.
        """
        raised = self._scenes.raise_frame(self._required(frame_id))
        return {"frame_id": frame_id, "raised": raised}

    @staticmethod
    def _dock_request(kwargs: dict[str, Any]) -> bool | None:
        """Read the dock flag under either of the wire's two names for it.

        ``None`` when the caller named neither, which is a request that asks for
        nothing rather than a request to restore.
        """
        for key in ("minimized", "collapsed"):
            if key in kwargs:
                return bool(kwargs[key])
        return None

    @staticmethod
    def _required(frame_id: str) -> str:
        """Return ``frame_id``, or raise: every frame command names one frame."""
        if not frame_id:
            msg = "frame_id is required"
            raise ValueError(msg)
        return frame_id
