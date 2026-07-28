"""Render an HTTP response body into a human reason for the CLI's REST client.

luxd's error responses and the rare unexpected-2xx body both arrive as raw bytes
the CLI must turn into one printable line. That parsing is a concern of its own —
decode once, pull the reason out of a JSON error shape, bound a preview — so it
lives here as a value the client tells to render itself, rather than a pile of
static helpers the client threads bytes through.
"""

from __future__ import annotations

import json
from typing import Self, cast, final

__all__ = ["ErrorBody"]

# A malformed-2xx fault names a short body preview so a stale/foreign server on
# the old port is recognizable; bounded so a binary or huge body stays safe.
_SNIPPET_LIMIT = 120


@final
class ErrorBody:
    """An HTTP response body decoded once and rendered to a human reason.

    The decode uses ``errors="replace"`` so binary or non-UTF-8 bytes never raise
    past this boundary — a bad-bytes body maps to a reason with replacement
    characters, not a traceback.
    """

    _text: str
    __slots__ = ("_text",)

    def __new__(cls, raw: bytes) -> Self:
        self = super().__new__(cls)
        self._text = raw.decode(errors="replace")
        return self

    def reason(self, status: int) -> str:
        """Render this error body's human reason, never blank or ``None``.

        An empty body falls back to the status line; a blank reason (empty detail
        string, empty detail list) falls back to the decoded body. Since the
        decoded body is non-blank there, the message always carries content.
        """
        if not self._text.strip():
            return f"HTTP {status}"
        reason = self._reason_in()
        return reason if reason.strip() else self._text

    def snippet(self, limit: int = _SNIPPET_LIMIT) -> str:
        """A one-line, printable, bounded preview of the body.

        Non-printable characters collapse to spaces, whitespace runs fold to one,
        and the result is truncated so a huge body cannot bloat the reason.
        """
        printable = "".join(c if c.isprintable() else " " for c in self._text)
        oneline = " ".join(printable.split())
        if len(oneline) <= limit:
            return oneline
        return oneline[:limit] + "…"

    def _reason_in(self) -> str:
        """Pull the human reason from a JSON error body, or the body itself.

        The text is the already-decoded body, so parsing it never raises on
        non-UTF-8 bytes. It is a JSON wire value narrowed here (PY-TS-14): a
        semantic ``OpError`` sends a bare ``detail`` string; a FastAPI binding
        rejection sends ``{loc, msg, type}`` items whose ``msg`` fields are
        joined. Anything else yields the text so its content survives.
        """
        try:
            parsed: object = json.loads(self._text)
        except json.JSONDecodeError:
            return self._text
        if not isinstance(parsed, dict):
            return self._text
        detail: object = cast("dict[str, object]", parsed).get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            items = cast("list[object]", detail)
            return "; ".join(map(self._item_message, items))
        return self._text

    @staticmethod
    def _item_message(item: object) -> str:
        """Render one located-error item as its ``msg``, or itself if not a dict."""
        if not isinstance(item, dict):
            return str(item)
        fields = cast("dict[str, object]", item)
        msg = fields.get("msg")
        return str(msg) if msg is not None else str(fields)
