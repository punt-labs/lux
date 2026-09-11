"""FrameBook — the display's frame collection and its scene placement maps.

Split out of ``SceneReplica``. The scene-placement maps compose
:class:`HubScopedStore <punt_lux.domain.hub_scoped_store.HubScopedStore>`
so two Hubs minting the identical scene id can never clobber one another.
"""

from __future__ import annotations

from itertools import chain, count
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.focus_request import FocusRequest
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.domain.identity import HubScopedKey, HubScopedStore

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from punt_lux.domain.identity import HubId
    from punt_lux.protocol import SceneMessage

__all__ = ["FrameBook"]


@final
class FrameBook:
    """Owns the frames and the scene→frame / scene→owner maps."""

    _frames: dict[str, Frame]
    _focus: FocusRequest
    _scene_to_frame: HubScopedStore[str]
    _scene_to_owner: HubScopedStore[int]
    __slots__ = ("_focus", "_frames", "_scene_to_frame", "_scene_to_owner")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = {}
        self._focus = FocusRequest()
        self._scene_to_frame = HubScopedStore()
        self._scene_to_owner = HubScopedStore()
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def frames(self) -> Mapping[str, Frame]:
        """Return a read-only view of the frame map keyed by frame id --
        the ``Frame`` objects it yields are still mutable."""
        return MappingProxyType(self._frames)

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        """Return a flat scene id → frame id view, merged across every Hub --
        a collision resolves last-write-wins, per :meth:`HubScopedStore.flatten`."""
        return MappingProxyType(self._scene_to_frame.flatten())

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        """Return a flat scene id → owner fd view, merged across every Hub."""
        return MappingProxyType(self._scene_to_owner.flatten())

    def frame_of_scene(self, scene_id: str) -> Frame | None:
        """Return the frame a scene lives in, or ``None`` if no frame holds it."""
        frame_id = self.scene_to_frame.get(scene_id)
        return self._frames.get(frame_id) if frame_id is not None else None

    def frame_of_hub_scene(self, key: HubScopedKey) -> Frame | None:
        """Return the frame ``key`` lives in, resolved by its owning Hub --
        unlike :meth:`frame_of_scene`, never another Hub's same-named entry."""
        frame_id = self._scene_to_frame.get(key)
        return self._frames.get(frame_id) if frame_id is not None else None

    def scenes_of_hub(self, hub: HubId) -> Iterator[tuple[str, str]]:
        """Yield every ``(scene_id, frame_id)`` pair ``hub`` currently owns."""
        return self._scene_to_frame.for_hub(hub)

    def scene_to_frame_entries(self) -> Iterator[tuple[HubScopedKey, str]]:
        """Yield every scene→frame entry with its full Hub-scoped key."""
        return self._scene_to_frame.entries()

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
        """Return the scene's frame, creating it on screen or refreshing its
        presentation -- an existing frame keeps whatever visibility the user
        left it in."""
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
        """Take the title, flags and layout a push carries; an omitted field
        means "leave it", never "reset it"."""
        if msg.frame_title:
            frame.title = msg.frame_title
        if msg.frame_flags is not None:
            frame.hints.flags = msg.frame_flags
        if msg.frame_layout is not None:
            frame.hints.layout = msg.frame_layout

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

        A visibility write only: scenes stay, so a later push still reads
        as a repeat. Its focus request goes, since it is no longer painted.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            return None
        frame.close()
        self._focus.release(frame_id)
        return frame

    def restore(self, frame_id: str) -> bool:
        """Bring a frame on screen and ask for focus; report whether it is held.

        One gesture, not two, and works from every visibility -- what makes
        a closed frame reachable again.
        """
        frame = self._frames.get(frame_id)
        if frame is None:
            return False
        frame.restore()
        self._focus.ask(frame_id)
        return True

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner,
        or to ``orphan_fd`` when none remains. Scenes persist; never dismissed."""
        for frame in self._frames.values():
            frame.owner_fds.discard(departed_fd)
            self._reassign_within(frame, departed_fd, orphan_fd)

    def _reassign_within(self, frame: Frame, departed_fd: int, orphan_fd: int) -> None:
        """Pass every scene ``departed_fd`` owned in ``frame`` to one heir."""
        heir = next(iter(frame.owner_fds), orphan_fd)
        scenes = frozenset(frame.scene_order)
        self._scene_to_owner.reassign_value(departed_fd, heir, scenes)

    def set_frame(self, key: HubScopedKey, frame_id: str) -> None:
        """Record which Hub-scoped scene now holds ``frame_id``."""
        self._scene_to_frame.put(key, frame_id)

    def record_owner(self, key: HubScopedKey, owner_fd: int) -> None:
        """Record the owning client fd for a Hub-scoped framed scene."""
        self._scene_to_owner.put(key, owner_fd)

    def forget_scene(self, scene_id: str) -> None:
        """Drop a scene's frame and owner mappings, across every Hub."""
        self._scene_to_frame.remove_all(scene_id)
        self._scene_to_owner.remove_all(scene_id)

    def forget_scene_from(self, scene_id: str, frame_id: str) -> None:
        """Drop exactly the mapping placing ``scene_id`` in ``frame_id`` --
        another Hub's same-named scene elsewhere survives untouched."""
        for key in self._scene_to_frame.remove_matching(scene_id, frame_id):
            self._scene_to_owner.remove(key)

    def forget_scenes_of_frame(self, frame_id: str) -> None:
        """Drop every entry pointing at ``frame_id``, across every Hub that
        placed a scene there -- the whole-frame :meth:`forget_scene_from`."""
        for key in self._scene_to_frame.keys_for_value(frame_id):
            self._scene_to_frame.remove(key)
            self._scene_to_owner.remove(key)

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
        self._scene_to_frame = HubScopedStore()
        self._scene_to_owner = HubScopedStore()

    def _next_cascade_index(self) -> int:
        """Return the smallest cascade index no live frame is using."""
        used = {f.cascade_index for f in self._frames.values()}
        return next(i for i in count() if i not in used)
