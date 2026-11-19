"""Session-local output failure; other sessions must still publish their bytes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionFault:
    session: str
    message: str
