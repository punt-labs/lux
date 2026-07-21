"""The thin adapter formatters render typed results as legacy status lines."""

from __future__ import annotations

from punt_lux.operations import DisplayModeState, OpError, SceneShown
from punt_lux.tools.tools import _format_display_mode, _format_scene


def test_format_scene_renders_success() -> None:
    assert _format_scene(SceneShown(scene_id="s1")) == "shown:s1"


def test_format_scene_renders_an_error_with_its_reason() -> None:
    error = OpError(code="rejected", reason="scene not rendered — bad")
    assert _format_scene(error) == "error: scene not rendered — bad"


def test_format_display_mode_renders_the_mode() -> None:
    assert _format_display_mode(DisplayModeState(mode="on")) == "display:on"
    assert _format_display_mode(DisplayModeState(mode="off")) == "display:off"
