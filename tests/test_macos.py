from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from punt_lux.display.macos import hide_from_dock_and_cmd_tab

if TYPE_CHECKING:
    import pytest


class TestHideFromDockAndCmdTab:
    def test_noop_on_non_darwin(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        with caplog.at_level(logging.WARNING):
            hide_from_dock_and_cmd_tab()
        assert caplog.records == []

    def test_applies_accessory_policy_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        mock_app = MagicMock()
        mock_appkit: Any = MagicMock()
        mock_appkit.NSApplication.sharedApplication.return_value = mock_app
        mock_appkit.NSApplicationActivationPolicyAccessory = 1

        with patch.dict("sys.modules", {"AppKit": mock_appkit}):
            hide_from_dock_and_cmd_tab()

        mock_app.setActivationPolicy_.assert_called_once_with(1)

    def test_logs_warning_on_import_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        # Force the AppKit import to fail by injecting a sentinel that raises.
        import builtins

        real_import = builtins.__import__

        def fail_appkit(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "AppKit":
                raise ImportError("no AppKit in this env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_appkit)
        with caplog.at_level(logging.WARNING):
            hide_from_dock_and_cmd_tab()

        assert any(
            "Accessory activation policy not applied" in r.getMessage()
            for r in caplog.records
        )

    def test_logs_warning_on_runtime_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        mock_appkit: Any = MagicMock()
        mock_appkit.NSApplication.sharedApplication.side_effect = RuntimeError("boom")

        with (
            patch.dict("sys.modules", {"AppKit": mock_appkit}),
            caplog.at_level(logging.WARNING),
        ):
            hide_from_dock_and_cmd_tab()

        assert any("boom" in r.getMessage() for r in caplog.records)
