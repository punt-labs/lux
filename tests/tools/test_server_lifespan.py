"""Regression tests: MCP session startup holds no display-config state."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp_types.version import LATEST_HANDSHAKE_VERSION

import punt_lux.tools.server as server_module
from punt_lux.hub.mcp_transport import McpHttpTransport
from punt_lux.hub.peripherals import DISPLAY, peripherals

if TYPE_CHECKING:
    import pytest


def _run_session_to_completion() -> None:
    """Exercise the production lifespan, handshake, and connection cleanup."""
    transport = McpHttpTransport()

    app = FastAPI(lifespan=lambda _: transport.lifespan())
    transport.mount(app)
    with TestClient(app, base_url="http://127.0.0.1:8430") as client:
        response = client.post(
            "/mcp?session_key=test",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_HANDSHAKE_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "config-test", "version": "0"},
                },
            },
        )
        response.raise_for_status()
        assert transport.session_count == 1
    assert transport.session_count == 0


class TestSessionStartup:
    """Startup must not read display config or connect to the display."""

    def test_reads_no_display_config(self) -> None:
        """Startup resolves and reads no config file, even when one exists."""
        with (
            patch("punt_lux.service.config.ConfigManager.read") as read,
            patch(
                "punt_lux.service.display_preference.DisplayPreference._main_checkout"
            ) as resolve,
        ):
            _run_session_to_completion()

        read.assert_not_called()
        resolve.assert_not_called()

    def test_does_not_eager_connect(self) -> None:
        """Startup never connects, so it cannot auto-spawn the display."""
        with patch.object(peripherals.require(DISPLAY), "asks") as connect:
            _run_session_to_completion()

        connect.assert_not_called()

    def test_under_launchd_cwd_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With cwd=/ (the launchd case) startup neither reads nor connects."""
        monkeypatch.chdir(Path("/"))
        with (
            patch("punt_lux.service.config.ConfigManager.read") as read,
            patch(
                "punt_lux.service.display_preference.DisplayPreference._main_checkout"
            ) as resolve,
            patch.object(peripherals.require(DISPLAY), "asks") as connect,
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
            patch("punt_lux.service.config.ConfigManager.read") as read,
            patch.object(peripherals.require(DISPLAY), "asks") as connect,
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
                patch("punt_lux.service.config.ConfigManager.read") as read,
                patch(
                    "punt_lux.service.display_preference.DisplayPreference._main_checkout"
                ) as resolve,
            ):
                importlib.reload(server_module)
                read.assert_not_called()
                resolve.assert_not_called()
        finally:
            importlib.reload(server_module)


class TestExplicitEnable:
    """The eager-connect-on-enable side effect was dropped (DES-088), not
    replaced -- setting the display mode moved out of the Hub entirely to a
    direct CLI-local ``DisplayModeStore`` write, which has no live
    ``ClientRegistry`` to eagerly connect through. The display now always
    connects lazily on the first real tool/REST call after mode is turned
    on -- the same fallback path the dropped eager-connect already treated
    as the documented, always-correct behavior."""
