"""FrameBook — the frame collection, keyed by
:class:`HubScopedKey <punt_lux.domain.hub_scoped_key.HubScopedKey>` so two
Hubs minting the identical id can never clobber one another. Scene placement
is a composed :class:`SceneIndex`, not this class's own state."""

from __future__ import annotations

from itertools import chain, count
from types import MappingProxyType
from typing import TYPE_CHECKING, Self, final

from punt_lux.display.replica.focus_request import FocusRequest
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.display.replica.scene_index import SceneIndex
from punt_lux.domain.identity import HubId, HubScopedKey, HubScopedStore

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from punt_lux.protocol import SceneMessage

__all__ = ["FrameBook"]

# A content write's own-Hub default; production always resolves the real HubId.
_NO_HUB = HubId.stub()


@final
class FrameBook:
    """Owns the frames, all keyed by :class:`HubScopedKey` so two Hubs
    minting the identical id never merge. Scene placement is delegated to
    a composed :class:`SceneIndex`."""

    _frames: HubScopedStore[Frame]
    _focus: FocusRequest
    _scene_index: SceneIndex
    __slots__ = ("_focus", "_frames", "_scene_index")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frames = HubScopedStore()
        self._focus = FocusRequest()
        self._scene_index = SceneIndex()
        return self

    @property
    def frames(self) -> Mapping[str, Frame]:
        """Flattened, read-only view of every frame; a collision is last-write-
        wins. Use :meth:`frame` for a collision-safe write path."""
        return MappingProxyType(self._frames.flatten())

    def frame(self, frame_id: str, hub: HubId = _NO_HUB) -> Frame | None:
        """Return the frame ``(hub, frame_id)`` addresses, or ``None`` --
        never another Hub's identically-named frame."""
        return self._frames.get(HubScopedKey(hub, frame_id))

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        return self._scene_index.scene_to_frame

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        return self._scene_index.scene_to_owner

    def frame_of_scene(self, scene_id: str) -> Frame | None:
        """The flattened, best-effort frame a scene lives in, or ``None``."""
        frame_id = self._scene_index.scene_to_frame.get(scene_id)
        return self._frames.flatten().get(frame_id) if frame_id is not None else None

    def frame_of_hub_scene(self, key: HubScopedKey) -> Frame | None:
        """The frame ``key`` lives in, resolved by its owning Hub only."""
        frame_id = self._scene_index.frame_id_of(key)
        if frame_id is None:
            return None
        return self._frames.get(HubScopedKey(key.hub, frame_id))

    def scene_to_frame_for_hub(self, hub: HubId) -> Iterator[tuple[str, str]]:
        return self._scene_index.for_hub(hub)

    def scene_hubs(self) -> frozenset[HubId]:
        return self._scene_index.hubs()

    def framed_scenes(self) -> Iterator[SceneMessage]:
        """Yield every scene held by any frame."""
        return chain.from_iterable(f.scenes.values() for f in self._frames.values())

    def on_screen(self) -> list[Frame]:
        """Return the frames that are painted, in insertion order."""
        return [f for f in self._frames.values() if f.is_on_screen]

    def docked(self) -> list[Frame]:
        """Return the frames the dock bar shows a pill for."""
        return [f for f in self._frames.values() if f.is_docked]

    def closed(self) -> list[Frame]:
        """Return the frames the user put away, which only a gesture brings back."""
        return [f for f in self._frames.values() if f.is_closed]

    def ensure(self, msg: SceneMessage, owner_fd: int, hub: HubId = _NO_HUB) -> Frame:
        """The scene's frame, creating it or refreshing its presentation --
        resolved by ``(hub, msg.frame_id)``, so a second Hub minting the
        identical frame id never joins the first's frame."""
        frame = self._frames.get(HubScopedKey(hub, msg.frame_id))
        if frame is None:
            return self._born(msg, owner_fd, hub)
        frame.owner_fds.add(owner_fd)
        self._adopt_presentation(frame, msg)
        return frame

    def _born(self, msg: SceneMessage, owner_fd: int, hub: HubId) -> Frame:
        """Build and hold a frame for a scene naming one that does not exist yet."""
        frame_id = msg.frame_id
        frame = Frame(
            hub=hub,
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
        self._frames.put(HubScopedKey(hub, frame_id), frame)
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

    def hub_count(self) -> int:
        return self._frames.hub_count()

    def __len__(self) -> int:
        return len(self._frames)

    def request_focus(self, frame_id: str) -> None:
        """Mark ``frame_id`` to take window focus on its next render."""
        self._focus.ask(frame_id)

    def consume_focus(self, frame_id: str) -> bool:
        """Return whether ``frame_id`` was awaiting focus, spending the request."""
        return self._focus.consume(frame_id)

    def minimize(self, frame_id: str) -> None:
        """Dock the named frame. No-op if it is gone -- a visibility gesture,
        so this resolves through the flattened view like :attr:`frames`."""
        frame = self._frames.flatten().get(frame_id)
        if frame is not None:
            frame.minimize()

    def close(self, frame_id: str) -> Frame | None:
        """Put the named frame away and return it, or ``None`` if gone."""
        frame = self._frames.flatten().get(frame_id)
        if frame is None:
            return None
        frame.close()
        self._focus.release(frame_id)
        return frame

    def restore(self, frame_id: str) -> bool:
        """Bring a frame on screen and ask for focus; report whether held."""
        frame = self._frames.flatten().get(frame_id)
        if frame is None:
            return False
        frame.restore()
        self._focus.ask(frame_id)
        return True

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner,
        or to ``orphan_fd`` when none remains. Scenes persist; never dismissed.
        Each frame's own Hub scopes its reassignment, so a second Hub's
        identically-named scene is never a candidate."""
        for frame in self._frames.values():
            frame.owner_fds.discard(departed_fd)
            heir = next(iter(frame.owner_fds), orphan_fd)
            scenes = frozenset(frame.scene_order)
            self._scene_index.reassign_owner(frame.hub, departed_fd, heir, scenes)

    def set_frame(self, key: HubScopedKey, frame_id: str) -> None:
        """Record which Hub-scoped scene now holds ``frame_id``."""
        self._scene_index.set_frame(key, frame_id)

    def record_owner(self, key: HubScopedKey, owner_fd: int) -> None:
        """Record the owning client fd for a Hub-scoped framed scene."""
        self._scene_index.record_owner(key, owner_fd)

    def forget_scene(self, scene_id: str) -> None:
        """Drop a scene's frame and owner mappings, across every Hub."""
        self._scene_index.forget_scene(scene_id)

    def forget_scene_from(
        self, scene_id: str, frame_id: str, hub: HubId = _NO_HUB
    ) -> None:
        """Drop exactly the ``(hub, scene_id)`` -> ``frame_id`` mapping --
        resolved by the exact key, never a bare-value search that could
        also match a second Hub's identically-valued entry."""
        self._scene_index.forget_scene_from(scene_id, frame_id, hub)

    def forget_scenes_of_frame(self, frame_id: str, hub: HubId = _NO_HUB) -> None:
        """Drop every ``hub``-owned entry pointing at ``frame_id`` -- the
        whole-frame :meth:`forget_scene_from`, scoped by owner so a second
        Hub's identically-named frame is never a candidate."""
        self._scene_index.forget_scenes_of_frame(frame_id, hub)

    def pop_frame(self, frame_id: str, hub: HubId = _NO_HUB) -> Frame | None:
        """Remove and return a frame, clearing focus if it held it."""
        frame = self._frames.remove(HubScopedKey(hub, frame_id))
        if frame is not None:
            self._focus.release(frame_id)
        return frame

    def clear(self) -> None:
        """Drop every frame and its scene placement maps."""
        self._frames = HubScopedStore()
        self._focus.clear()
        self._scene_index.clear()

    def _next_cascade_index(self) -> int:
        """Return the smallest cascade index no live frame is using."""
        used = {f.cascade_index for f in self._frames.values()}
        return next(i for i in count() if i not in used)
