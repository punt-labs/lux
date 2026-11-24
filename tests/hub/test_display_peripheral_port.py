"""The existing Display endpoint satisfies its structural peripheral contract."""

from __future__ import annotations

from punt_lux.hub.clients import ClientRegistry
from punt_lux.hub.display_peripheral_port import DisplayPeripheralPort
from punt_lux.hub.reconnect_signal import ReconnectSignal


def test_client_registry_satisfies_display_peripheral_port() -> None:
    concrete = ClientRegistry()
    port: DisplayPeripheralPort = concrete
    assert port is concrete
    assert not port.is_connected
    assert isinstance(port.reconnects, ReconnectSignal)
