"""Typed, identity-bearing keys for Hub-local peripheral contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from punt_lux.hub.peripheral_ports import PeripheralStatus

__all__ = ["PeripheralKey"]


@dataclass(frozen=True, slots=True, eq=False)
class PeripheralKey[P: PeripheralStatus]:
    """Name a kind and its typed capability; only this key can resolve its port."""

    kind: str
    capability: str

    def bind(self, endpoint: P) -> tuple[Self, P]:
        """Pair this contract key with its endpoint for registry storage."""
        return self, endpoint
