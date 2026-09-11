"""HubScopedStore -- the aggregated-storage shape multi-Hub collections use.

The load-bearing property this suite proves: two synthetic Hub connections
independently producing colliding Rung-2 (local) strings must produce two
distinct entries, never one clobbering the other -- the collision this store
exists to make unrepresentable (`system.tex` "Governing Invariant").
"""

from __future__ import annotations

from punt_lux.domain.hub_id import HubId
from punt_lux.domain.hub_scoped_key import HubScopedKey
from punt_lux.domain.hub_scoped_store import HubScopedStore

_HUB_A = HubId("pembroke", 1)
_HUB_B = HubId("okinos", 2)


class TestPutAndGet:
    def test_put_then_get_returns_the_value(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        key = HubScopedKey(_HUB_A, "s1")
        store.put(key, "frame-a")
        assert store.get(key) == "frame-a"

    def test_get_of_an_absent_key_is_none(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert store.get(HubScopedKey(_HUB_A, "ghost")) is None

    def test_put_overwrites_the_identical_key(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        key = HubScopedKey(_HUB_A, "s1")
        store.put(key, "first")
        store.put(key, "second")
        assert store.get(key) == "second"


class TestCollisionSafety:
    """Two Hubs producing the identical local id never collide."""

    def test_two_hubs_with_the_same_local_id_get_distinct_entries(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        key_a = HubScopedKey(_HUB_A, "s1")
        key_b = HubScopedKey(_HUB_B, "s1")

        store.put(key_a, "frame-from-a")
        store.put(key_b, "frame-from-b")

        assert store.get(key_a) == "frame-from-a"
        assert store.get(key_b) == "frame-from-b"

    def test_a_second_hubs_write_does_not_overwrite_the_firsts(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-from-a")

        store.put(HubScopedKey(_HUB_B, "s1"), "frame-from-b")

        assert store.get(HubScopedKey(_HUB_A, "s1")) == "frame-from-a"


class TestRemove:
    def test_remove_returns_the_value_and_drops_the_entry(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        key = HubScopedKey(_HUB_A, "s1")
        store.put(key, "frame-a")

        assert store.remove(key) == "frame-a"
        assert store.get(key) is None

    def test_remove_of_an_absent_key_is_none_and_a_noop(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert store.remove(HubScopedKey(_HUB_A, "ghost")) is None

    def test_remove_only_drops_the_named_hubs_entry(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-from-a")
        store.put(HubScopedKey(_HUB_B, "s1"), "frame-from-b")

        store.remove(HubScopedKey(_HUB_A, "s1"))

        assert store.get(HubScopedKey(_HUB_B, "s1")) == "frame-from-b"


class TestForHub:
    def test_yields_only_the_named_hubs_entries(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-a1")
        store.put(HubScopedKey(_HUB_A, "s2"), "frame-a2")
        store.put(HubScopedKey(_HUB_B, "s1"), "frame-b1")

        result = dict(store.for_hub(_HUB_A))

        assert result == {"s1": "frame-a1", "s2": "frame-a2"}

    def test_a_hub_with_no_entries_yields_nothing(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert list(store.for_hub(_HUB_A)) == []


class TestEntries:
    def test_yields_every_entry_across_every_hub_with_its_full_key(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        key_a = HubScopedKey(_HUB_A, "s1")
        key_b = HubScopedKey(_HUB_B, "s1")
        store.put(key_a, "frame-a")
        store.put(key_b, "frame-b")

        result = dict(store.entries())

        assert result == {key_a: "frame-a", key_b: "frame-b"}

    def test_an_empty_store_yields_nothing(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert list(store.entries()) == []


class TestPurgeHubNotIn:
    def test_drops_entries_the_hub_owns_that_are_absent_from_the_manifest(
        self,
    ) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-a1")
        store.put(HubScopedKey(_HUB_A, "s2"), "frame-a2")

        dropped = store.purge_hub_not_in(_HUB_A, frozenset({"s1"}))

        assert dropped == ["frame-a2"]
        assert store.get(HubScopedKey(_HUB_A, "s1")) == "frame-a1"
        assert store.get(HubScopedKey(_HUB_A, "s2")) is None

    def test_never_touches_a_second_live_hubs_entries(self) -> None:
        """The manifest-purge cross-Hub data-loss hazard this method exists to close."""
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-a1")
        store.put(HubScopedKey(_HUB_B, "s1"), "frame-b1")

        store.purge_hub_not_in(_HUB_A, frozenset())

        assert store.get(HubScopedKey(_HUB_B, "s1")) == "frame-b1"

    def test_a_hub_with_no_entries_purges_nothing(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert store.purge_hub_not_in(_HUB_A, frozenset()) == []


class TestDropHub:
    def test_retires_every_entry_the_hub_owned(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-a1")
        store.put(HubScopedKey(_HUB_A, "s2"), "frame-a2")

        dropped = store.drop_hub(_HUB_A)

        assert sorted(dropped) == ["frame-a1", "frame-a2"]
        assert list(store.for_hub(_HUB_A)) == []

    def test_never_touches_a_second_live_hubs_entries(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "frame-a1")
        store.put(HubScopedKey(_HUB_B, "s1"), "frame-b1")

        store.drop_hub(_HUB_A)

        assert store.get(HubScopedKey(_HUB_B, "s1")) == "frame-b1"

    def test_a_hub_with_no_entries_drops_nothing(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        assert store.drop_hub(_HUB_A) == []


class TestReassignValue:
    """The ownership-transfer primitive a departed client's co-owned scenes
    reassign through (``FrameBook.reassign_scenes_of``). Collision safety here
    is sharper than most: the entries being told apart share not just the
    local id but the *value* being reassigned away from, so a hub-blind
    implementation would silently reassign a second Hub's identically-placed
    entry too."""

    def test_reassigns_every_matching_entry_the_hub_owns(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "old")
        store.put(HubScopedKey(_HUB_A, "s2"), "old")

        store.reassign_value(_HUB_A, "old", "new", frozenset({"s1", "s2"}))

        assert store.get(HubScopedKey(_HUB_A, "s1")) == "new"
        assert store.get(HubScopedKey(_HUB_A, "s2")) == "new"

    def test_never_touches_a_second_hubs_identically_local_and_valued_entry(
        self,
    ) -> None:
        """The collision this method exists to close: Hub B's entry shares the
        same local id *and* the same old value, yet a reassignment scoped to
        Hub A must leave it untouched."""
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "old")
        store.put(HubScopedKey(_HUB_B, "s1"), "old")

        store.reassign_value(_HUB_A, "old", "new", frozenset({"s1"}))

        assert store.get(HubScopedKey(_HUB_A, "s1")) == "new"
        assert store.get(HubScopedKey(_HUB_B, "s1")) == "old"

    def test_respects_the_locals_filter(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "old")
        store.put(HubScopedKey(_HUB_A, "s2"), "old")

        store.reassign_value(_HUB_A, "old", "new", frozenset({"s1"}))

        assert store.get(HubScopedKey(_HUB_A, "s1")) == "new"
        assert store.get(HubScopedKey(_HUB_A, "s2")) == "old"

    def test_leaves_an_entry_whose_value_does_not_match_old_untouched(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "keep-me")

        store.reassign_value(_HUB_A, "old", "new", frozenset({"s1"}))

        assert store.get(HubScopedKey(_HUB_A, "s1")) == "keep-me"


class TestRemoveMatchingHubValue:
    """The whole-frame collision-safe removal :meth:`forget_scenes_of_frame`
    is built on -- scoped by owning Hub, not merely by value, so a second
    Hub's identically-valued entries are never candidates."""

    def test_removes_every_entry_the_hub_owns_with_the_matching_value(self) -> None:
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "f1")
        store.put(HubScopedKey(_HUB_A, "s2"), "f1")

        removed = store.remove_matching_hub_value(_HUB_A, "f1")

        assert sorted(k.local for k in removed) == ["s1", "s2"]
        assert store.get(HubScopedKey(_HUB_A, "s1")) is None
        assert store.get(HubScopedKey(_HUB_A, "s2")) is None

    def test_never_touches_a_second_hubs_identically_named_and_valued_entry(
        self,
    ) -> None:
        """The collision this method exists to close: Hub B names the same
        local id *and* points at the same value (its own identically-id'd
        frame) as Hub A -- a value-only match would remove both."""
        store: HubScopedStore[str] = HubScopedStore()
        store.put(HubScopedKey(_HUB_A, "s1"), "f1")
        store.put(HubScopedKey(_HUB_B, "s1"), "f1")

        store.remove_matching_hub_value(_HUB_A, "f1")

        assert store.get(HubScopedKey(_HUB_B, "s1")) == "f1"
