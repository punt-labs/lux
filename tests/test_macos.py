from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from punt_lux.display.macos import set_regular_activation_policy

if TYPE_CHECKING:
    import pytest


class TestSetRegularActivationPolicy:
    def test_noop_on_non_darwin(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        with caplog.at_level(logging.WARNING):
            set_regular_activation_policy()
        assert caplog.records == []

    def test_applies_regular_policy_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        mock_app = MagicMock()
        mock_appkit: Any = MagicMock()
        mock_appkit.NSApplication.sharedApplication.return_value = mock_app
        mock_appkit.NSApplicationActivationPolicyRegular = 0

        with patch.dict("sys.modules", {"AppKit": mock_appkit}):
            set_regular_activation_policy()

        mock_app.setActivationPolicy_.assert_called_once_with(0)

    def test_logs_warning_on_import_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        import builtins

        real_import = builtins.__import__

        def fail_appkit(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "AppKit":
                raise ImportError("no AppKit in this env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_appkit)
        with caplog.at_level(logging.WARNING):
            set_regular_activation_policy()

        assert any(
            "Regular activation policy not applied" in r.getMessage()
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
            set_regular_activation_policy()

        assert any("boom" in r.getMessage() for r in caplog.records)
