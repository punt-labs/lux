"""RouteDeps — the two collaborators every REST route class composes.

Bundled into one value object so a route class's ``__new__`` takes one
parameter instead of one per collaborator (PY-OO-3): every route class in
:mod:`punt_lux.rest` is constructed the identical way, from the facade and
the shared error mapper, never independently.
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
