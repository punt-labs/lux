"""Both display executable forms boot the same renderer and runtime."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from punt_lux.display.luxd_display import DisplayEntryPoint


@pytest.mark.parametrize("socket", [None, "/tmp/display.sock"])
@pytest.mark.parametrize("auto_click", [False, True])
def test_serve_owns_runtime_and_renderer(socket: str | None, auto_click: bool) -> None:
    with (
        patch("punt_lux.display.luxd_display.RenderLoop") as renderer,
        patch("punt_lux.display.luxd_display.DaemonRuntime") as runtime,
    ):
        DisplayEntryPoint.serve(socket, test_auto_click=auto_click)
    runtime.assert_called_once_with("luxd-display")
    runtime.return_value.run.assert_called_once_with()
    runtime.return_value.run.return_value.__enter__.assert_called_once_with()
    runtime.return_value.run.return_value.__exit__.assert_called_once_with(
        None, None, None
    )
    renderer.assert_called_once_with(socket, test_auto_click=auto_click)
    renderer.return_value.run.assert_called_once_with()


def test_renderer_error_closes_runtime() -> None:
    with (
        patch(
            "punt_lux.display.luxd_display.RenderLoop",
            side_effect=RuntimeError("renderer"),
        ),
        patch("punt_lux.display.luxd_display.DaemonRuntime") as runtime,
        pytest.raises(RuntimeError, match="renderer"),
    ):
        runtime.return_value.run.return_value.__exit__.return_value = False
        DisplayEntryPoint.serve(None)
    runtime.return_value.run.return_value.__exit__.assert_called_once()


def test_entry_point_forwards_arguments() -> None:
    with (
        patch.object(
            sys,
            "argv",
            ["luxd-display", "--socket", "/tmp/display.sock", "--test-auto-click"],
        ),
        patch.object(DisplayEntryPoint, "serve") as serve,
    ):
        DisplayEntryPoint.main()
    serve.assert_called_once_with("/tmp/display.sock", test_auto_click=True)
