"""Peripheral keys retain identity and enforce their endpoint contracts."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from punt_lux.hub.peripheral_key import PeripheralKey


@dataclass(frozen=True, slots=True)
class _Endpoint:
    is_connected: bool = False


def test_equal_labels_do_not_make_keys_equal() -> None:
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    namesake = PeripheralKey[_Endpoint]("display", "ui-replica")
    assert key.kind == namesake.kind == "display"
    assert key.capability == namesake.capability == "ui-replica"
    assert key == key
    assert key != namesake
    assert len({key, namesake}) == 2


@pytest.mark.parametrize("field", ["kind", "capability"])
def test_key_labels_are_immutable(field: str) -> None:
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    with pytest.raises(FrozenInstanceError):
        setattr(key, field, "replacement")


def test_binding_preserves_key_and_endpoint_identity() -> None:
    key = PeripheralKey[_Endpoint]("display", "ui-replica")
    endpoint = _Endpoint()
    bound_key, bound_endpoint = key.bind(endpoint)
    assert bound_key is key
    assert bound_endpoint is endpoint


def test_registration_rejects_an_endpoint_missing_the_key_contract(
    tmp_path: Path,
) -> None:
    source = """from typing import Protocol
from punt_lux.hub.peripheral_key import PeripheralKey
from punt_lux.hub.peripheral_ports import PeripheralStatus
from punt_lux.hub.peripheral_registry import PeripheralRegistry

class Audio(PeripheralStatus, Protocol):
    def play(self) -> None: ...

key = PeripheralKey[Audio]("audio", "playback")
registry = PeripheralRegistry()

def configure_audio(endpoint: Audio) -> None:
    registry.register(key, endpoint)

def misconfigure_audio(endpoint: PeripheralStatus) -> None:
    registry.register(key, endpoint)
"""
    path = tmp_path / "peripheral_contract.py"
    path.write_text(source)
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.count("error:") == 1, result.stdout
    assert f"{path.name}:{len(source.splitlines())}: error:" in result.stdout
    assert 'type parameter "P"' in result.stdout
