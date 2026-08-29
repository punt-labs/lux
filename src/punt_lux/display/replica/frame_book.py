"""FrameBook — the display's frame collection and its scene placement maps.

The frame-management half of the scene graph, split out of ``SceneReplica`` so
that class keeps to per-scene widget state and stale-id notification.
``FrameBook`` owns the frames themselves, which frame each scene
lives in, and which client owns each framed scene, plus the frame's cascade
placement. It knows nothing about widget state or stale-id notification — those
are cross-cutting concerns the ``SceneReplica`` layers on top, reacting to the
frames this book reports as created, placed, or removed.
"""

from __future__ import annotations

from itertools import chain, count
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.focus_request import FocusRequest
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from punt_lux.protocol import SceneMessage

__all__ = ["FrameBook"]


@final
class FrameBook:
    """Owns the frames and the scene→frame / scene→owner maps."""

    _frames: dict[str, Frame]
    _focus: FocusRequest
    _scene_to_frame: dict[str, str]
    _scene_to_owner: dict[str, int]
    __slots__ = ("_focus", "_frames", "_scene_to_frame", "_scene_to_owner")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = {}
        self._focus = FocusRequest()
        self._scene_to_frame = {}
        self._scene_to_owner = {}
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def frames(self) -> Mapping[str, Frame]:
        """Return a read-only view of the frame map keyed by frame id.

        The renderer reads and renders the frames but never adds or removes one;
        the view keeps that guarantee at the boundary. (The ``Frame`` objects it
        yields are still mutable — their own methods own their internal state.)
        """
        return MappingProxyType(self._frames)

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        """Return a read-only view of scene id → the frame holding it."""
        return MappingProxyType(self._scene_to_frame)

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        """Return a read-only view of framed scene id → its owning client fd."""
        return MappingProxyType(self._scene_to_owner)

    def frame_of_scene(self, scene_id: str) -> Frame | None:
        """Return the frame a scene lives in, or ``None`` if no frame holds it."""
        frame_id = self._scene_to_frame.get(scene_id)
        return self._frames.get(frame_id) if frame_id is not None else None

    def framed_scenes(self) -> Iterator[SceneMessage]:
        """Yield every scene held by any frame."""
        return chain.from_iterable(f.scenes.values() for f in self._frames.values())

    # -- visibility queries the renderer asks instead of testing a flag -----

    def on_screen(self) -> list[Frame]:
        """Return the frames that are painted, in insertion order."""
        return [f for f in self._frames.values() if f.is_on_screen]

    def docked(self) -> list[Frame]:
        """Return the frames the dock bar shows a pill for."""
        return [f for f in self._frames.values() if f.is_docked]

    def closed(self) -> list[Frame]:
        """Return the frames the user put away, which only a gesture brings back."""
        return [f for f in self._frames.values() if f.is_closed]

    # -- writes -------------------------------------------------------------

    def ensure(self, msg: SceneMessage, frame_id: str, owner_fd: int) -> Frame:
        """Return the scene's frame, creating it or refreshing its presentation.

        A new frame is born on screen — the Display's new-frame policy, and the
        one place a content event may set a visibility, because there is no prior
        value to override. Being born on screen is not a raise: no focus is
        requested, no other frame is disturbed, and the window's own shown state
        is untouched. An existing frame keeps whatever visibility the user left it
        in, and gains only the owner and any title, flags, or layout the push
        carries.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            return self._born(msg, frame_id, owner_fd)
        frame.owner_fds.add(owner_fd)
        self._adopt_presentation(frame, msg)
        return frame

    def _born(self, msg: SceneMessage, frame_id: str, owner_fd: int) -> Frame:
        """Build and hold a frame for a scene naming one that does not exist yet."""
        frame = Frame(
            frame_id=frame_id,
            title=msg.frame_title or msg.title or frame_id,
            owner_fds={owner_fd},
            scenes={},
            scene_order=[],
            visibility=FrameVisibility.ON_SCREEN,
            cascade_index=self._next_cascade_index(),
            initial_size=msg.frame_size,
            flags=msg.frame_flags,
            layout=msg.frame_layout or "tab",
        )
        self._frames[frame_id] = frame
        return frame

    @staticmethod
    def _adopt_presentation(frame: Frame, msg: SceneMessage) -> None:
        """Take the title, flags and layout a push carries, keeping what it omits.

        Presentation the client declares, unlike the visibility the user owns: an
        omitted field means "leave it", never "reset it".
        """
        if msg.frame_title:
            frame.title = msg.frame_title
        if msg.frame_flags is not None:
            frame.flags = msg.frame_flags
        if msg.frame_layout is not None:
            frame.layout = msg.frame_layout

    def request_focus(self, frame_id: str) -> None:
        """Mark ``frame_id`` to take window focus on its next render."""
        self._focus.ask(frame_id)

    def consume_focus(self, frame_id: str) -> bool:
        """Return whether ``frame_id`` was awaiting focus, spending the request."""
        return self._focus.consume(frame_id)

    def minimize(self, frame_id: str) -> None:
        """Dock the named frame. No-op if it is gone."""
        frame = self._frames.get(frame_id)
        if frame is not None:
            frame.minimize()

    def close(self, frame_id: str) -> Frame | None:
        """Put the named frame away and return it, or ``None`` if it is gone.

        A visibility write and nothing else: the frame stays in the book with its
        scenes, so a later :meth:`restore` has something to act on and a later
        push still reads as a repeat rather than an arrival. Its focus request
        goes, because a frame that is not painted cannot take focus.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            return None
        frame.close()
        self._focus.release(frame_id)
        return frame

    def restore(self, frame_id: str) -> bool:
        """Bring a frame back on screen and ask for focus; report whether it is held.

        Restoring and focusing are one gesture, not two: a frame that took focus
        while still put away would have answered the request without becoming
        visible. Enabled from every visibility, which is what makes a closed frame
        reachable again.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            return False
        frame.restore()
        self._focus.ask(frame_id)
        return True

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner.

        The client leaves every frame it co-owned; each scene it owned passes to
        another owner of that frame, or to ``orphan_fd`` when none remains. Scenes
        persist across a disconnect --- they are never dismissed here.
        """
        for frame in self._frames.values():
            frame.owner_fds.discard(departed_fd)
            self._reassign_within(frame, departed_fd, orphan_fd)

    def _reassign_within(self, frame: Frame, departed_fd: int, orphan_fd: int) -> None:
        """Pass every scene ``departed_fd`` owned in ``frame`` to one surviving heir.

        The heir is settled once for the frame rather than per scene: the departed
        fd has already left ``owner_fds``, so every scene it held in this frame
        goes to the same survivor, and to ``orphan_fd`` when there is none.
        """
        heir = next(iter(frame.owner_fds), orphan_fd)
        for scene_id in frame.scene_order:
            if self._scene_to_owner.get(scene_id) == departed_fd:
                self._scene_to_owner[scene_id] = heir

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
        if frame is not None:
            self._focus.release(frame_id)
        return frame

    def clear(self) -> None:
        """Drop every frame and its scene placement maps."""
        self._frames.clear()
        self._focus.clear()
        self._scene_to_frame.clear()
        self._scene_to_owner.clear()

    def _next_cascade_index(self) -> int:
        """Return the smallest cascade index no live frame is using."""
        used = {f.cascade_index for f in self._frames.values()}
        return next(i for i in count() if i not in used)
