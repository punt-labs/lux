"""ReconnectWait — one wait_for_reconnect call's two inputs, bundled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final


@final
@dataclass(frozen=True, slots=True)
class ReconnectWait:
    """A reconnect-generation snapshot plus how long to wait past it."""

    since_gen: int
    timeout: float
