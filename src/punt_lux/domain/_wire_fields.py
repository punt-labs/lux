"""``WireFields`` — context value owning the (mapping, kind-name) pair.

Lifted out of ``update.py`` so that module stays at three classes (the
three Update kinds).  Replaces the prior module-level ``_require_str`` /
``_require_mapping`` free functions (PY-OO-7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from punt_lux.domain.ids import ElementId

__all__ = ["WireFields"]


@dataclass(frozen=True, slots=True)
class WireFields:
    """Bind a wire mapping to the Update-kind name it's being decoded into."""

    _data: Mapping[str, object]
    _kind: str

    def require_str(self, field: str) -> str:
        """Return ``data[field]`` as a non-empty str or raise ValueError."""
        raw = self._data.get(field)
        if not isinstance(raw, str) or not raw:
            msg = f"{self._kind}.{field} must be a non-empty str, got {raw!r}"
            raise ValueError(msg)
        return raw

    def require_mapping(self, field: str) -> Mapping[str, object]:
        """Return ``data[field]`` as a mapping or raise ValueError."""
        raw = self._data.get(field)
        if not isinstance(raw, Mapping):
            kind = type(raw).__name__
            msg = f"{self._kind}.{field} must be a mapping, got {kind}"
            raise ValueError(msg)
        return cast("Mapping[str, object]", raw)

    def optional_id(self, field: str) -> ElementId | None:
        """Return ``data[field]`` as ElementId; None if absent; raise if malformed."""
        raw = self._data.get(field)
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw:
            msg = f"{self._kind}.{field} must be str or absent, got {raw!r}"
            raise ValueError(msg)
        return ElementId(raw)

    def require_present(self, field: str) -> object:
        """Return ``data[field]`` raw; raise if the key is absent.

        Distinguishes "missing key" from "explicit ``None``" — the latter
        is a legitimate payload (Copilot CP-6: ``SetProperty.value`` is
        the nullable field in the discriminated update union, and
        ``d.get("value")`` cannot tell those two cases apart).
        """
        if field not in self._data:
            msg = f"{self._kind} missing required field {field!r}"
            raise ValueError(msg)
        return self._data[field]
