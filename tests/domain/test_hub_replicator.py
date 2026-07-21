"""HubReplicator — the single-writer send, recovery, clear-first, and liveness.

These drive the real worker thread against a real ``HubDisplay`` store and fake
display ports, so every partition exercises the shipped mechanism rather than a
stub: clear-first ordering (CL3/E1), the two send failures and their recovery
(P3/P4, K, RC), no lost update across respawn (K2/K4/RC3), the torn-read the
store lock prevents (S2), and agent-path liveness while the worker is stuck
sending (P6).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Self

import pytest

from punt_lux.domain.hub.dirty_signal import DrainedBatch
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.replicator import (
    _BASE_BACKOFF_SECONDS,
    HubReplicator,
)
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from punt_lux.domain.element import Element as WireElement

_CONN = ConnectionId("repl-conn")


def _seed(store: HubDisplay, scene: str, content: str = "x") -> SceneId:
    """Install one owned root in ``scene`` and record a framed presentation."""
    scene_id = SceneId(scene)
    store.register_client(_CONN)
    store.replace_scene(
        _CONN, scene_id, [TextElement(id=f"{scene}-root", content=content)]
    )
    store.record_presentation(scene_id, ScenePresentation(frame_id=scene))
    return scene_id


class _FakeSender:
    """Records sends; can be armed to fail once or block until released.

    A ``_fail`` exception is raised on the next send and then cleared, so a
    healed connection (after the provider drops it) succeeds — modelling a fresh
    display. ``_gate`` blocks a send until the test releases it, modelling a slow
    send that has not yet hit its time limit.
    """

    shows: list[str]
    frames: list[str | None]
    roots: list[list[WireElement]]
    clears: int
    menus: list[list[dict[str, object]]]
    registered_items: list[list[dict[str, object]]]
    timeline: list[str]
    _fail: OSError | None
    _fail_scene: tuple[str, OSError] | None
    _gate: threading.Event | None
    _lock: threading.Lock
    _sent: threading.Event
    _entered: threading.Event
    __slots__ = (
        "_entered",
        "_fail",
        "_fail_scene",
        "_gate",
        "_lock",
        "_sent",
        "clears",
        "frames",
        "menus",
        "registered_items",
        "roots",
        "shows",
        "timeline",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.shows = []
        self.frames = []
        self.roots = []
        self.clears = 0
        self.menus = []
        self.registered_items = []
        self.timeline = []
        self._fail = None
        self._fail_scene = None
        self._gate = None
        self._lock = threading.Lock()
        self._sent = threading.Event()
        self._entered = threading.Event()
        return self

    def arm_failure(self, exc: OSError) -> None:
        self._fail = exc

    def fail_on_scene(self, scene_id: str, exc: OSError) -> None:
        """Raise once when a specific scene is sent, leaving other sends clean."""
        self._fail_scene = (scene_id, exc)

    def block_next(self, gate: threading.Event) -> None:
        self._gate = gate

    def wait_sent(self, timeout: float) -> bool:
        return self._sent.wait(timeout)

    def wait_entered(self, timeout: float) -> bool:
        """Block until a send has entered the guard — a race-free handshake.

        Set the instant the worker reaches the send, before it parks on the
        gate, so a test can act while the worker is provably inside the send
        rather than after a hopeful sleep.
        """
        return self._entered.wait(timeout)

    def _guard(self) -> None:
        self._entered.set()
        if self._gate is not None:
            gate, self._gate = self._gate, None
            gate.wait(timeout=5.0)
        if self._fail is not None:
            exc, self._fail = self._fail, None
            raise exc

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        frame_id: str | None = None,
        **_kwargs: object,
    ) -> None:
        self._guard()
        if self._fail_scene is not None and self._fail_scene[0] == scene_id:
            _, exc = self._fail_scene
            self._fail_scene = None
            raise exc
        with self._lock:
            self.shows.append(scene_id)
            self.frames.append(frame_id)
            self.roots.append(list(elements))
            self.timeline.append(f"show:{scene_id}")
        self._sent.set()

    def clear_async(self) -> None:
        self._guard()
        with self._lock:
            self.clears += 1
            self.timeline.append("clear")
        self._sent.set()

    def set_menu(self, menus: list[dict[str, object]]) -> None:
        self._guard()
        with self._lock:
            self.menus.append(list(menus))
            self.timeline.append("menu")
        self._sent.set()

    def set_registered_items(self, items: list[dict[str, object]]) -> None:
        with self._lock:
            self.registered_items.append(list(items))


class _FakeProvider:
    """Hands out one sender; ``drop`` heals it, modelling a reconnect."""

    _sender: _FakeSender
    drops: int
    __slots__ = ("_sender", "drops")

    def __new__(cls, sender: _FakeSender) -> Self:
        self = super().__new__(cls)
        self._sender = sender
        self.drops = 0
        return self

    def get(self) -> _FakeSender:
        return self._sender

    def drop(self) -> None:
        self.drops += 1


class _FakeLifecycle:
    """Records reap/ensure calls and their order; ``ensure`` can be armed to fail.

    An armed ``ensure`` raises once and then clears, modelling a display that
    cannot be respawned on the first try but recovers on a retry.
    """

    calls: list[str]
    _ensure_fail: Exception | None
    __slots__ = ("_ensure_fail", "calls")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.calls = []
        self._ensure_fail = None
        return self

    def arm_ensure_failure(self, exc: Exception) -> None:
        self._ensure_fail = exc

    def reap(self, timeout: float = 2.0) -> None:
        self.calls.append("reap")

    def ensure(self, timeout: float = 5.0) -> Path:
        self.calls.append("ensure")
        if self._ensure_fail is not None:
            exc, self._ensure_fail = self._ensure_fail, None
            raise exc
        return Path("/tmp/lux-test.sock")


def _replicator(
    store: HubDisplay,
) -> tuple[HubReplicator, _FakeSender, _FakeProvider, _FakeLifecycle]:
    sender = _FakeSender()
    provider = _FakeProvider(sender)
    lifecycle = _FakeLifecycle()
    return HubReplicator(store.reader, provider, lifecycle), sender, provider, lifecycle


def test_a_dirty_scene_is_sent_to_the_display() -> None:
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        assert sender.shows == ["s1"]
    finally:
        repl.stop()


def test_menu_state_is_pushed_to_the_display() -> None:
    # A menu change is Hub-owned: the operation marks the bar and tool items and
    # this one background writer sends both — the agent bar via set_menu and the
    # World-menu items via set_registered_items — the same mark-and-replicate path
    # a scene takes.
    store = HubDisplay()
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_menus(
            [{"label": "File", "items": []}], [{"label": "Run", "id": "run"}]
        )
        assert sender.wait_sent(2.0)
        assert sender.menus == [[{"label": "File", "items": []}]]
        assert sender.registered_items == [[{"label": "Run", "id": "run"}]]
    finally:
        repl.stop()


def test_a_dead_peer_recovery_re_marks_the_menu_state() -> None:
    # A respawned display must get the menu state re-pushed, like the live scenes.
    store = HubDisplay()
    repl, sender, _provider, _lifecycle = _replicator(store)
    sender.arm_failure(OSError("EPIPE"))
    repl.start()
    try:
        repl.mark_menus([{"label": "File", "items": []}], [])
        assert sender.wait_sent(2.0)
        # The first send failed and was healed; the re-marked bar is sent again.
        assert sender.menus == [[{"label": "File", "items": []}]]
    finally:
        repl.stop()


def test_the_resend_carries_the_recorded_frame() -> None:
    # A scene shown into a differently-named frame is resent into that frame,
    # never hoisted into a frame named for itself.
    store = HubDisplay()
    scene = SceneId("s1")
    store.register_client(_CONN)
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="x")])
    store.record_presentation(scene, ScenePresentation(frame_id="hello-frame"))
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        assert sender.frames == ["hello-frame"]
    finally:
        repl.stop()


def test_the_resend_carries_the_stores_current_value() -> None:
    # The worker snapshots the store at send time, so a mutation that lands
    # before the send is carried, not a stale copy.
    store = HubDisplay()
    scene = _seed(store, "s1", content="first")
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="second")])
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        (pushed,) = sender.roots
        assert [e.to_dict()["content"] for e in pushed] == ["second"]
    finally:
        repl.stop()


def test_clear_is_sent_before_the_batch() -> None:
    # CL3 / E1: a clear coalesced with a show must leave the scene on screen —
    # blank first, then repaint, never the reverse.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_cleared()
        repl.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        # Give the batch send a moment to follow the clear.
        for _ in range(50):
            if sender.shows:
                break
            threading.Event().wait(0.01)
        # Blank first, then repaint — never the reverse.
        assert sender.timeline == ["clear", "show:s1"]
    finally:
        repl.stop()


def test_a_wedged_display_is_reaped_respawned_and_repainted() -> None:
    # P3 / K1 / K2: BlockingIOError → reap then ensure (in that order), drop the
    # dead fd, re-mark every live scene, and repaint the fresh display.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, provider, lifecycle = _replicator(store)
    sender.arm_failure(BlockingIOError())
    repl.start()
    try:
        repl.mark_dirty(scene)
        # The first send raises; recovery heals and the re-mark repaints.
        assert sender.wait_sent(3.0)
        assert lifecycle.calls == ["reap", "ensure"]
        assert provider.drops == 1
        assert sender.shows == ["s1"]
    finally:
        repl.stop()


def test_a_dead_peer_reconnects_without_reaping() -> None:
    # P4 / RC1 / RC3: OSError → drop and reconnect, never reap; re-mark every
    # live scene so the fresh, empty display is repainted.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, provider, lifecycle = _replicator(store)
    sender.arm_failure(OSError("ECONNRESET"))
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_sent(3.0)
        assert lifecycle.calls == []  # nothing killed — the peer was already gone
        assert provider.drops == 1
        assert sender.shows == ["s1"]
    finally:
        repl.stop()


def test_a_recovery_failure_restores_the_batch_and_retries() -> None:
    # A recovery step that itself fails — here ``ensure`` cannot respawn the
    # display on the first try — must not drop the drained work. The worker puts
    # the batch back, backs off, and the next cycle retries it once the display
    # recovers, so nothing is lost when a respawn transiently fails.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, lifecycle = _replicator(store)
    sender.arm_failure(BlockingIOError())  # first send wedges → reap/ensure
    lifecycle.arm_ensure_failure(RuntimeError("cannot spawn display"))
    repl.start()
    try:
        repl.mark_dirty(scene)
        # The first cycle wedges and its respawn raises; the batch is restored
        # and the retry, with a healed display, repaints the scene.
        assert sender.wait_sent(3.0)
        assert sender.shows == ["s1"]
        assert lifecycle.calls == ["reap", "ensure"]  # ensure raised, not retried
    finally:
        repl.stop()


def test_a_dead_peer_recovery_re_marks_a_consumed_clear() -> None:
    # A clear coalesced with a show, where the clear's send hits a dead peer:
    # the reconnect re-marks the consumed clear, so the display is blanked again
    # on the retry. Without the re-mark, a same-display reconnect would leave the
    # old scene on screen forever.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, provider, _lifecycle = _replicator(store)
    sender.arm_failure(OSError("EPIPE"))  # the clear's send finds a dead peer
    repl.start()
    try:
        repl.mark_cleared()
        repl.mark_dirty(scene)
        assert sender.wait_sent(3.0)
        # Give the retried cycle a moment to blank then repaint.
        for _ in range(100):
            if sender.shows:
                break
            threading.Event().wait(0.01)
        assert provider.drops == 1
        # The clear survived the dead-peer recovery: blank first, then repaint.
        assert sender.timeline == ["clear", "show:s1"]
    finally:
        repl.stop()


def test_an_emptied_scene_is_blanked_into_its_frame() -> None:
    # A9: a scene emptied without a clear is pushed with no roots, blanking its
    # frame. That is how a scene an update stripped to nothing, or one a departed
    # session left, disappears from the display rather than lingering. The frame is
    # named distinctly from the scene so a regression that blanked into the default
    # frame (frame_id == scene id) would fail on the frames assertion.
    store = HubDisplay()
    scene = SceneId("s1")
    store.register_client(_CONN)
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="x")])
    store.record_presentation(scene, ScenePresentation(frame_id="hello-frame"))
    store.replace_scene(_CONN, scene, ())  # empty the scene
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)  # the now-empty scene
        assert sender.wait_sent(2.0)
        assert sender.shows == ["s1"]  # pushed to blank the frame
        assert sender.frames == ["hello-frame"]  # into the frame it was shown in
        (pushed,) = sender.roots
        assert pushed == []  # with no roots
    finally:
        repl.stop()


def test_blanking_an_emptied_scene_reclaims_its_presentation() -> None:
    # Once the worker blanks an emptied scene, its presentation is forgotten: the
    # scene is gone from the store and nothing repaints it without a re-show, so
    # the frame map does not grow for the process lifetime. A distinct frame name
    # makes the reclaim observable — presentation_for falls back to the self-framed
    # default (frame_id == scene id) once the recorded frame is dropped.
    store = HubDisplay()
    scene = SceneId("s1")
    store.register_client(_CONN)
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="x")])
    store.record_presentation(scene, ScenePresentation(frame_id="hello-frame"))
    store.replace_scene(_CONN, scene, ())  # empty the scene
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        assert sender.frames == ["hello-frame"]  # blanked into its own frame first
        for _ in range(200):  # the reclaim runs just after the send returns
            if store.presentation_for(scene).frame_id == "s1":
                break
            threading.Event().wait(0.01)
        assert store.presentation_for(scene).frame_id == "s1"  # reclaimed
    finally:
        repl.stop()


def test_a_failed_blank_is_re_marked_then_retried_and_the_frame_reclaimed() -> None:
    # The full chain for an emptied scene whose blank send fails: the scene has no
    # roots, so it is absent from live_scene_ids; the recovery re-marks it from the
    # batch's own scenes, the retry blanks it into the frame it was shown in, and
    # only then is its presentation reclaimed. Forgetting waits for a delivered
    # blank, so the retry still has the recorded frame to blank into.
    store = HubDisplay()
    scene = SceneId("s1")
    store.register_client(_CONN)
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="x")])
    store.record_presentation(scene, ScenePresentation(frame_id="hello-frame"))
    store.replace_scene(_CONN, scene, ())  # empty the scene
    repl, sender, provider, _lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)  # park the worker in the first blank send
    sender.arm_failure(OSError())  # ...which then fails as a dead peer
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_entered(2.0)
        gate.set()  # release → OSError → recovery re-marks the scene from the batch
        for _ in range(300):
            if sender.frames == ["hello-frame"]:
                break
            threading.Event().wait(0.01)
        assert provider.drops == 1  # dead-peer reconnect
        assert sender.frames == ["hello-frame"]  # the retry blanked into the frame
        assert sender.roots == [[]]  # with no roots
        for _ in range(200):
            if store.presentation_for(scene).frame_id == "s1":
                break
            threading.Event().wait(0.01)
        assert store.presentation_for(scene).frame_id == "s1"  # reclaimed after blank
    finally:
        gate.set()
        repl.stop()


def test_a_reshow_during_the_blank_send_keeps_its_new_presentation() -> None:
    # A re-show that lands during the ~2s blank send installs roots and a fresh
    # frame. The reclaim re-checks rootless under the write lock, so it sees the new
    # roots and skips the forget — the new frame survives, not clobbered by a stale
    # reclaim of the scene the worker thought it had emptied.
    store = HubDisplay()
    scene = SceneId("s1")
    store.register_client(_CONN)
    store.replace_scene(_CONN, scene, [TextElement(id="s1-root", content="x")])
    store.record_presentation(scene, ScenePresentation(frame_id="old-frame"))
    store.replace_scene(_CONN, scene, ())  # empty it, so the worker will blank it
    repl, sender, _provider, _lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)  # park the worker inside the blank send
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_entered(2.0)  # the worker is inside the blank send
        # A re-show lands mid-send: new roots and a new frame.
        store.show_scene(
            _CONN,
            scene,
            [TextElement(id="s1-root", content="y")],
            ScenePresentation(frame_id="new-frame"),
        )
        gate.set()  # release → the clean cycle's reclaim re-checks rootless
        assert sender.wait_sent(2.0)
        # The reclaim runs just after the send; it must skip (the scene has roots),
        # so the new frame holds across the settle window rather than reverting.
        for _ in range(50):
            threading.Event().wait(0.01)
            assert store.presentation_for(scene).frame_id == "new-frame"
    finally:
        gate.set()
        repl.stop()


def test_a_requeued_blank_targets_the_recorded_frame() -> None:
    # Two emptied scenes with distinct frames coalesce in one cycle. One blanks and
    # the other's send fails as a dead peer; recovery re-marks both. Because reclaim
    # is deferred to a clean cycle, the blanked scene's frame is not forgotten
    # mid-cycle, so its retry blanks into the recorded frame — every blank of either
    # scene targets its recorded frame, never the self-framed default.
    store = HubDisplay()
    a, b = SceneId("s1"), SceneId("s2")
    store.register_client(_CONN)
    for sid, frame in ((a, "frame-a"), (b, "frame-b")):
        store.replace_scene(_CONN, sid, [TextElement(id=f"{sid}-root", content="x")])
        store.record_presentation(sid, ScenePresentation(frame_id=frame))
        store.replace_scene(_CONN, sid, ())  # empty it
    repl, sender, provider, _lifecycle = _replicator(store)
    sender.fail_on_scene("s2", OSError())  # scene B's blank fails once
    repl.start()
    try:
        repl.mark_dirty(a)
        repl.mark_dirty(b)
        for _ in range(300):
            if {"s1", "s2"} <= set(sender.shows):
                break
            threading.Event().wait(0.01)
        assert provider.drops >= 1  # the dead peer reconnected
        assert {"s1", "s2"} <= set(sender.shows)  # both scenes blanked
        sent = list(zip(sender.shows, sender.frames, strict=False))
        for scene_id, sent_frame in sent:
            expected = "frame-a" if scene_id == "s1" else "frame-b"
            assert sent_frame == expected  # recorded frame, never the default
    finally:
        repl.stop()


def test_a_recovered_cycle_backs_off_and_a_clean_cycle_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A send failure that recovery handled still counts as a failure for the
    # backoff: the delay grows, so a display that connects yet refuses every send is
    # throttled rather than looped at the coalesce interval. A genuinely clean cycle
    # resets the delay. Driving one cycle at a time with sleep stubbed keeps this
    # deterministic and instant.
    slept: list[float] = []
    monkeypatch.setattr("punt_lux.domain.hub.replicator.time.sleep", slept.append)
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, _lifecycle = _replicator(store)
    batch = DrainedBatch(frozenset({scene}), cleared=False, shutting=False)

    sender.arm_failure(OSError())  # the send fails; recovery reconnects
    repl._run_cycle(batch)
    assert slept == [_BASE_BACKOFF_SECONDS]  # a recovered cycle throttles
    assert repl._backoff > _BASE_BACKOFF_SECONDS  # and grows the delay, not resets

    repl._run_cycle(batch)  # a clean cycle now resets the delay
    assert repl._backoff == _BASE_BACKOFF_SECONDS


def test_recovery_of_an_emptied_store_repaints_nothing() -> None:
    # K3: a live scene's send fails and triggers recovery; by the time recovery
    # re-marks, the store has been emptied, so live_scene_ids is empty and the
    # fresh display is repainted with nothing.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, provider, lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)  # park the worker in the send
    sender.arm_failure(BlockingIOError())  # ...then fail when released
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_entered(2.0)  # the worker is provably inside the send
        store.replace_scene(_CONN, scene, ())  # empty the store before recovery
        gate.set()  # release the send → it raises → recovery runs
        for _ in range(100):
            if provider.drops:
                break
            threading.Event().wait(0.01)
        assert provider.drops == 1
        assert lifecycle.calls == ["reap", "ensure"]
        assert sender.shows == []  # nothing live to repaint
    finally:
        gate.set()
        repl.stop()


def test_a_mutator_makes_progress_while_the_worker_is_stuck_sending() -> None:
    # P6: the whole point — a mutator completes a full replace while the worker
    # is blocked in a send to a wedged display. The agent path never waits on I/O.
    store = HubDisplay()
    scene = _seed(store, "s1")
    other = SceneId("s2")
    repl, sender, _provider, _lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)
    repl.start()
    try:
        repl.mark_dirty(scene)
        # The worker is provably parked inside the gated send — no hopeful sleep.
        assert sender.wait_entered(2.0)

        # A mutator runs to completion while the worker holds the send open.
        done = threading.Event()

        def mutate() -> None:
            store.register_client(_CONN)
            store.replace_scene(_CONN, other, [TextElement(id="s2-root", content="y")])
            done.set()

        t = threading.Thread(target=mutate)
        t.start()
        assert done.wait(2.0), "mutator blocked while the worker was sending"
        t.join(timeout=2.0)
    finally:
        gate.set()
        repl.stop()


def test_a_mutation_during_recovery_is_repainted_after_respawn() -> None:
    # K5: a mutation lands while the worker is reaping and respawning a wedged
    # display. The recovery re-marks every live scene, so the fresh display is
    # repainted with the latest state — including the scene added mid-recovery.
    store = HubDisplay()
    scene = _seed(store, "s1")
    other = SceneId("s2")
    repl, sender, _provider, _lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)
    sender.arm_failure(BlockingIOError())
    repl.start()
    try:
        repl.mark_dirty(scene)
        assert sender.wait_entered(2.0)  # worker parked in the send to "s1"
        # A new scene is installed while the worker is stuck; the send then
        # fails and recovery re-marks every live scene, both of them.
        store.register_client(_CONN)
        store.replace_scene(_CONN, other, [TextElement(id="s2-root", content="y")])
        gate.set()  # release → send raises → reap/ensure/re-mark
        for _ in range(300):
            if set(sender.shows) >= {"s1", "s2"}:
                break
            threading.Event().wait(0.01)
        assert set(sender.shows) == {"s1", "s2"}
    finally:
        gate.set()
        repl.stop()


def test_the_worker_snapshot_waits_for_a_mutation_to_commit() -> None:
    # S2: the torn read. A mutator holds the store write lock and replaces the
    # scene with a new value; the worker's snapshot must not fire mid-mutation.
    # It waits for the write lock to release, then copies the committed value —
    # never a half-updated one. Asserting the pushed value equals the
    # post-mutation value proves the snapshot saw the whole commit, not a tear.
    store = HubDisplay()
    scene = _seed(store, "s1", content="before")
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        with store.write_lock():
            repl.mark_dirty(scene)
            # Replace the scene with a new value while the lock is held. The
            # worker woke and drained but cannot snapshot, so nothing is sent.
            store.replace_scene(
                _CONN, scene, [TextElement(id="s1-root", content="after")]
            )
            assert not sender.wait_sent(0.3)
        # The write lock released; the worker snapshots the committed value.
        assert sender.wait_sent(2.0)
        (pushed,) = sender.roots
        assert [e.to_dict()["content"] for e in pushed] == ["after"]
    finally:
        repl.stop()


def test_a_stop_flushes_a_send_in_flight_then_exits() -> None:
    # SH1: a scene marked before the stop is sent before the worker exits — a stop
    # never abandons a send already in flight. The worker is parked mid-send via
    # the gate, so the flush is provably underway when the stop is requested, and
    # the stop runs on its own thread because it joins the worker it is stopping.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, _lifecycle = _replicator(store)
    gate = threading.Event()
    sender.block_next(gate)
    repl.start()
    repl.mark_dirty(scene)
    assert sender.wait_entered(2.0)  # the worker is inside the send
    stopper = threading.Thread(target=repl.stop)
    stopper.start()
    gate.set()  # release the flush; it completes before the worker exits
    assert sender.wait_sent(2.0)
    stopper.join(2.0)
    assert not stopper.is_alive()  # the stop joined the worker cleanly
    assert sender.shows == ["s1"]


def test_a_show_then_clear_ends_blank() -> None:
    # CL4: a show and a clear coalesce before the drain. The clear emptied the
    # store, so the cycle blanks the display and the now-empty scene is skipped —
    # the display ends blank, consistent with the emptied store.
    store = HubDisplay()
    scene = _seed(store, "s1")
    store.replace_scene(_CONN, scene, ())  # the clear emptied the scene
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)
        repl.mark_cleared()
        assert sender.wait_sent(2.0)
        assert sender.timeline == ["clear"]  # blanked; the empty scene skipped
        assert sender.shows == []
    finally:
        repl.stop()


def test_a_clear_with_no_batch_only_blanks() -> None:
    # E2: a clear pushed with an empty batch blanks the display and nothing else.
    store = HubDisplay()
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_cleared()
        assert sender.wait_sent(2.0)
        assert sender.timeline == ["clear"]
        assert sender.shows == []
    finally:
        repl.stop()


def test_a_fresh_replicator_after_a_stop_starts_idle_and_works() -> None:
    # SH4: luxd restarting is a fresh replicator over the same store — idle, then
    # it sends on the first mark.
    store = HubDisplay()
    scene = _seed(store, "s1")
    first, _s1, _p1, _l1 = _replicator(store)
    first.start()
    first.stop()

    second, sender, _provider, _lifecycle = _replicator(store)
    second.start()
    try:
        second.mark_dirty(scene)
        assert sender.wait_sent(2.0)
        assert sender.shows == ["s1"]
    finally:
        second.stop()


def test_a_stop_before_start_makes_start_raise() -> None:
    # A stop is terminal even before the worker ran: with no thread to join the
    # stop itself is a clean no-op, but it latches the dirty signal shutting, so a
    # later start would spawn a worker that exits at once and drops every mark. The
    # start must raise loudly, not fail silently.
    store = HubDisplay()
    repl, _sender, _provider, _lifecycle = _replicator(store)
    repl.stop()  # no worker to join; latches shutting
    with pytest.raises(RuntimeError, match="was stopped"):
        repl.start()


def test_restarting_a_stopped_replicator_raises() -> None:
    # A6: a replicator that ran and stopped is terminal. Restarting it would
    # spawn a worker whose latched signal makes it exit at once, silently
    # dropping every later mark. The restart must raise, not fail silently.
    store = HubDisplay()
    repl, _sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    repl.stop()
    with pytest.raises(RuntimeError, match="was stopped"):
        repl.start()
