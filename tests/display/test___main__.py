"""The module executable boots the same display entry point as the console script."""

from __future__ import annotations

import runpy
import sys
from unittest.mock import patch

import pytest

from punt_lux.display.luxd_display import DisplayEntryPoint


@pytest.mark.parametrize("options", [[], ["--socket", "", "--test-auto-click"]])
def test_module_forwards_arguments(options: list[str]) -> None:
    with (
        patch.object(sys, "argv", ["luxd-display", *options]),
        patch.object(DisplayEntryPoint, "serve") as serve,
    ):
        runpy.run_module("punt_lux.display", run_name="__main__")
    serve.assert_called_once_with(
        "" if options else None, test_auto_click=bool(options)
    )


def test_invalid_module_option_exits_without_starting() -> None:
    with (
        patch.object(sys, "argv", ["luxd-display", "--unknown-option"]),
        patch.object(DisplayEntryPoint, "serve") as serve,
        pytest.raises(SystemExit) as caught,
    ):
        runpy.run_module("punt_lux.display", run_name="__main__")
    assert caught.value.code == 2
    serve.assert_not_called()
