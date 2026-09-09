"""RouteDeps — the facade and error mapper, bundled for the routes taking both.

Bundled into one value object so a route class's ``__new__`` takes one
parameter instead of one per collaborator (PY-OO-3). ``DisplayRoutes`` and
``FrameRoutes`` take a ``RouteDeps``; ``SceneRoutes``, ``MenuRoutes``, and
``DisplayModeRoutes`` still take ``ops``/``errors`` as separate constructor
parameters (see :class:`~punt_lux.rest.app.RestSurface`) -- the bundle is not
yet the uniform shape across every route class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["RouteDeps"]


@final
@dataclass(frozen=True, slots=True)
class RouteDeps:
    """The facade and error mapper one REST route class composes."""

    ops: Operations
    errors: HttpErrorMap
