"""What the daemon knows about a session at birth: its id, label and request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.wire.stream.new_request import NewRequest


@dataclass(frozen=True, slots=True)
class SessionSpec:
    """A session's identity plus the request that started it.

    Only the login shell, named by the empty launcher, is listed today, so a
    spec for any other launcher cannot exist.
    """

    name: str
    label: str
    request: NewRequest

    def __post_init__(self) -> None:
        if self.request.launcher:
            raise ValueError(f"unknown launcher {self.request.launcher!r}")

    @property
    def cols(self) -> int:
        return self.request.cols

    @property
    def rows(self) -> int:
        return self.request.rows

    def identity(self) -> dict[str, object]:
        """Return the fields that name this session in a listing."""
        return {
            "session": self.name,
            "label": self.label,
            "launcher": self.request.launcher,
        }
