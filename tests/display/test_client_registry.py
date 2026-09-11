"""ClientRegistry -- the per-fd maps a connected client's state lives in."""

from __future__ import annotations

from punt_lux.display.client_registry import ClientRegistry
from punt_lux.domain.identity import HubId

_HUB = HubId("pembroke", 123)


def test_register_connection_gives_a_fresh_reader() -> None:
    registry = ClientRegistry()

    registry.register_connection(10, sock=object())  # type: ignore[arg-type]  # test double

    assert registry.reader_for(10) is not None


def test_reader_for_an_unregistered_fd_is_none() -> None:
    registry = ClientRegistry()

    assert registry.reader_for(10) is None


def test_identify_records_kind_name_hub_id_and_connect_time() -> None:
    registry = ClientRegistry()

    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=1.5)

    assert registry.kind_of(10) == "hub"
    assert registry.client_names[10] == "lux-mcp"
    assert registry.hub_id_of(10) == _HUB
    assert registry.client_connect_times[10] == 1.5


def test_kind_of_before_identify_is_none() -> None:
    registry = ClientRegistry()

    assert registry.kind_of(10) is None


def test_hub_id_of_before_identify_is_none() -> None:
    registry = ClientRegistry()

    assert registry.hub_id_of(10) is None


def test_hub_fd_for_finds_the_named_hub_connection() -> None:
    registry = ClientRegistry()
    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=0.0)

    assert registry.hub_fd_for("lux-mcp") == 10


def test_hub_fd_for_ignores_a_test_kind_connection_with_the_same_name() -> None:
    registry = ClientRegistry()
    registry.identify(10, kind="test", name="lux-mcp", hub_id=_HUB, connect_time=0.0)

    assert registry.hub_fd_for("lux-mcp") is None


def test_hub_fd_for_an_absent_name_is_none() -> None:
    registry = ClientRegistry()

    assert registry.hub_fd_for("lux-mcp") is None


def test_forget_connection_drops_everything_but_the_hub_id() -> None:
    registry = ClientRegistry()
    registry.register_connection(10, sock=object())  # type: ignore[arg-type]  # test double
    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=0.0)

    registry.forget_connection(10)

    assert registry.reader_for(10) is None
    assert 10 not in registry.fd_to_client
    assert registry.kind_of(10) is None
    assert registry.hub_id_of(10) == _HUB  # survives -- may still be resolved once


def test_forget_hub_id_drops_the_last_surviving_fact() -> None:
    registry = ClientRegistry()
    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=0.0)
    registry.forget_connection(10)

    registry.forget_hub_id(10)

    assert registry.hub_id_of(10) is None


def test_clear_drops_every_connections_state() -> None:
    registry = ClientRegistry()
    registry.register_connection(10, sock=object())  # type: ignore[arg-type]  # test double
    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=1.0)

    registry.clear()

    assert registry.reader_for(10) is None
    assert 10 not in registry.fd_to_client
    assert registry.kind_of(10) is None
    assert registry.hub_id_of(10) is None
    assert 10 not in registry.client_connect_times


def test_clear_prevents_a_recycled_fd_from_inheriting_a_departed_identity() -> None:
    """A listener reused after shutdown must not treat a fresh fd as identified."""
    registry = ClientRegistry()
    registry.identify(10, kind="hub", name="lux-mcp", hub_id=_HUB, connect_time=0.0)

    registry.clear()
    registry.register_connection(10, sock=object())  # type: ignore[arg-type]  # test double

    assert registry.kind_of(10) is None
    assert registry.hub_id_of(10) is None
    assert registry.hub_fd_for("lux-mcp") is None
