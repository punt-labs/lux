"""``WireRequire`` — shared wire-boundary isinstance-or-raise checks (PY-EH-1).

A small, reusable pair of type checks for decoding untyped wire values (JSON
``list``/``dict``): return the value narrowed to the expected type, or raise
naming ``where`` and the offending value's actual type. Extracted out of
``tree_node.py`` so a recursive decoder's own module keeps a low, unavoidable
function count — any element with a recursive wire-decoded value family can
reuse it rather than duplicating the two checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast, final

__all__ = ["WireRequire"]


@final
class WireRequire:
    """Stateless isinstance-or-raise checks naming ``where`` on failure."""

    __slots__ = ()

    @staticmethod
    def list_(raw: object, loc: str) -> list[object]:
        """Return ``raw`` as a ``list``, or raise naming ``loc``."""
        if not isinstance(raw, list):
            raise ValueError(f"{loc} must be a list of nodes; got {type(raw).__name__}")
        return cast("list[object]", raw)

    @staticmethod
    def mapping(raw: object, where: str) -> Mapping[str, object]:
        """Return ``raw`` as a ``Mapping``, or raise naming ``where``."""
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be a mapping; got {type(raw).__name__}")
        return cast("Mapping[str, object]", raw)

    @staticmethod
    def string(raw: object, message: str) -> str:
        """Return ``raw`` as a ``str``, or raise ``message`` naming its actual value."""
        if not isinstance(raw, str):
            raise ValueError(f"{message}; got {raw!r}")
        return raw
