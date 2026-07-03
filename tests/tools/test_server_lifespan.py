"""Regression tests: MCP session startup holds no display-config state."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import anyio
from mcp.shared.message import SessionMessage

import punt_lux.tools.server as server_module
from punt_lux.tools import run_mcp_session, set_display_mode

if TYPE_CHECKING:
    import pytest


def _run_session_to_completion() -> None:
    """Drive a real MCP session with its read stream already closed.

    ``run_mcp_session`` is the per-connection entry point luxd calls. Passing a
    receive stream whose send end is closed makes ``server.run`` return at once,
    so the whole startup path runs — ContextVar set, private-API guards, lifespan
    enter and exit — without a live client. A config read anywhere in that path,
    not just inside the lifespan, is therefore caught.
    """

    async def _run() -> None:
        send_read, recv_read = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](0)
        send_write, _recv_write = anyio.create_memory_object_stream[SessionMessage](0)
        await send_read.aclose()
        with anyio.fail_after(5):
            await run_mcp_session(recv_read, send_write, session_key="test")

    anyio.run(_run)


class TestSessionStartup:
    """Startup must not read display config or connect to the display."""

    def test_reads_no_display_config(self) -> None:
        """Startup resolves and reads no config file, even when one exists."""
        with (
            patch("punt_lux.config.ConfigManager.read") as read,
            patch("punt_lux.config.resolve_config_path") as resolve,
        ):
            _run_session_to_completion()

        read.assert_not_called()
        resolve.assert_not_called()

    def test_does_not_eager_connect(self) -> None:
        """Startup never connects, so it cannot auto-spawn the display."""
        with patch("punt_lux.domain.hub.clients.client_registry.get") as connect:
            _run_session_to_completion()

        connect.assert_not_called()

    def test_under_launchd_cwd_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With cwd=/ (the launchd case) startup neither reads nor connects."""
        monkeypatch.chdir(Path("/"))
        with (
            patch("punt_lux.config.ConfigManager.read") as read,
            patch("punt_lux.config.resolve_config_path") as resolve,
            patch("punt_lux.domain.hub.clients.client_registry.get") as connect,
        ):
            _run_session_to_completion()

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
            _run_session_to_completion()

        read.assert_not_called()
        connect.assert_not_called()


class TestServerImport:
    """Importing the server module reads no config at module load."""

    def test_import_reads_no_display_config(self) -> None:
        """A module-level config read would fire before per-test spies exist."""
        try:
            with (
                patch("punt_lux.config.ConfigManager.read") as read,
                patch("punt_lux.config.resolve_config_path") as resolve,
            ):
                importlib.reload(server_module)
                read.assert_not_called()
                resolve.assert_not_called()
        finally:
            importlib.reload(server_module)


class TestExplicitEnable:
    """Only explicit set_display_mode(y) eager-connects — startup does not."""

    def test_set_display_mode_y_eager_connects(self, tmp_path: Path) -> None:
        """Enabling display connects immediately, unlike daemon startup."""
        with patch("punt_lux.domain.hub.clients.client_registry.get") as connect:
            assert set_display_mode("y", repo=str(tmp_path)) == "display:on"

        connect.assert_called_once()
