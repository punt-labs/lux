"""DisplayModeOperations — read and write a project's display-mode config.

The mode lives in ``<repo>/.punt-labs/lux.md``. Turning it on eagerly connects
to the display so the first render does not pay the connect cost. The client
registry is given at construction so the eager connect is a real collaborator in
a test without a running display.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

from punt_lux.config import ConfigManager
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
        config = ConfigManager(config_path=Path(repo) / ".punt-labs" / "lux.md").read()
        return DisplayModeState.from_config(config.display)

    def write_display_mode(
        self, request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Persist the mode; eagerly connect to the display when turning on."""
        if isinstance(request, OpError):
            return request
        field = "y" if request.mode == "on" else "n"
        config = ConfigManager(config_path=Path(request.repo) / ".punt-labs" / "lux.md")
        config.write_field("display", field)
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
