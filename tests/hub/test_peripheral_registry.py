"""Static peripheral selection, lifecycle ordering and wiring failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

import pytest

from punt_lux.hub.peripheral_key import PeripheralKey
from punt_lux.hub.peripheral_registry import PeripheralRegistry


@dataclass(frozen=True, slots=True)
class _Endpoint:
    is_connected: bool = False


class _Workers:
    _log: list[str]
    _name: str
    _fail: str

    def __new__(cls, log: list[str], name: str, fail: str = "") -> Self:
        self = super().__new__(cls)
        self._log, self._name, self._fail = log, name, fail
        return self

    def start(self) -> None:
        self._log.append(f"{self._name}.start")
        if self._fail == "start":
            raise RuntimeError("start failed")

    def stop(self) -> None:
        self._log.append(f"{self._name}.stop")
        if self._fail == "stop":
            raise RuntimeError("stop failed")


def test_empty_registry_lifecycle_and_missing_lookup() -> None:
    registry = PeripheralRegistry()
    registry.start()
    registry.stop()
    with pytest.raises(LookupError, match="not registered: audio/playback"):
        registry.require(PeripheralKey[_Endpoint]("audio", "playback"))


def test_lookup_preserves_identity_and_requires_the_registered_key() -> None:
    registry = PeripheralRegistry()
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    endpoint = _Endpoint()
    registry.register(key, endpoint)
    assert registry.require(key) is endpoint
    assert not registry.require(key).is_connected
    with pytest.raises(LookupError, match="not registered"):
        registry.require(PeripheralKey[_Endpoint]("display", "ui-replica"))


@pytest.mark.parametrize("capability", ["ui-replica", "other-capability"])
def test_duplicate_kind_cannot_replace_endpoint(capability: str) -> None:
    registry = PeripheralRegistry()
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    endpoint = _Endpoint()
    registry.register(key, endpoint)
    with pytest.raises(ValueError, match="kind already registered: display"):
        registry.register(
            PeripheralKey[_Endpoint]("display", capability), _Endpoint(True)
        )
    assert registry.require(key) is endpoint
    with pytest.raises(ValueError, match="kind already registered"):
        registry.register(key, endpoint)


def test_worker_binding_requires_registration_and_is_once_only() -> None:
    registry = PeripheralRegistry()
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    log: list[str] = []
    workers = _Workers(log, "display")
    with pytest.raises(LookupError, match="not registered"):
        registry.bind_workers(key, workers)
    registry.register(key, _Endpoint())
    registry.bind_workers(key, workers)
    with pytest.raises(ValueError, match="workers already bound: display"):
        registry.bind_workers(key, _Workers(log, "replacement"))
    registry.start()
    registry.stop()
    assert log == ["display.start", "display.stop"]


@pytest.mark.parametrize("action", ["start", "stop"])
def test_incomplete_binding_does_not_partially_run_workers(action: str) -> None:
    registry = PeripheralRegistry()
    display = PeripheralKey[_Endpoint]("display", "ui-replica")
    audio = PeripheralKey[_Endpoint]("audio", "playback")
    log: list[str] = []
    registry.register(display, _Endpoint())
    registry.register(audio, _Endpoint(True))
    registry.bind_workers(display, _Workers(log, "display"))
    with pytest.raises(LookupError, match="workers are not bound"):
        getattr(registry, action)()
    assert log == []
    registry.bind_workers(audio, _Workers(log, "audio"))
    getattr(registry, action)()
    assert len(log) == 2


@pytest.mark.parametrize("action", ["start", "stop"])
def test_lifecycle_freezes_endpoint_and_worker_registration(action: str) -> None:
    registry = PeripheralRegistry()
    display = PeripheralKey[_Endpoint]("display", "ui-replica")
    registry.register(display, _Endpoint())
    registry.bind_workers(display, _Workers([], "display"))
    getattr(registry, action)()
    with pytest.raises(RuntimeError, match="registration is frozen"):
        registry.register(PeripheralKey[_Endpoint]("audio", "playback"), _Endpoint())
    with pytest.raises(RuntimeError, match="registration is frozen"):
        registry.bind_workers(display, _Workers([], "replacement"))


def test_workers_follow_endpoint_registration_not_binding_order() -> None:
    registry = PeripheralRegistry()
    display = PeripheralKey[_Endpoint]("display", "ui-replica")
    audio = PeripheralKey[_Endpoint]("audio", "playback")
    log: list[str] = []
    registry.register(display, _Endpoint())
    registry.register(audio, _Endpoint(True))
    registry.bind_workers(audio, _Workers(log, "audio"))
    registry.bind_workers(display, _Workers(log, "display"))
    registry.start()
    registry.stop()
    assert log == ["display.start", "audio.start", "audio.stop", "display.stop"]


@pytest.mark.parametrize("action", ["start", "stop"])
def test_worker_errors_propagate_without_retry(action: str) -> None:
    registry = PeripheralRegistry()
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    log: list[str] = []
    registry.register(key, _Endpoint())
    registry.bind_workers(key, _Workers(log, "display", action))
    with pytest.raises(RuntimeError, match=f"{action} failed"):
        getattr(registry, action)()
    assert log == [f"display.{action}"]
