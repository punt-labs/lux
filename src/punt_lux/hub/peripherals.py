"""Process endpoint composition; worker binding follows replicator bootstrap."""

from __future__ import annotations

from punt_lux.hub.clients import ClientRegistry
from punt_lux.hub.display_peripheral_port import DisplayPeripheralPort
from punt_lux.hub.peripheral_key import PeripheralKey
from punt_lux.hub.peripheral_registry import PeripheralRegistry

__all__ = ["DISPLAY", "peripherals"]

DISPLAY = PeripheralKey[DisplayPeripheralPort]("display", "ui-replica")
peripherals = PeripheralRegistry()
peripherals.register(DISPLAY, ClientRegistry())
