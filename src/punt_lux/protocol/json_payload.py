"""JsonPayload -- one frame's bytes, decoded to a JSON object within a depth bound."""

from __future__ import annotations

import json
import re
from typing import Any, Self, cast, final

__all__ = ["MAX_NESTING", "JsonPayload"]

# Brackets one element's wire form may nest: a container adds two a level (its
# object and its children array), and some leaves nest their own data (a tree's
# nodes). 48 allows twenty-odd containers inside each other. The Hub refuses a
# scene past it (domain/nesting_cap.py), so the guard below never meets a reply it
# must refuse.
MAX_ELEMENT_NESTING = 48
# The deepest frame is a display's inspect_scene reply: the response object, its
# result object, the element_paths array, one record and its props -- five
# brackets -- around an element's own wire form, which the Hub caps at
# MAX_ELEMENT_NESTING when it accepts the scene. Hub-to-display messages carry
# elements pickled and nest far less.
_ENVELOPE_NESTING = 5
MAX_NESTING = MAX_ELEMENT_NESTING + _ENVELOPE_NESTING
# Unterminated strings run to the end; possessive repetition keeps the scan linear.
_STRINGS = re.compile(rb'"(?:[^"\\]++|\\.)*+(?:"|\\?\Z)', re.DOTALL)
_BRACKETS = re.compile(rb"[\[\]{}]")
_OPENERS = b"[{"


@final
class JsonPayload:
    """A frame's payload bytes, before they are trusted to be a bounded JSON object."""

    _raw: bytes
    __slots__ = ("_raw",)

    def __new__(cls, raw: bytes) -> Self:
        self = super().__new__(cls)
        self._raw = raw
        return self

    def as_object(self) -> dict[str, Any]:
        """Return the payload as a JSON object, or raise ``ValueError``.

        The nesting is bounded by a scan first, so a deep frame is refused before
        the decoder recurses into it; a decoder that still hits the recursion
        limit is refused the same way.
        """
        self._require_shallow()
        try:
            raw = json.loads(self._raw)
        except RecursionError as exc:
            msg = "JSON payload nests too deeply"
            raise ValueError(msg) from exc
        if not isinstance(raw, dict):
            msg = f"Expected JSON object, got {type(raw).__name__}"
            raise ValueError(msg)
        return cast("dict[str, Any]", raw)

    def _require_shallow(self) -> None:
        """Raise ``ValueError`` when brackets outside strings nest past the bound."""
        depth = 0
        for token in _BRACKETS.finditer(_STRINGS.sub(b'""', self._raw)):
            depth += 1 if token.group() in _OPENERS else -1
            if depth > MAX_NESTING:
                msg = f"JSON payload nests deeper than {MAX_NESTING} levels"
                raise ValueError(msg)
