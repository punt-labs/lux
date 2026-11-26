"""The terminal paint boundary preserves the frame and balances the font stack."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from punt_lux.display.terminal.font import TerminalFont
from punt_lux.display.terminal.presenter import TerminalPresenter
from punt_lux.display.terminal.remote_sessions import RemoteSessions
from punt_lux.wire.model.elements.terminal import TerminalElement
from punt_lux.wire.stream.control_fields import ControlError


def test_bad_replica_renders_a_placeholder_without_escaping_the_frame() -> None:
    elem = TerminalElement(id="t", session="s")
    object.__setattr__(elem, "_session", "../legacy")
    with patch("punt_lux.display.terminal.presenter.imgui.text_wrapped") as text:
        TerminalPresenter.paint(elem)
    assert "Terminal unavailable" in text.call_args.args[0]
    assert "identifier" in text.call_args.args[0]


@pytest.mark.parametrize("font", [None, Mock()])
@pytest.mark.parametrize(
    "error", [None, ControlError("bad replica"), RuntimeError("bug")]
)
def test_render_and_error_paths_balance_fonts(
    font: object, error: Exception | None
) -> None:
    session = Mock()
    session.render_in_child.side_effect = error
    with (
        patch.object(RemoteSessions, "get", return_value=session),
        patch.object(TerminalFont, "font", font),
        patch("punt_lux.display.terminal.presenter.imgui.push_font") as push,
        patch("punt_lux.display.terminal.presenter.imgui.pop_font") as pop,
        patch("punt_lux.display.terminal.presenter.imgui.text_wrapped") as text,
    ):
        if isinstance(error, RuntimeError):
            with pytest.raises(RuntimeError, match="bug"):
                TerminalPresenter.paint(TerminalElement(id="t", session="s"))
        else:
            TerminalPresenter.paint(TerminalElement(id="t", session="s"))
        assert push.call_count == pop.call_count == int(font is not None)
        assert text.call_count == int(isinstance(error, ControlError))
        assert session.render_in_child.call_args.args[0] == "##terminal-t"
