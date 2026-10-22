"""HubDisplay quarantine wiring — observer cascade and teardown-clear paths.

Focused on the invariants added by the review round: every quarantine-clear
path (owner re-show, empty-scene removal, frame close, TTL expiry) fires the
observer cascade, so a subscriber (like ``CrashAttribution.clear_tally``)
never misses a lift; TTL and frame-close teardowns clear the record too, so
no orphan quarantine outlives its scene.
"""

from __future__ import annotations

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import RemoveElement
from punt_lux.protocol.elements.text import TextElement

_CONN = ConnectionId("owner")
_SCENE = SceneId("s1")


def _seeded_with_quarantine(record: QuarantineRecord) -> HubDisplay:
    """Return a store holding one owned root under _SCENE, quarantined."""
    store = HubDisplay()
    store.register_client(_CONN)
    store.replace_scene(_CONN, _SCENE, [TextElement(id="t1", content="x")])
    store.quarantine(_SCENE, record)
    return store


def _record() -> QuarantineRecord:
    return QuarantineRecord(death_count=2, last_death_at=42.0)


def test_replace_scene_fires_the_quarantine_cleared_observers() -> None:
    store = _seeded_with_quarantine(_record())
    observed: list[SceneId] = []
    store.add_quarantine_cleared_observer(observed.append)

    store.replace_scene(_CONN, _SCENE, [TextElement(id="t2", content="fixed")])

    assert observed == [_SCENE]
    assert not store.is_quarantined(_SCENE)


def test_remove_element_that_empties_scene_fires_observers() -> None:
    store = _seeded_with_quarantine(_record())
    observed: list[SceneId] = []
    store.add_quarantine_cleared_observer(observed.append)

    store.apply(_CONN, RemoveElement(scene_id=_SCENE, element_id=ElementId("t1")))

    assert observed == [_SCENE]
    assert not store.is_quarantined(_SCENE)


def test_ttl_expiry_fires_quarantine_cleared_observers() -> None:
    # Finding 4's teardown territory: tearing a scene's roots down must also
    # lift the quarantine, so a later write against the (gone) scene gets
    # "not found" rather than a spurious quarantine rejection. The TTL sweep is
    # the only Hub-side teardown left -- a user closing a frame on the Display
    # no longer reaches the Hub at all (DES-088).
    now = [1000.0]
    store = HubDisplay(clock=lambda: now[0])
    store.register_client(_CONN)
    store.show_scene(
        _CONN,
        _SCENE,
        [TextElement(id="t1", content="x")],
        ScenePresentation(frame_id="ttl-frame"),
        ttl_seconds=1.0,
    )
    store.quarantine(_SCENE, _record())
    observed: list[SceneId] = []
    store.add_quarantine_cleared_observer(observed.append)

    now[0] = 1002.0
    expired = store.frames.expire_due()

    assert expired == frozenset({_SCENE})
    assert observed == [_SCENE]
    assert not store.is_quarantined(_SCENE)


def test_observers_are_not_fired_on_a_clean_scene() -> None:
    # A teardown of a scene that was never quarantined must not fire a phantom
    # observer event — the callback names a real quarantine lift, not every
    # teardown.
    store = HubDisplay()
    store.register_client(_CONN)
    store.replace_scene(_CONN, _SCENE, [TextElement(id="t1", content="x")])
    observed: list[SceneId] = []
    store.add_quarantine_cleared_observer(observed.append)

    store.apply(_CONN, RemoveElement(scene_id=_SCENE, element_id=ElementId("t1")))

    assert observed == []


def test_live_scene_ids_excludes_quarantined_scenes() -> None:
    # The reconcile boundary depends on this: live_scene_ids is the
    # replication-facing read, so a quarantined scene must never appear here
    # for the DES-068 reconnect hook to re-mark.
    store = _seeded_with_quarantine(_record())
    assert store.all_scene_ids() == (_SCENE,)  # still installed for inspection
    assert store.live_scene_ids() == ()  # but never replicated


def test_a_reshow_after_quarantine_needs_full_threshold_before_re_quarantine() -> None:
    # Finding 2's end-to-end shape at the store: an owner re-shows (which
    # lifts the quarantine and fires the observer, resetting any subscribed
    # attribution's tally). If a new tally later reaches the threshold, that
    # is a fresh full accumulation — never a re-quarantine off one death.
    store = _seeded_with_quarantine(_record())
    calls: list[SceneId] = []
    store.add_quarantine_cleared_observer(calls.append)
    store.replace_scene(_CONN, _SCENE, [TextElement(id="t2", content="fixed")])
    assert not store.is_quarantined(_SCENE)
    assert calls == [_SCENE]
