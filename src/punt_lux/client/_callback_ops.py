"""``CallbackConvenienceOps`` -- the bare-args ``register_callback`` shape.

Split from :mod:`punt_lux.client._sync_ops` (PY-IC-9: protocols live in their
own module) so this one Protocol's signature stands alone rather than
dragging the aggregate ``SyncOps`` module's average down with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.operations import Ok, OpError

__all__ = ["CallbackConvenienceOps"]


@runtime_checkable
class CallbackConvenienceOps(Protocol):
    """The bare-args ``register_callback`` shape every production caller depends on.

    Distinct from :class:`~punt_lux.commands._ports.CallbackRegisterOps`, whose
    Protocol shape is ``register_callback(request, *, scope)`` for the
    in-process ``Operations`` facade. ``_RestTransport`` carries this shape
    instead, since ``applets/leg.py`` already calls it bare; see
    ``cli/callback.py``'s ``_CallbackRegisterAdapter`` for the one adapter
    between the two.
    """

    def register_callback(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok | OpError:
        """Register a menu callback; ``frame_id`` is applet-only.

        See :meth:`CallbackAccessor.register`.
        """
        ...
