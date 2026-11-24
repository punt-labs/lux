"""The typed key cannot widen to admit an endpoint with a different contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
