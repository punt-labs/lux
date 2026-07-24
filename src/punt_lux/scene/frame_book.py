"""FrameBook — the display's frame collection and its scene placement maps.

The frame-management half of the scene graph, split out of ``SceneManager`` so
that class keeps to the unframed scenes, per-scene widget state, and stale-id
notification. ``FrameBook`` owns the frames themselves, which frame each scene
lives in, and which client owns each framed scene, plus the frame's cascade
placement. It knows nothing about widget state or stale-id notification — those
are cross-cutting concerns the ``SceneManager`` layers on top, reacting to the
frames this book reports as created, placed, or removed.
"""

from __future__ import annotations

from itertools import chain, count
from typing import TYPE_CHECKING, Self, final

from punt_lux.scene.frame import Frame

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.protocol import SceneMessage

__all__ = ["FrameBook"]


@final
class FrameBook:
    """Owns the frames and the scene→frame / scene→owner maps."""

    _frames: dict[str, Frame]
    _focus_frame_id: str | None
    _scene_to_frame: dict[str, str]
    _scene_to_owner: dict[str, int]
    __slots__ = ("_focus_frame_id", "_frames", "_scene_to_frame", "_scene_to_owner")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = {}
        self._focus_frame_id = None
        self._scene_to_frame = {}
        self._scene_to_owner = {}
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def frames(self) -> dict[str, Frame]:
        """Return the frame map keyed by frame id."""
        return self._frames

    @property
    def focus_frame_id(self) -> str | None:
        """Return the frame that most recently took focus, if any."""
        return self._focus_frame_id

    @focus_frame_id.setter
    def focus_frame_id(self, value: str | None) -> None:
        self._focus_frame_id = value

    @property
    def scene_to_frame(self) -> dict[str, str]:
        """Return the map from scene id to the frame holding it."""
        return self._scene_to_frame

    @property
    def scene_to_owner(self) -> dict[str, int]:
        """Return the map from framed scene id to its owning client fd."""
        return self._scene_to_owner

    def frame_of_scene(self, scene_id: str) -> Frame | None:
        """Return the frame a scene lives in, or ``None`` if it is unframed."""
        frame_id = self._scene_to_frame.get(scene_id)
        return self._frames.get(frame_id) if frame_id is not None else None

    def framed_scenes(self) -> Iterator[SceneMessage]:
        """Yield every scene held by any frame."""
        return chain.from_iterable(f.scenes.values() for f in self._frames.values())

    # -- writes -------------------------------------------------------------

    def ensure(self, msg: SceneMessage, frame_id: str, owner_fd: int) -> Frame:
        """Return the scene's frame, creating it or refreshing its presentation.

        A new frame is built from the push and takes focus intent from the
        caller; an existing one gains the owner and adopts any title, flags, or
        layout the push carries.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            frame = Frame(
                frame_id=frame_id,
                title=msg.frame_title or msg.title or frame_id,
                owner_fds={owner_fd},
                scenes={},
                scene_order=[],
                cascade_index=self._next_cascade_index(),
                initial_size=msg.frame_size,
                flags=msg.frame_flags,
                layout=msg.frame_layout or "tab",
            )
            self._frames[frame_id] = frame
            return frame
        frame.owner_fds.add(owner_fd)
        if msg.frame_title:
            frame.title = msg.frame_title
        if msg.frame_flags is not None:
            frame.flags = msg.frame_flags
        if msg.frame_layout is not None:
            frame.layout = msg.frame_layout
        return frame

    def set_frame(self, scene_id: str, frame_id: str) -> None:
        """Record which frame now holds ``scene_id``."""
        self._scene_to_frame[scene_id] = frame_id

    def record_owner(self, scene_id: str, owner_fd: int) -> None:
        """Record the owning client fd for a framed scene."""
        self._scene_to_owner[scene_id] = owner_fd

    def forget_scene(self, scene_id: str) -> None:
        """Drop a scene's frame and owner mappings."""
        self._scene_to_frame.pop(scene_id, None)
        self._scene_to_owner.pop(scene_id, None)

    def pop_frame(self, frame_id: str) -> Frame | None:
        """Remove and return a frame, clearing focus if it held it."""
        frame = self._frames.pop(frame_id, None)
        if frame is not None and self._focus_frame_id == frame_id:
            self._focus_frame_id = None
        return frame

    def clear(self) -> None:
        """Drop every frame and its scene placement maps."""
        self._frames.clear()
        self._focus_frame_id = None
        self._scene_to_frame.clear()
        self._scene_to_owner.clear()

    def _next_cascade_index(self) -> int:
        """Return the smallest cascade index no live frame is using."""
        used = {f.cascade_index for f in self._frames.values()}
        return next(i for i in count() if i not in used)
