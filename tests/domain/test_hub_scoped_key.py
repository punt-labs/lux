"""HubScopedKey -- value tests for the aggregated store's real key."""

from __future__ import annotations

from punt_lux.domain.hub_id import HubId
from punt_lux.domain.hub_scoped_key import HubScopedKey


def test_two_keys_with_the_same_hub_and_local_are_equal() -> None:
    hub = HubId("pembroke", 1)
    assert HubScopedKey(hub, "s1") == HubScopedKey(hub, "s1")


def test_two_keys_with_different_hubs_and_the_same_local_are_not_equal() -> None:
    key_a = HubScopedKey(HubId("pembroke", 1), "s1")
    key_b = HubScopedKey(HubId("okinos", 2), "s1")
    assert key_a != key_b


def test_two_keys_with_the_same_hub_and_different_locals_are_not_equal() -> None:
    hub = HubId("pembroke", 1)
    assert HubScopedKey(hub, "s1") != HubScopedKey(hub, "s2")


def test_keys_are_hashable_and_usable_as_dict_keys() -> None:
    hub = HubId("pembroke", 1)
    table = {HubScopedKey(hub, "s1"): "frame-a"}
    assert table[HubScopedKey(hub, "s1")] == "frame-a"
