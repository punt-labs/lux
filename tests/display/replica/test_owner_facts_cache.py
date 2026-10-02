"""OwnerFactsCache and OwnerFactsStore -- the departure-guarded snapshot and
its keyed store, tested on their own."""

from __future__ import annotations

from punt_lux.display.replica.owner_facts_cache import OwnerFactsCache, OwnerFactsStore
from punt_lux.domain.identity import HubId, HubScopedKey

_ROWS = (("Client", "lux"), ("Kind", "agent"))
_OTHER_ROWS = (("Client", "lux"),)
_HUB = HubId.stub()
_OTHER_HUB = HubId("okinos", 2)
_F1 = HubScopedKey(_HUB, "f1")
_F2 = HubScopedKey(_HUB, "f2")
_GHOST = HubScopedKey(_HUB, "ghost")


class TestConstruction:
    def test_starts_empty_by_default(self) -> None:
        assert OwnerFactsCache().rows is None

    def test_can_start_populated(self) -> None:
        assert OwnerFactsCache(_ROWS).rows == _ROWS


class TestUpdate:
    def test_a_facts_bearing_update_populates_an_empty_cache(self) -> None:
        cache = OwnerFactsCache()
        cache.update(_ROWS)
        assert cache.rows == _ROWS

    def test_a_facts_bearing_update_replaces_the_cached_snapshot(self) -> None:
        cache = OwnerFactsCache(_ROWS)
        cache.update(_OTHER_ROWS)
        assert cache.rows == _OTHER_ROWS

    def test_a_none_update_preserves_the_cached_snapshot(self) -> None:
        # The departure guarantee: once populated, a None update -- the owner
        # departed or the Hub could not resolve it -- never blanks the cache.
        cache = OwnerFactsCache(_ROWS)
        cache.update(None)
        assert cache.rows == _ROWS

    def test_a_none_update_on_an_empty_cache_stays_empty(self) -> None:
        cache = OwnerFactsCache()
        cache.update(None)
        assert cache.rows is None


class TestStoreAdopt:
    def test_a_facts_bearing_adopt_populates_a_new_frames_entry(self) -> None:
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)
        assert store.rows_for(_F1) == _ROWS

    def test_a_later_none_adopt_preserves_the_frames_cached_snapshot(self) -> None:
        # The departure guarantee (lux-c7xi round 2): moved off Frame entirely
        # and onto this keyed store -- a later push carrying None must still
        # never blank what was cached while the connection was live.
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)

        store.adopt(_F1, None)

        assert store.rows_for(_F1) == _ROWS

    def test_frames_are_independent(self) -> None:
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)
        store.adopt(_F2, _OTHER_ROWS)
        assert store.rows_for(_F1) == _ROWS
        assert store.rows_for(_F2) == _OTHER_ROWS


class TestStoreRowsFor:
    def test_an_untracked_frame_reads_none(self) -> None:
        store = OwnerFactsStore()
        assert store.rows_for(_GHOST) is None


class TestStorePrune:
    def test_prune_drops_a_tracked_frames_entry(self) -> None:
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)

        store.prune(_F1)

        assert store.rows_for(_F1) is None

    def test_a_later_adopt_after_prune_starts_fresh_not_stale(self) -> None:
        """A pruned then reused frame id starts empty -- no stale carryover."""
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)
        store.prune(_F1)

        store.adopt(_F1, None)

        assert store.rows_for(_F1) is None

    def test_prune_of_an_untracked_frame_is_a_noop(self) -> None:
        store = OwnerFactsStore()
        store.prune(_GHOST)  # must not raise
        assert store.rows_for(_GHOST) is None


class TestStoreClear:
    def test_clear_drops_every_entry(self) -> None:
        store = OwnerFactsStore()
        store.adopt(_F1, _ROWS)
        store.adopt(_F2, _OTHER_ROWS)

        store.clear()

        assert store.rows_for(_F1) is None
        assert store.rows_for(_F2) is None

    def test_clear_on_an_empty_store_is_a_noop(self) -> None:
        store = OwnerFactsStore()
        store.clear()  # must not raise
        assert store.rows_for(_F1) is None


class TestHubScoping:
    """Two Hubs minting the identical frame id must never share one entry."""

    def test_two_hubs_naming_the_same_frame_id_hold_distinct_facts(self) -> None:
        store = OwnerFactsStore()
        mine = HubScopedKey(_HUB, "main")
        theirs = HubScopedKey(_OTHER_HUB, "main")

        store.adopt(mine, _ROWS)
        store.adopt(theirs, _OTHER_ROWS)

        assert store.rows_for(mine) == _ROWS
        assert store.rows_for(theirs) == _OTHER_ROWS

    def test_pruning_one_hubs_frame_leaves_the_others_intact(self) -> None:
        store = OwnerFactsStore()
        mine = HubScopedKey(_HUB, "main")
        theirs = HubScopedKey(_OTHER_HUB, "main")
        store.adopt(mine, _ROWS)
        store.adopt(theirs, _OTHER_ROWS)

        store.prune(mine)

        assert store.rows_for(mine) is None
        assert store.rows_for(theirs) == _OTHER_ROWS
