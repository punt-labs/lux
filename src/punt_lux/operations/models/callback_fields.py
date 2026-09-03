"""The raw fields a boundary collects before a callback registration validates.

Split from :mod:`punt_lux.operations.models.callbacks` (one class per module)
so :class:`RegisterCallbackRequest` keeps a single, focused parse method.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CallbackFields"]


@dataclass(frozen=True, slots=True)
class CallbackFields:
    """The three raw fields a boundary hands ``RegisterCallbackRequest.parse``.

    Bundles what an MCP tool, a CLI command, and the REST transport each
    collect from their own bare arguments (PY-OO-5, PY-IC-1) -- ``parse``
    itself does the validating, so this carries un-validated strings.
    """

    callback_id: str
    label: str
    frame_id: str | None = None
