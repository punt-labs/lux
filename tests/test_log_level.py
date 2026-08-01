"""The logging floor each entry point starts from, and the one knob that lowers it.

A session applet's stderr belongs to whoever started it and the display writes to
a file of its own, so the floors differ; what they share is this override, which
is how a routine number — the per-click response latency — gets read when someone
is looking.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.log_level import level_from_env

if TYPE_CHECKING:
    import pytest


def test_the_log_level_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one knob that lowers a process's floor, so routine facts can be read.

    A session's stderr is the MCP host's, so it logs at WARNING and its per-click
    response latency — reported at INFO — would otherwise only ever be visible
    when it broke its budget, which is exactly when the number stops being useful.
    """
    monkeypatch.setenv("LUX_LOG_LEVEL", "info")
    assert level_from_env("WARNING") == logging.INFO


def test_an_unusable_log_level_falls_back_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LUX_LOG_LEVEL", "chatty")
    assert level_from_env("WARNING") == logging.WARNING
    assert "not valid" in capsys.readouterr().err


def test_an_unset_log_level_leaves_the_entry_point_its_own_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each entry point picks the floor its stream can afford; absence keeps it."""
    monkeypatch.delenv("LUX_LOG_LEVEL", raising=False)
    assert level_from_env("WARNING") == logging.WARNING
    assert level_from_env("INFO") == logging.INFO
