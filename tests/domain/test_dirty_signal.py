"""DirtySignal — coalescing, the atomic drain, and the stop flag.

Covers the Wake / Drain partitions of the replicator spec: many marks of one
scene coalesce to a single batch entry (D2), two scenes drain together (D3), a
mark that lands after a drain is carried to the next cycle (D4), and the drain
takes the dirty set and the cleared flag together (D5). The menu flag rides the
same signal: many menu marks coalesce to one flag (MN1), the drain takes it
alongside the dirty set and the cleared flag and resets it (MN2), an idle worker
wakes on a menu mark alone (MN3), and a batch with no menu mark carries no menu
flag (MN5).
"""

from __future__ import annotations

import threading

from punt_lux.domain.hub.dirty_signal import DirtySignal, DrainedBatch
from punt_lux.domain.ids import SceneId

_S1 = SceneId("s1")
_S2 = SceneId("s2")
# 0.0 coalesce keeps the tests instant — the burst window is behavioural, not timed.
_NO_COALESCE = 0.0


def test_many_marks_of_one_scene_coalesce_to_a_single_entry() -> None:
    signal = DirtySignal()
    for _ in range(5):
        signal.mark_dirty(_S1)

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.scenes == frozenset({_S1})
    assert not batch.cleared


def test_two_scenes_drain_in_one_batch() -> None:
    signal = DirtySignal()
    signal.mark_dirty(_S1)
    signal.mark_dirty(_S2)

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.scenes == frozenset({_S1, _S2})


def test_a_mark_after_the_drain_is_carried_to_the_next_cycle() -> None:
    signal = DirtySignal()
    signal.mark_dirty(_S1)
    first = signal.wait_and_drain(_NO_COALESCE)
    assert first.scenes == frozenset({_S1})

    signal.mark_dirty(_S2)
    second = signal.wait_and_drain(_NO_COALESCE)

    # s1 was drained in the first cycle; only s2 lands in the second.
    assert second.scenes == frozenset({_S2})


def test_drain_takes_dirty_and_cleared_together_and_resets_both() -> None:
    signal = DirtySignal()
    signal.mark_dirty(_S1)
    signal.mark_cleared()

    batch = signal.wait_and_drain(_NO_COALESCE)
    assert batch.scenes == frozenset({_S1})
    assert batch.cleared

    # Both were reset: the next cycle has no work until something new is marked.
    signal.mark_dirty(_S2)
    nxt = signal.wait_and_drain(_NO_COALESCE)
    assert nxt.scenes == frozenset({_S2})
    assert not nxt.cleared


def test_many_menu_marks_coalesce_to_a_single_flag() -> None:
    # MN1: the menu flag is payload-less, so a burst of marks collapses to one
    # flag — the worker pushes the registry once, not once per mark.
    signal = DirtySignal()
    for _ in range(5):
        signal.mark_menus()

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.menus_dirty
    assert batch.scenes == frozenset()
    assert not batch.cleared


def test_drain_takes_menus_alongside_dirty_and_cleared_and_resets() -> None:
    # MN2: one drain takes the dirty set, the cleared flag, and the menu flag
    # together and resets all three, so the next cycle carries none of them until
    # something new is marked.
    signal = DirtySignal()
    signal.mark_dirty(_S1)
    signal.mark_cleared()
    signal.mark_menus()

    batch = signal.wait_and_drain(_NO_COALESCE)
    assert batch.scenes == frozenset({_S1})
    assert batch.cleared
    assert batch.menus_dirty

    signal.mark_dirty(_S2)
    nxt = signal.wait_and_drain(_NO_COALESCE)
    assert nxt.scenes == frozenset({_S2})
    assert not nxt.cleared
    assert not nxt.menus_dirty


def test_an_idle_signal_wakes_on_a_menu_mark_alone() -> None:
    # MN3: a menu change is enough to wake the worker on its own — no scene need be
    # dirty and no clear pending. The worker parks on the condition until the menu
    # mark arrives, then drains a batch that carries only the menu flag.
    signal = DirtySignal()
    drained: list[DrainedBatch] = []

    def worker() -> None:
        drained.append(signal.wait_and_drain(_NO_COALESCE))

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=0.2)
    assert t.is_alive()  # parked: nothing dirty, not cleared, no menu yet
    assert drained == []

    signal.mark_menus()
    t.join(timeout=2.0)
    assert len(drained) == 1
    assert drained[0].menus_dirty
    assert drained[0].scenes == frozenset()
    assert not drained[0].cleared


def test_a_batch_without_a_menu_mark_carries_no_menu_flag() -> None:
    # MN5: a scene-only batch leaves the menu flag clear, so the worker skips the
    # menu push entirely — the signal-level precondition for never touching the
    # client's menu on a non-menu cycle.
    signal = DirtySignal()
    signal.mark_dirty(_S1)

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.scenes == frozenset({_S1})
    assert not batch.menus_dirty


def test_stop_with_nothing_pending_returns_shutting_at_once() -> None:
    signal = DirtySignal()
    signal.request_stop()

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.shutting
    assert not batch.has_work


def test_stop_with_a_pending_scene_flushes_it_and_signals_shutting() -> None:
    signal = DirtySignal()
    signal.mark_dirty(_S1)
    signal.request_stop()

    batch = signal.wait_and_drain(_NO_COALESCE)

    assert batch.scenes == frozenset({_S1})
    assert batch.shutting


def test_is_shutting_latches_true_once_a_stop_is_requested() -> None:
    # The single source of the stop fact: the replicator asks this to reject a
    # start after a stop, so the flag that makes the worker exit and the flag that
    # forbids a restart are one and the same.
    signal = DirtySignal()
    assert not signal.is_shutting

    signal.request_stop()

    assert signal.is_shutting


def test_an_idle_signal_blocks_until_a_mark_arrives() -> None:
    signal = DirtySignal()
    drained: list[frozenset[SceneId]] = []

    def worker() -> None:
        drained.append(signal.wait_and_drain(_NO_COALESCE).scenes)

    t = threading.Thread(target=worker)
    t.start()
    # No work yet: the worker is parked on the condition, nothing drained.
    t.join(timeout=0.2)
    assert t.is_alive()
    assert drained == []

    signal.mark_dirty(_S1)
    t.join(timeout=2.0)
    assert drained == [frozenset({_S1})]
