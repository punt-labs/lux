"""The thin adapter formatters render typed results as legacy status lines."""

from __future__ import annotations

import pytest

from punt_lux.operations import DisplayModeState, OpError, SceneShown
from punt_lux.tools.tools import _format_display_mode, _format_render, _format_update


def test_format_render_renders_success() -> None:
    assert _format_render(SceneShown(scene_id="s1")) == "shown:s1"


def test_format_render_renders_a_parse_error_without_a_prefix() -> None:
    error = OpError(code="invalid_request", reason="layout must be single, got 'x'")
    assert _format_render(error) == "error: layout must be single, got 'x'"


def test_format_render_prefixes_a_rejection_with_scene_not_rendered() -> None:
    error = OpError(code="rejected", reason="[table 'on_page'] is bad")
    assert (
        _format_render(error) == "error: scene not rendered — [table 'on_page'] is bad"
    )


def test_format_update_renders_success() -> None:
    assert _format_update(SceneShown(scene_id="s1")) == "shown:s1"


def test_format_update_prefixes_a_rejection_with_scene_not_updated() -> None:
    error = OpError(code="rejected", reason="unknown element")
    assert _format_update(error) == "error: scene not updated — unknown element"


def test_format_display_mode_renders_the_mode() -> None:
    assert _format_display_mode(DisplayModeState(mode="on")) == "display:on"
    assert _format_display_mode(DisplayModeState(mode="off")) == "display:off"


def test_format_display_mode_reraises_an_error_as_valueerror() -> None:
    error = OpError(code="invalid_request", reason="Invalid mode 'x'. Use 'y' or 'n'.")
    with pytest.raises(ValueError, match="Invalid mode"):
        _format_display_mode(error)
