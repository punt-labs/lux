"""EnvironmentChecks — what ``lux doctor`` says about the machine it runs on.

Every one of these is advisory: a box missing a font or the plugin still runs
lux, so nothing here may report itself as required. That is the property most
worth pinning, because getting it wrong makes ``doctor`` exit non-zero on a
perfectly working installation.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    import pytest

from punt_lux.doctor_checks import EnvironmentChecks

_OK = "✓"
_FAIL = "✗"
_OPTIONAL = "—"
_PLUGIN_ID = "lux@punt-labs"


# Typed stand-ins for the two facts every check reads off the machine: whether a
# path is a file, and where (or whether) the claude CLI is.
def _every_path_is_a_file(_self: Path) -> bool:
    return True


def _no_path_is_a_file(_self: Path) -> bool:
    return False


def _no_claude(_name: str) -> str | None:
    return None


def _claude_at_bin(_name: str) -> str | None:
    return "/bin/claude"


def _plugin_list(stdout: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """A ``claude plugin list`` that answers with ``stdout``.

    Substituted at the subprocess boundary rather than at the method that reads
    it, so what the tests drive is the state the CLI's real output produces.
    """

    def _run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["claude", "plugin", "list"], returncode=0, stdout=stdout, stderr=""
        )

    return _run


def _plugin_list_never_answers(
    *_args: object, **_kwargs: object
) -> subprocess.CompletedProcess[str]:
    """A ``claude plugin list`` that outlasts its bound, as a slow CLI can."""
    raise subprocess.TimeoutExpired(cmd="claude plugin list", timeout=10.0)


def _linux() -> str:
    return "Linux"


def _darwin() -> str:
    return "Darwin"


@final
class _Report:
    """Collect the lines a check reports, with whether each was required."""

    _lines: list[tuple[str, str, bool]]
    __slots__ = ("_lines",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lines = []
        return self

    def __call__(self, symbol: str, message: str, *, required: bool = True) -> None:
        self._lines.append((symbol, message, required))

    @property
    def marks(self) -> list[str]:
        return [symbol for symbol, _message, _required in self._lines]

    @property
    def messages(self) -> list[str]:
        return [message for _symbol, message, _required in self._lines]

    @property
    def any_required(self) -> bool:
        return any(required for _symbol, _message, required in self._lines)


def test_present_fonts_are_reported_by_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.Path.is_file", _every_path_is_a_file)
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).fonts()

    assert report.marks == [_OK, _OK, _OK]
    assert all(".ttf" in m or ".ttc" in m or ".otf" in m for m in report.messages)
    assert report.any_required is False  # advisory, always


def test_missing_fonts_name_the_consequence_without_failing_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No font on the box is a degraded render, not a broken installation."""
    monkeypatch.setattr("punt_lux.doctor_checks.Path.is_file", _no_path_is_a_file)
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).fonts()

    assert report.marks == [_FAIL, _OPTIONAL, _OPTIONAL]
    assert "Latin-only" in report.messages[0]
    assert report.any_required is False  # so doctor still exits 0


def test_linux_names_the_package_that_provides_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.platform.system", _linux)
    monkeypatch.setattr("punt_lux.doctor_checks.Path.is_file", _no_path_is_a_file)
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).fonts()

    assert "apt install" in report.messages[0]
    assert "apt install" in report.messages[2]


def test_macos_offers_no_advice_because_it_ships_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.platform.system", _darwin)
    monkeypatch.setattr("punt_lux.doctor_checks.Path.is_file", _no_path_is_a_file)
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).fonts()

    assert "apt install" not in " ".join(report.messages)


def test_without_the_claude_cli_the_plugin_is_not_asked_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.shutil.which", _no_claude)
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).plugin()

    assert report.marks == [_OPTIONAL]
    assert "claude CLI not found" in report.messages[0]
    assert report.any_required is False


def test_an_installed_plugin_is_reported_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.shutil.which", _claude_at_bin)
    monkeypatch.setattr(
        "punt_lux.doctor_checks.subprocess.run", _plugin_list(f"{_PLUGIN_ID}\n")
    )
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).plugin()

    assert report.marks == [_OK, _OK]
    assert "lux@punt-labs" in report.messages[1]


def test_a_claude_cli_that_never_answers_does_not_hang_doctor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unbounded run makes the whole diagnostic hang on its least vital check.

    Reporting the timeout as an absent plugin would be worse than useless — it
    sends the reader to reinstall a plugin that may be perfectly fine — so no
    answer is its own outcome with its own line.
    """
    monkeypatch.setattr("punt_lux.doctor_checks.shutil.which", _claude_at_bin)
    monkeypatch.setattr(
        "punt_lux.doctor_checks.subprocess.run", _plugin_list_never_answers
    )
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).plugin()

    assert report.marks == [_OK, _OPTIONAL]
    assert "did not answer" in report.messages[1]
    assert "lux install" not in report.messages[1]
    assert report.any_required is False


def test_the_plugin_list_is_run_under_a_time_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound itself, not just its handling: without it there is nothing to catch."""
    seen: dict[str, object] = {}

    def _run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("punt_lux.doctor_checks.shutil.which", _claude_at_bin)
    monkeypatch.setattr("punt_lux.doctor_checks.subprocess.run", _run)
    EnvironmentChecks(_Report(), _PLUGIN_ID).plugin()

    bound = seen.get("timeout")
    assert isinstance(bound, float)
    assert bound > 0


def test_an_absent_plugin_names_the_command_that_installs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("punt_lux.doctor_checks.shutil.which", _claude_at_bin)
    monkeypatch.setattr(
        "punt_lux.doctor_checks.subprocess.run", _plugin_list("other@elsewhere\n")
    )
    report = _Report()
    EnvironmentChecks(report, _PLUGIN_ID).plugin()

    assert report.marks == [_OK, _OPTIONAL]
    assert "lux install" in report.messages[1]
    assert report.any_required is False
