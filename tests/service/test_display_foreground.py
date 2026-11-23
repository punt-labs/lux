"""Foreground lifecycle launches the package executable, never a renderer import."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from punt_lux.service.display_foreground import DisplayForeground


@pytest.mark.parametrize(
    "socket", [None, "", "/tmp/display socket", "--display-socket"]
)
@pytest.mark.parametrize("auto_click", [False, True])
def test_exec_preserves_environment_and_forwards_options(
    socket: str | None, auto_click: bool
) -> None:
    with (
        patch(
            "punt_lux.service.display_foreground.importlib.import_module",
            return_value=object(),
        ),
        patch.object(os, "execv", side_effect=SystemExit) as execute,
        pytest.raises(SystemExit),
    ):
        DisplayForeground.serve(socket, test_auto_click=auto_click)
    args = [sys.executable, "-m", "punt_lux.display"]
    if socket is not None:
        args.append(f"--socket={socket}")
    if auto_click:
        args.append("--test-auto-click")
    execute.assert_called_once_with(sys.executable, args)


@pytest.mark.parametrize(
    "missing",
    ["imgui_bundle", "numpy", "PIL", "OpenGL", "PIL.Image", "OpenGL.GL"],
)
def test_missing_extra_does_not_replace_process(missing: str) -> None:
    def load(module: str) -> object:
        if module == missing or module.startswith(f"{missing}."):
            raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
        return object()

    with (
        patch(
            "punt_lux.service.display_foreground.importlib.import_module",
            side_effect=load,
        ),
        patch.object(os, "execv") as execute,
        pytest.raises(ModuleNotFoundError) as caught,
    ):
        DisplayForeground.serve(None)
    assert caught.value.name == missing
    execute.assert_not_called()


def test_exec_failure_is_not_swallowed() -> None:
    with (
        patch(
            "punt_lux.service.display_foreground.importlib.import_module",
            return_value=object(),
        ),
        patch.object(os, "execv", side_effect=OSError("cannot execute")),
        pytest.raises(OSError, match="cannot execute"),
    ):
        DisplayForeground.serve(None)


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("imgui_bundle", True),
        ("imgui_bundle.native", True),
        ("unrelated", False),
        ("", False),
    ],
)
def test_missing_dependency_classification(module: str, expected: bool) -> None:
    assert DisplayForeground.is_dependency(module) is expected
