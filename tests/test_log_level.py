"""Preserve severity selection for applets importing the legacy Lux helper."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.log_level import level_from_env

if TYPE_CHECKING:
    import pytest


def test_the_log_level_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUX_LOG_LEVEL", "info")
    assert level_from_env("WARNING") == logging.INFO


def test_an_unusable_log_level_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUX_LOG_LEVEL", "chatty")
    assert level_from_env("WARNING") == logging.WARNING


def test_an_emptied_log_level_reads_as_unset_rather_than_as_a_mistake(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LUX_LOG_LEVEL", "")
    assert level_from_env("WARNING") == logging.WARNING
    assert capsys.readouterr().err == ""


def test_an_unset_log_level_leaves_the_entry_point_its_own_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUX_LOG_LEVEL", raising=False)
    assert level_from_env("WARNING") == logging.WARNING
    assert level_from_env("INFO") == logging.INFO


def test_an_explicit_level_reaches_the_display_the_operator_asked_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUX_LOG_LEVEL", "DEBUG")
    assert level_from_env("INFO") == logging.DEBUG
