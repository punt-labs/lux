"""identity -- the Hub-identity facade re-exports, and nothing else."""

from __future__ import annotations

from punt_lux.domain import (
    hub_id,
    hub_id_token,
    hub_scoped_key,
    hub_scoped_store,
    identity,
)


def test_all_lists_exactly_the_four_value_types() -> None:
    assert set(identity.__all__) == {
        "HubId",
        "HubIdToken",
        "HubScopedKey",
        "HubScopedStore",
    }


def test_reexports_are_identical_to_their_canonical_module_objects() -> None:
    """A facade re-export, not a copy -- ``is``, not merely ``==``."""
    assert identity.HubId is hub_id.HubId
    assert identity.HubIdToken is hub_id_token.HubIdToken
    assert identity.HubScopedKey is hub_scoped_key.HubScopedKey
    assert identity.HubScopedStore is hub_scoped_store.HubScopedStore


def test_hub_id_built_through_the_facade_works_like_the_real_thing() -> None:
    hub = identity.HubId("pembroke", 123)

    assert hub.wire_token == "pembroke\x1f123"
    assert identity.HubIdToken(hub.wire_token).resolve() == hub


def test_hub_scoped_key_and_store_built_through_the_facade_compose() -> None:
    hub = identity.HubId("pembroke", 123)
    store: identity.HubScopedStore[str] = identity.HubScopedStore()
    key = identity.HubScopedKey(hub, "s1")

    store.put(key, "frame-a")

    assert store.get(key) == "frame-a"
