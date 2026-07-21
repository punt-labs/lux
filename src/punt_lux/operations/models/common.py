"""The shared discriminated error every operation may return."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["OpError", "OpErrorCode"]

# The closed set a caller branches on; the reason is the human sentence.
OpErrorCode = Literal[
    "display_unavailable",  # the display process is not running
    "timeout",  # a proxied round-trip exceeded its bound
    "rejected",  # the Hub refused a malformed or invalid write
    "invalid_request",  # the request itself did not type-check
    "not_found",  # the named scene or resource does not exist
]


class OpError(BaseModel):
    """A capability failed; ``code`` is machine-branchable, ``reason`` is prose.

    Tagged ``kind="error"`` so a discriminated result cannot be both a success
    and a failure at once. ``reason`` carries the bare cause with no surface
    wording — each adapter adds its own prefix (``"scene not rendered — "``,
    ``"scene not updated — "``) when it renders the legacy status line.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["error"] = "error"
    code: OpErrorCode
    reason: str
