"""compose_or_reject — the one ValueError-to-OpError boundary DES-086 shares.

``ConnectionScopedId.compose`` raises ``ValueError`` for a caller-unrepresentable
local id (blank, or carrying the unit separator) — a value-producing function
whose input the caller cannot satisfy is a boundary error, not a silent
fallback (PY-EH-8). Every write choke point that composes a store key —
``SceneInstaller.install``, ``SceneOperations.update``, ``SceneClearer.clear``
— hits the identical exception and reports it the identical way
``RenderRequest.parse`` already reports its own rejections. One function
means the mapping is proven once, not re-typed at each call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["compose_or_reject"]


def compose_or_reject[T](compose: Callable[[], T]) -> T | OpError:
    """Return ``compose()``, or the ``OpError`` its ``ValueError`` reports."""
    try:
        return compose()
    except ValueError as exc:
        return OpError(code="invalid_request", reason=str(exc))
