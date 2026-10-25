"""BatchSender -- pushes one drained batch to the display, and what it was sending.

The replicator's worker drains a batch and hands it here. A send that fails raises
out of :meth:`BatchSender.push`; what the failure should be charged to is read back
afterwards: the scenes that were in flight (:attr:`suspect`) and the dial they went
out on (:attr:`dial`). Both are set immediately before each send that can raise, so
they are exactly what that send risked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.crash_attribution import CrashAttribution
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.dirty_signal import DrainedBatch
    from punt_lux.domain.hub.frame_owner_facts import FrameOwnerFactsReader
    from punt_lux.domain.hub.replicator_ports import (
        CallbackMenuReader,
        ClientProvider,
        DisplaySender,
        MenuReader,
    )
    from punt_lux.domain.hub.scene_snapshot import SceneReader
    from punt_lux.domain.ids import SceneId

__all__ = ["BatchSender"]

# The isolation-mode roundtrip budget: after each singleton send, wait this
# long for the display to ack a ping -- long enough under load, short enough
# that a wedged display trips recovery quickly and blames the real crasher.
_PROBE_TIMEOUT_SECONDS = 1.0


@final
class BatchSender:
    """Sends a batch's menus and scenes, remembering what a failure would blame."""

    _reader: SceneReader
    _menu_reader: MenuReader
    _callback_reader: CallbackMenuReader
    _clients: ClientProvider
    _attribution: CrashAttribution
    _owner_facts: FrameOwnerFactsReader
    _suspect: frozenset[SceneId]
    # The dial the attempt in progress last sent on: what a failure asks to drop.
    _dial: DialGeneration | None
    __slots__ = (
        "_attribution",
        "_callback_reader",
        "_clients",
        "_dial",
        "_menu_reader",
        "_owner_facts",
        "_reader",
        "_suspect",
    )

    def __new__(
        cls,
        reader: SceneReader,
        menu_reader: MenuReader,
        callback_reader: CallbackMenuReader,
        clients: ClientProvider,
        attribution: CrashAttribution,
        owner_facts: FrameOwnerFactsReader,
    ) -> Self:
        self = super().__new__(cls)
        self._reader = reader
        self._menu_reader = menu_reader
        self._callback_reader = callback_reader
        self._clients = clients
        self._attribution = attribution
        self._owner_facts = owner_facts
        self._suspect = frozenset()
        self._dial = None
        return self

    @property
    def suspect(self) -> frozenset[SceneId]:
        """The scenes in flight when the last send was made."""
        return self._suspect

    @property
    def dial(self) -> DialGeneration | None:
        """The dial the last send went out on; ``None`` if none was had."""
        return self._dial

    def push(self, batch: DrainedBatch) -> tuple[SceneId, ...]:
        """Send the batch and return the scenes it found empty, for later reclaim.

        Quarantined scenes are filtered before either send path runs (Invariant
        1: a quarantined scene is never replicated), enforced here regardless
        of what queued it. A menu send is attributed to the *empty* suspect
        set: a menu-caused crash is not a scene-caused one, so blaming the
        whole batch would reintroduce isolation's false-positive class — the
        empty suspect still trips isolation, so later scene sends are singles.
        """
        self._dial = None
        scenes = frozenset(
            s for s in batch.scenes if not self._attribution.is_quarantined(s)
        )
        if batch.menus_dirty:
            self._suspect = frozenset()
            # Read the agent bar and the live sessions fresh, so the newest menu
            # state wins even if a change landed after this batch was drained.
            bar = self._menu_reader.wire_snapshot()
            callback_menus = self._callback_reader.callback_menu_wire()
            sender = self._sender()
            sender.set_menu([dict(menu) for menu in bar])
            sender.set_callback_menus(callback_menus)
        if self._attribution.mode == "isolating":
            return self._isolating(scenes)
        return self._batching(scenes)

    def _batching(self, scenes: frozenset[SceneId]) -> tuple[SceneId, ...]:
        """Send every scene as one coalesced batch — the suspect set on a death.

        A send failure anywhere aborts the whole method, so the suspect is set
        once, to the whole batch: a socket-level failure can't tell which of
        several already-accepted sends actually crashed the Display.
        """
        self._suspect = scenes
        # Each ``_send_scene`` sends and reports whether the scene was empty; the
        # comprehension keeps the empties as reclaim candidates.
        return tuple(scene for scene in scenes if self._send_scene(scene))

    def _isolating(self, scenes: frozenset[SceneId]) -> tuple[SceneId, ...]:
        """Send every scene alone, with a liveness probe between sends.

        The suspect narrows to the singleton before each send, and a synchronous
        ``probe_alive`` runs *after* each send, *before* the next — without it,
        scene N's crash surfaces only as a broken pipe on the *next* write,
        attributing to innocent N+1. The probe forces the crash to surface while
        the suspect is still {N}. A failed probe raises OSError, which the
        replicator hands to recovery.
        """
        emptied: list[SceneId] = []
        for scene_id in scenes:
            self._suspect = frozenset({scene_id})
            if self._send_scene(scene_id):
                emptied.append(scene_id)
            if not self._sender().probe_alive(_PROBE_TIMEOUT_SECONDS):
                msg = f"display did not ack probe after sending {scene_id!r}"
                raise OSError(msg)
        return tuple(emptied)

    def _sender(self) -> DisplaySender:
        """The display's send port, noting the dial a failure of it would name."""
        link = self._clients.get()
        self._dial = link.dial
        return link.requests

    def _send_scene(self, scene_id: SceneId) -> bool:
        """Send a copy of the scene; return whether it was empty (a reclaim candidate).

        The store returns a snapshot whose roots are already copied out, so the
        send runs with no store lock held. An empty scene blanks its own frame;
        owner facts resolve fresh here (like the menu bar) and ``None`` leaves
        the display's cached snapshot alone rather than blanking it.
        """
        snapshot = self._reader.snapshot(scene_id)
        snapshot.push(self._sender(), self._owner_facts)
        return snapshot.is_empty
