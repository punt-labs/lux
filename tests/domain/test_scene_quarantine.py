"""Tests for SceneQuarantine -- record, lift, and notify under the store lock."""

from __future__ import annotations

from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.scene_quarantine import SceneQuarantine
from punt_lux.domain.hub.store_lock import StoreLock
from punt_lux.domain.ids import SceneId

_SCENE = SceneId("s1")
_RECORD = QuarantineRecord(death_count=2, last_death_at=1.0)


def _quarantine() -> SceneQuarantine:
    return SceneQuarantine(StoreLock())


class TestSceneQuarantine:
    def test_a_quarantined_scene_reports_and_returns_its_record(self) -> None:
        q = _quarantine()
        q.quarantine(_SCENE, _RECORD)
        assert q.is_quarantined(_SCENE)
        assert q.quarantine_record(_SCENE) == _RECORD

    def test_an_unknown_scene_is_not_quarantined(self) -> None:
        assert _quarantine().quarantine_record(_SCENE) is None

    def test_quarantined_ids_lists_every_quarantined_scene(self) -> None:
        q = _quarantine()
        q.quarantine(_SCENE, _RECORD)
        assert q.quarantined_ids() == frozenset({_SCENE})

    def test_lifting_clears_the_record_and_notifies_observers(self) -> None:
        q = _quarantine()
        seen: list[SceneId] = []
        q.add_quarantine_cleared_observer(seen.append)
        q.quarantine(_SCENE, _RECORD)
        q.lift(_SCENE)
        assert not q.is_quarantined(_SCENE)
        assert seen == [_SCENE]

    def test_lifting_a_scene_that_is_not_quarantined_notifies_nobody(self) -> None:
        q = _quarantine()
        seen: list[SceneId] = []
        q.add_quarantine_cleared_observer(seen.append)
        q.lift(_SCENE)
        assert seen == []
