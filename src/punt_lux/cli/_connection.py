"""Resolve the synchronous Hub client at a CLI boundary."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import typer

from punt_lux.client.facade import LuxClient
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.client._sync_ops import SyncOps
    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)


def connect_client(
    *, identity: ClientIdentity | None = None, timeout: float = 2.0
) -> SyncOps:
    """Return the Hub client for this identity, or report a CLI connection error."""
    try:
        if identity is not None:
            return LuxClient.for_identity(identity, timeout=timeout).sync
        return LuxClient.connect(timeout=timeout).sync
    except HubUnavailableError as exc:
        logger.info("CLI %s failed: luxd unavailable", command_path())
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


def command_path() -> str:
    """Name the running CLI command (``lux ping``) without its arguments."""
    try:  # typer 0.24+ vendors click; earlier typer runs on click itself
        from typer._click.globals import get_current_context
    except ImportError:
        return _click_command_path()
    context = get_current_context(silent=True)
    return context.command_path if context is not None else "lux"


def _click_command_path() -> str:
    """Name the running command from click's own context stack."""
    from click import get_current_context

    context = get_current_context(silent=True)
    return context.command_path if context is not None else "lux"
