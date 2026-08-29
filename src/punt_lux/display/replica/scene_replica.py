"""The Display's replica of the scene graph the Hub sent it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.stale_ids import OnSceneReplacedFn, StaleIds
from punt_lux.display.replica.widget_state import WidgetState
from punt_lux.display.replica.widget_state_store import WidgetStateStore
from punt_lux.protocol import SceneMessage

__all__ = ["OnSceneReplacedFn", "SceneReplica"]


class SceneReplica:
    """Own the scene graph — framed scenes, widget state, stale-id notification.

    Every scene lives in a frame: the Hub synthesizes one at the render boundary
    when the caller names none, so there is no unframed scene storage. Frames and
    the scene→frame/owner maps belong to a composed :class:`FrameBook`, the
    per-scene widget state to a composed :class:`WidgetStateStore`, and the
    element-id bookkeeping and stale-id notification to a composed
    :class:`StaleIds`. Pure state machine: no ImGui, socket, or OpenGL.

    Two authorities write here and they must not write to each other's fields.
    A client owns *content* — which scene ids exist. The user owns *visibility* —
    where each frame is, which is why ``close`` and ``dispose_frame`` are two
    methods rather than one with a flag (DES-065 R8).
    """

    _book: FrameBook
    _widget_state: WidgetStateStore
    _stale: StaleIds

    def __new__(
        cls,
        *,
        on_scene_replaced: OnSceneReplacedFn,
    ) -> Self:
        self = super().__new__(cls)
        self._book = FrameBook()
        self._widget_state = WidgetStateStore()
        self._stale = StaleIds(self._book, on_scene_replaced)
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def frames(self) -> Mapping[str, Frame]:
        return self._book.frames

    @property
    def scene_count(self) -> int:
        """Total scenes held across every frame."""
        return sum(len(f.scenes) for f in self._book.frames.values())

    @property
    def frame_count(self) -> int:
        """Number of frames held, whatever visibility the user left each one in."""
        return len(self._book.frames)

    @property
    def active_scene_id(self) -> str | None:
        """The first painted frame's active tab — the display's 'current' scene.

        A docked or closed frame is not on screen, so its tab is not what the
        display is currently showing, however early it sits in the book.
        """
        for frame in self._book.on_screen():
            if frame.active_tab is not None:
                return frame.active_tab
        return None

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        return self._book.scene_to_frame

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        return self._book.scene_to_owner

    def request_focus(self, frame_id: str) -> None:
        """Mark ``frame_id`` to take window focus on its next render."""
        self._book.request_focus(frame_id)

    def consume_focus(self, frame_id: str) -> bool:
        """Return whether ``frame_id`` was awaiting focus, clearing the request."""
        return self._book.consume_focus(frame_id)

    def minimize(self, frame_id: str) -> None:
        """Dock the named frame. No-op if it is gone."""
        self._book.minimize(frame_id)

    def raise_frame(self, frame_id: str) -> bool:
        """Restore the named frame and ask for focus; report whether it is held.

        The whole gesture behind a user asking for a frame by name — an applet's
        menu entry, a dock pill, the Windows menu's closed-frame list. It works
        the same from every visibility, which is what makes a closed frame
        reachable again.
        """
        return self._book.restore(frame_id)

    def on_screen_frames(self) -> list[Frame]:
        """Return the frames the renderer paints."""
        return self._book.on_screen()

    def docked_frames(self) -> list[Frame]:
        """Return the frames the dock bar shows a pill for."""
        return self._book.docked()

    def closed_frames(self) -> list[Frame]:
        """Return the frames the user put away."""
        return self._book.closed()

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner."""
        self._book.reassign_scenes_of(departed_fd, orphan_fd)

    def scenes_to_purge(
        self, identifying_fd: int, manifest: frozenset[str]
    ) -> list[tuple[str, str]]:
        """Return every ``(frame_id, scene_id)`` pair a Hub manifest disowns.

        A scene qualifies when it is neither owned by ``identifying_fd`` nor
        named in ``manifest`` — an orphan from a prior Hub connection's death
        is swept by the same rule, since its owner is never the identifying
        fd. Read-only (DES-068): the caller drives the removal through
        :meth:`dismiss_framed_scene` per pair, closing a frame only when the
        pass empties it entirely.
        """
        owner = self._book.scene_to_owner
        return [
            (frame_id, scene_id)
            for frame_id, frame in self._book.frames.items()
            for scene_id in frame.scenes
            if owner.get(scene_id) != identifying_fd and scene_id not in manifest
        ]

    # -- public API --------------------------------------------------------

    def handle_framed_scene(self, msg: SceneMessage, owner_fd: int) -> None:
        """Route a scene into its frame, creating the frame if needed.

        An empty push removes the scene instead of creating or keeping a frame:
        the frame and its content appear and disappear together, never as a husk.
        """
        frame_id = msg.frame_id
        if not msg.elements:
            stale = self._book.frame_of_scene(msg.id) or self._book.frames.get(frame_id)
            if stale is not None and self.dismiss_framed_scene(stale, msg.id):
                self.dispose_frame(stale.frame_id)
            return
        frame = self._book.ensure(msg, frame_id, owner_fd)
        self.upsert_scene_in_frame(frame, msg)
        self._book.record_owner(msg.id, owner_fd)

    def upsert_scene_in_frame(self, frame: Frame, msg: SceneMessage) -> None:
        """Add or replace a scene within a frame.

        A push is a notification, not a window-raise. Whether the scene is new to
        the frame or a repaint of one already there, this writes content only: it
        never restores a frame the user docked or closed, never asks for focus,
        and never moves the tab the user is reading. The one tab it does write is
        a frame's first scene, which has no selection to take.
        """
        self._vacate_other_frame(frame, msg.id)
        is_new = msg.id not in frame.scenes
        old_scene = frame.scenes.get(msg.id)
        frame.scenes[msg.id] = msg
        if is_new:
            self._admit_new_scene(frame, msg.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def _vacate_other_frame(self, frame: Frame, scene_id: str) -> None:
        """Take ``scene_id`` out of any frame but this one: it lives in one at a time.

        The frame it leaves is disposed if that emptied it — a frame with no
        content is a husk, whatever the user had made of it.
        """
        old_frame = self._book.frame_of_scene(scene_id)
        if old_frame is None or old_frame.frame_id == frame.frame_id:
            return
        if self.dismiss_framed_scene(old_frame, scene_id):
            self.dispose_frame(old_frame.frame_id)

    def _admit_new_scene(self, frame: Frame, scene_id: str) -> None:
        """Place a scene the frame did not hold, writing content and nothing else.

        The active tab is the one thing here that could be called presentation,
        and it is written only when the frame has none — its first scene, which
        has no selection to take. A later arrival joins the strip and leaves the
        user reading what they were reading.
        """
        frame.scene_order.append(scene_id)
        self._widget_state.open(scene_id)
        if frame.active_tab is None:
            frame.active_tab = scene_id
        self._book.set_frame(scene_id, frame.frame_id)

    def resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in its frame, or None when no frame holds it."""
        frame = self._book.frame_of_scene(scene_id)
        return frame.scenes.get(scene_id) if frame is not None else None

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        """Remove a single scene from a frame.

        Return True if the frame is now empty (caller should close it
        with notifications).
        """
        dismissed = frame.scenes.pop(scene_id, None)
        if dismissed is not None:
            self._stale.notify(self._stale.in_tree(dismissed.elements))
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._widget_state.discard(scene_id)
        self._book.forget_scene(scene_id)
        if frame.active_tab == scene_id:
            frame.active_tab = frame.scene_order[0] if frame.scene_order else None
        return not frame.scenes

    def close(self, frame_id: str) -> list[str]:
        """Put a frame away, returning the element ids the caller should drain.

        The visibility half of the old ``close_frame``: the user shut a window,
        which says nothing about its content. The frame keeps its place in the
        book, its scenes stay *known*, its widget state and active tab survive,
        and the Hub is told nothing — no element was replaced, so nothing is
        stale to anyone but this Display.

        The ids come back unfiltered rather than through :meth:`_notify_stale`,
        precisely because the elements *do* survive: the caller drops its own
        queued interactions for them so a button in a window the user just shut
        cannot fire afterwards. Empty for a frame the book does not hold.
        """
        frame = self._book.close(frame_id)
        if frame is None:
            return []
        return sorted(self._stale.of_frame(frame))

    def dispose_frame(self, frame_id: str) -> list[str]:
        """Throw a frame out with all its scenes, returning the stale element IDs.

        The content half of the old ``close_frame``: the client says its content
        is gone — an empty push, a manifest purge, a TTL sweep, Clear All — so the
        frame leaves the book, its scene ids return to *unseen*, its widget state
        goes, and the ids no surviving scene holds are reported stale. It applies
        whatever visibility the user had left the frame in: a frame with no
        content is a husk, and a closed one is no exception.
        """
        frame = self._book.pop_frame(frame_id)
        if frame is None:
            return []
        removed_ids = self._stale.of_frame(frame)
        for scene_id in frame.scene_order:
            self._widget_state.discard(scene_id)
            self._book.forget_scene(scene_id)
        return self._stale.notify(removed_ids)

    def clear_all(self) -> None:
        """Remove all scenes, frames, and associated state."""
        self._book.clear()
        self._widget_state.clear()

    def widget_state_for(self, scene_id: str) -> WidgetState | None:
        """Return the WidgetState for a scene, or None."""
        return self._widget_state.get(scene_id)

    @property
    def widget_state_count(self) -> int:
        """Return the number of scenes holding widget state."""
        return len(self._widget_state)

    # -- scene-replacement helpers -----------------------------------------

    def _replace_scene_state(
        self, msg: SceneMessage, old_scene: SceneMessage | None = None
    ) -> None:
        """Drain stale IDs no other scene holds and discard their widget state.

        The event drain is survivor-aware: an id this scene dropped is drained only
        when no other framed scene holds it, so replacing one scene never cancels
        another's still-valid queued events.
        """
        if old_scene is None:
            return
        stale_ids = self._stale.dropped_by(msg, old_scene)
        self._stale.notify(stale_ids)
        self._widget_state.retire_elements(msg.id, stale_ids)
