"""Session labels preserve printable Unicode and refuse control characters."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.session_label import SessionLabel


@pytest.mark.parametrize("text", ["", "work", "Büro ☕", "x" * 64])
def test_session_label_accepts(text: str) -> None:
    assert SessionLabel(text).text == text


@pytest.mark.parametrize("text", ["x" * 65, "a\nb", "a\x00", "\x9b2J", "\x7f"])
def test_session_label_refuses(text: str) -> None:
    with pytest.raises(ControlError, match="label"):
        SessionLabel(text)


@pytest.mark.parametrize("text", ["\ud800", "a\udfffb"])
def test_session_label_refuses_unpaired_surrogates(text: str) -> None:
    with pytest.raises(ControlError, match="label"):
        SessionLabel(text)
