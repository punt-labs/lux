"""Tests for punt_lux.session_cleanup -- isolated MCP session teardown."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.ids import ConnectionId
from punt_lux.session_cleanup import SessionCleanup

if TYPE_CHECKING:
    import pytest


class _RaisingMenu:
    """Stand-in whose menu teardown always raises."""

    def drop_session(self, scope: object) -> None:
        raise RuntimeError("menu teardown exploded")


class _RecordingMenu:
    """Stand-in that records the scopes it was asked to drop."""

    scopes: list[object]
    __slots__ = ("scopes",)

    def __new__(cls) -> _RecordingMenu:
        self = super().__new__(cls)
        self.scopes = []
        return self

    def drop_session(self, scope: object) -> None:
        self.scopes.append(scope)


class TestSessionCleanup:
    def test_failing_leg_does_not_starve_the_other(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A raise in the menu leg must not skip the disconnect leg."""
        disconnected: list[str] = []

        def _record_disconnect(conn: object, drop: object) -> None:
            disconnected.append(str(conn))

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _RaisingMenu())
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        with caplog.at_level(logging.ERROR, logger="punt_lux.session_cleanup"):
            SessionCleanup(ConnectionId("sess-x")).run("sess-x")

        assert disconnected == ["sess-x"]
        assert "leg=menu session_key=sess-x" in caplog.text
        assert "menu teardown exploded" in caplog.text

    def test_failing_disconnect_leg_is_logged_and_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A raise in the disconnect leg is attributed and does not escape."""

        def _boom(conn: object, drop: object) -> None:
            raise RuntimeError("disconnect cascade exploded")

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", _RecordingMenu())
        monkeypatch.setattr("punt_lux.session_cleanup.disconnect_connection", _boom)

        with caplog.at_level(logging.ERROR, logger="punt_lux.session_cleanup"):
            SessionCleanup(ConnectionId("sess-y")).run("sess-y")  # must not raise

        assert "leg=disconnect session_key=sess-y" in caplog.text
        assert "disconnect cascade exploded" in caplog.text

    def test_both_legs_run_on_the_happy_path(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With no failures, both legs run and nothing is logged as an error."""
        menu = _RecordingMenu()
        disconnected: list[str] = []

        def _record_disconnect(conn: object, drop: object) -> None:
            disconnected.append(str(conn))

        monkeypatch.setattr("punt_lux.session_cleanup.OPERATIONS", menu)
        monkeypatch.setattr(
            "punt_lux.session_cleanup.disconnect_connection", _record_disconnect
        )

        with caplog.at_level(logging.ERROR, logger="punt_lux.session_cleanup"):
            SessionCleanup(ConnectionId("sess-z")).run("sess-z")

        assert len(menu.scopes) == 1
        assert disconnected == ["sess-z"]
        assert caplog.text == ""
