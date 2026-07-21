"""DisplayModeOperations — coordinate a project's display-mode config; the file's
path and I/O belong to DisplayModeStore, so a config failure surfaces as a fault."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.display_mode_store import DisplayModeStore
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.config import DisplayModeRequest, DisplayModeState

if TYPE_CHECKING:
    from punt_lux.domain.hub.clients import ClientRegistry

__all__ = ["DisplayModeOperations"]

logger = logging.getLogger(__name__)


@final
class DisplayModeOperations:
    """Read and write the per-project display mode."""

    _client_registry: ClientRegistry
    __slots__ = ("_client_registry",)

    def __new__(cls, client_registry: ClientRegistry) -> Self:
        self = super().__new__(cls)
        self._client_registry = client_registry
        return self

    def read_display_mode(self, repo: str) -> DisplayModeState | OpError:
        """Return the mode ``<repo>/.punt-labs/lux.md`` records, or an ``OpError``."""
        repo_error = DisplayModeRequest.check_repo(repo)
        if repo_error is not None:
            return repo_error
        return DisplayModeStore(repo).read()

    def write_display_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Persist the mode; eagerly connect to the display when turning on."""
        if isinstance(request, OpError):
            return request
        return self._apply(request)

    def _apply(self, request: DisplayModeRequest) -> DisplayModeState | OpError:
        """Write the field and eager-connect, surfacing a config I/O ``fault``."""
        fault = DisplayModeStore(request.repo).write(
            "y" if request.mode == "on" else "n"
        )
        if fault is not None:
            return fault
        if request.mode == "on":
            self._eager_connect()
        return DisplayModeState(mode=request.mode)

    def _eager_connect(self) -> None:
        """Best-effort connect on turning the display on; retry on first tool call."""
        try:
            self._client_registry.get()
        except (RuntimeError, OSError, ValueError, KeyError):
            logger.warning(
                "Eager connect on display mode on failed; "
                "will retry on first tool call",
                exc_info=True,
            )
