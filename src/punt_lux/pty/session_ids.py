"""Daemon-assigned session ids that are never reused, even across restarts."""

from __future__ import annotations

import re
import secrets
from itertools import count
from typing import Self


class SessionIds:
    """Produce ``t<boot>.<n>``: ``boot`` is fixed per daemon start, ``n`` counts.

    The boot value is random, so an id issued before a restart cannot name a
    session issued after it.
    """

    _boot: str
    _counter: count[int]

    def __new__(cls, boot: str) -> Self:
        if re.fullmatch(r"[0-9a-f]{1,16}", boot) is None:
            raise ValueError(f"boot value must be lowercase hex: {boot!r}")
        self = super().__new__(cls)
        self._boot = boot
        self._counter = count(1)
        return self

    @classmethod
    def fresh(cls) -> Self:
        """Start a sequence under a new random boot value."""
        return cls(secrets.token_hex(4))

    def next(self) -> str:
        """Return the next id; no id is ever returned twice."""
        return f"t{self._boot}.{next(self._counter)}"
