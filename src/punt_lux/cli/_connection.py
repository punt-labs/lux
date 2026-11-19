"""Resolve the synchronous Hub client at a CLI boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from punt_lux.client.facade import LuxClient
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.domain.hub.client_identity import ClientIdentity


def connect_client(
    *, identity: ClientIdentity | None = None, timeout: float = 2.0
) -> SyncOps:
    """Return the Hub client for this identity, or report a CLI connection error."""
    try:
        if identity is not None:
            return LuxClient.for_identity(identity, timeout=timeout).sync
        return LuxClient.connect(timeout=timeout).sync
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
