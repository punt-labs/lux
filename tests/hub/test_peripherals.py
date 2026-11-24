"""A second kind cannot impersonate or interfere with the Display endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from runpy import run_path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

import punt_lux.hub as hub_module
import punt_lux.hub.clients as clients_module
import punt_lux.hub.hub_composition as composition
import punt_lux.hub.peripherals as peripherals_module
from punt_lux.hub.clients import ClientRegistry
from punt_lux.hub.display_peripheral_port import DisplayPeripheralPort
from punt_lux.hub.peripheral_key import PeripheralKey
from punt_lux.hub.peripheral_registry import PeripheralRegistry
from punt_lux.hub.peripherals import DISPLAY
from punt_lux.operations.display_control import DisplayControlOperations
from punt_lux.operations.display_facts import DisplayFactProxy
from punt_lux.service.display_paths import DisplayPaths
from punt_lux.wire.model import QueryResponse
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.query_geometry import GeometryUnavailable


@dataclass(frozen=True, slots=True)
class _Audio:
    is_connected: bool = True


def test_composition_registers_exactly_one_display_under_the_display_key() -> None:
    source = peripherals_module.__file__
    assert source is not None
    with patch.object(
        PeripheralRegistry,
        "register",
        autospec=True,
        side_effect=PeripheralRegistry.register,
    ) as register:
        namespace = run_path(source)
    registry = cast("PeripheralRegistry", namespace["peripherals"])
    key = cast("PeripheralKey[DisplayPeripheralPort]", namespace["DISPLAY"])
    endpoint = registry.require(key)
    assert key.kind == "display"
    assert key.capability == "ui-replica"
    assert isinstance(endpoint, ClientRegistry)
    assert not endpoint.is_connected
    register.assert_called_once_with(registry, key, endpoint)


@pytest.mark.parametrize("connected", [True, False])
def test_audio_never_substitutes_for_missing_display(
    monkeypatch: pytest.MonkeyPatch, connected: bool
) -> None:
    registry = PeripheralRegistry()
    display = ClientRegistry()
    audio = PeripheralKey[_Audio]("audio", "playback")
    registry.register(DISPLAY, display)
    registry.register(audio, _Audio(connected))
    monkeypatch.setattr(composition, "peripherals", registry)
    monkeypatch.setattr(DisplayPaths, "is_running", MagicMock(return_value=False))
    asks = MagicMock(side_effect=AssertionError("unexpected dial"))
    monkeypatch.setattr(display, "asks", asks)
    port = composition.HubComposition.display_port()
    assert registry.require(audio).is_connected is connected
    assert not port.is_connected
    error = DisplayControlOperations(port).screenshot()
    assert isinstance(error, OpError)
    assert error.code == "display_unavailable"
    assert error.reason == "display is not running"
    geometry = DisplayFactProxy(port).geometry("scene")
    assert isinstance(geometry, GeometryUnavailable)
    assert geometry.reason == "display is not running"
    asks.assert_not_called()


def test_screenshot_routes_only_through_selected_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PeripheralRegistry()
    display = ClientRegistry()
    audio = PeripheralKey[_Audio]("audio", "playback")
    registry.register(DISPLAY, display)
    registry.register(audio, _Audio())
    monkeypatch.setattr(composition, "peripherals", registry)
    monkeypatch.setattr(DisplayPaths, "is_running", MagicMock(return_value=True))
    query = MagicMock(
        return_value=QueryResponse(
            method="screenshot", result={"path": "/display/capture.png"}
        )
    )
    monkeypatch.setattr(
        display,
        "asks",
        lambda: SimpleNamespace(query=query, connection_id="display-dial"),
    )
    control = DisplayControlOperations(composition.HubComposition.display_port())
    screenshot = control.screenshot()
    assert not isinstance(screenshot, OpError)
    assert screenshot.path == "/display/capture.png"
    query.assert_called_once_with("screenshot", {})
    assert registry.require(audio).is_connected


def test_old_display_singleton_is_not_exported() -> None:
    assert not hasattr(hub_module, "client_registry")
    assert not hasattr(clients_module, "client_registry")
