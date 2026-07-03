"""Regression tests: the MCP session lifespan holds no display-config state."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from punt_lux.tools.server import mcp

if TYPE_CHECKING:
    import pytest


def _drive_session_startup() -> None:
    """Enter and exit the MCP session lifespan the way a session does.

    ``run_mcp_session`` wraps ``server.run`` in ``mcp._lifespan_manager()``.
    Entering and exiting that context is the daemon's entire startup path, so
    it is the surface these tests exercise.
    """

    async def _run() -> None:
        async with mcp._lifespan_manager():
            pass

    asyncio.run(_run())


class TestSessionStartup:
    """Startup must not read display config or connect to the display."""

    def test_reads_no_display_config(self) -> None:
        """Startup resolves and reads no config file, even when one exists."""
        with (
            patch("punt_lux.config.ConfigManager.read") as read,
            patch("punt_lux.config.resolve_config_path") as resolve,
        ):
            _drive_session_startup()

        read.assert_not_called()
        resolve.assert_not_called()

    def test_does_not_eager_connect(self) -> None:
        """Startup never connects, so it cannot auto-spawn the display."""
        with patch("punt_lux.domain.hub.clients.client_registry.get") as connect:
            _drive_session_startup()

        connect.assert_not_called()

    def test_under_launchd_cwd_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With cwd=/ (the launchd case) startup neither reads nor connects."""
        monkeypatch.chdir(Path("/"))
        with (
            patch("punt_lux.config.ConfigManager.read") as read,
            patch("punt_lux.config.resolve_config_path") as resolve,
            patch("punt_lux.domain.hub.clients.client_registry.get") as connect,
        ):
            _drive_session_startup()

        read.assert_not_called()
        resolve.assert_not_called()
        connect.assert_not_called()

    def test_missing_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """In a directory with no .punt-labs/lux.md, startup still no-ops."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".punt-labs" / "lux.md").exists()
        with (
            patch("punt_lux.config.ConfigManager.read") as read,
            patch("punt_lux.domain.hub.clients.client_registry.get") as connect,
        ):
            _drive_session_startup()

        read.assert_not_called()
        connect.assert_not_called()
