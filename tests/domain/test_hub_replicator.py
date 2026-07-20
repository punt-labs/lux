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

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.replicator import HubReplicator
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
    timeline: list[str]
    _fail: OSError | None
    _gate: threading.Event | None
    _lock: threading.Lock
    _sent: threading.Event
    _entered: threading.Event
    __slots__ = (
        "_entered",
        "_fail",
        "_gate",
        "_lock",
        "_sent",
        "clears",
        "frames",
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
        self.timeline = []
        self._fail = None
        self._gate = None
        self._lock = threading.Lock()
        self._sent = threading.Event()
        self._entered = threading.Event()
        return self

    def arm_failure(self, exc: OSError) -> None:
        self._fail = exc

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
    # session left, disappears from the display rather than lingering.
    store = HubDisplay()
    scene = _seed(store, "s1")
    store.replace_scene(_CONN, scene, ())  # empty the scene
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.start()
    try:
        repl.mark_dirty(scene)  # the now-empty scene
        assert sender.wait_sent(2.0)
        assert sender.shows == ["s1"]  # pushed to blank the frame
        (pushed,) = sender.roots
        assert pushed == []  # with no roots
    finally:
        repl.stop()


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


def test_shutdown_flushes_a_pending_scene_then_stops() -> None:
    # SH1: a stop with pending work does one final bounded flush before stopping.
    # Requesting the stop before the worker starts makes the first drain provably
    # see shutting=True alongside the pending scene, so the single-cycle flush is
    # deterministic rather than racing the 16 ms coalesce window.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, _provider, _lifecycle = _replicator(store)
    repl.mark_dirty(scene)
    repl.stop()  # request the stop before the worker's first drain
    repl.start()
    repl.stop()  # join the now-finished worker
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


def test_shutdown_with_a_stuck_display_does_not_reap() -> None:
    # SH2: the final flush is best-effort — a stuck send fails within its limit
    # and shutdown continues without reaping or respawning. The stop is requested
    # before the worker starts, so the flush is deterministically the shutting
    # cycle rather than racing the coalesce window.
    store = HubDisplay()
    scene = _seed(store, "s1")
    repl, sender, provider, lifecycle = _replicator(store)
    sender.arm_failure(BlockingIOError())
    repl.mark_dirty(scene)
    repl.stop()  # request the stop before the worker's first drain
    repl.start()
    repl.stop()  # join the now-finished worker
    assert lifecycle.calls == []
    assert provider.drops == 0


def test_stop_without_start_is_a_no_op() -> None:
    # A replicator that was never started stops cleanly — there is no worker
    # thread to join, and the stop must not raise. It stays startable.
    store = HubDisplay()
    repl, _sender, _provider, _lifecycle = _replicator(store)
    repl.stop()
    repl.start()  # a stop before the worker ran leaves it startable
    repl.stop()


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
