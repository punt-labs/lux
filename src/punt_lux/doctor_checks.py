"""The environment checks ``lux doctor`` reports on that are not about lux itself.

Fonts and the Claude plugin are properties of the machine, not of the display or
the Hub, and answering "is this box set up to render Unicode" takes a table of
platform paths that has no business sitting in the CLI. Each check reports through
a :class:`CheckReporter` the command supplies, so the checking and the tallying
stay apart: this decides what is true, the command decides how to show it.

Every check here is advisory. A missing font degrades rendering and a missing
plugin means lux is not wired into Claude Code, but neither makes the installation
broken, so none of them is reported as required.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, Self, final, runtime_checkable

__all__ = ["CheckReporter", "EnvironmentChecks"]

# The marks a report line carries: passed, failed, or present-but-optional.
_OK = "✓"
_FAIL = "✗"
_OPTIONAL = "—"

_PLUGIN_ID = "lux@punt-labs"

# Where each platform keeps the fonts the display needs, best first. The primary
# carries Latin plus broad Unicode; the other two only matter for symbols and Z
# notation, which is why their absence is a note rather than a failure.
_MACOS_FONTS = {
    "primary": (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ),
    "symbol": ("/System/Library/Fonts/Apple Symbols.ttf",),
    "math": (
        "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
        "/Library/Fonts/STIXTwoMath.otf",
    ),
}
_LINUX_FONTS = {
    "primary": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ),
    "symbol": (
        "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
        "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
    ),
    "math": (
        "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
        "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
    ),
}
# What to tell a user who is missing one. macOS ships all three, so it needs no
# advice; a Linux user gets the package that provides them.
_LINUX_FONT_HINT = " — apt install fonts-dejavu-core or fonts-noto"
_LINUX_MATH_HINT = " — apt install fonts-noto"


@runtime_checkable
class CheckReporter(Protocol):
    """How a check reports one line: its mark, its message, and whether it counts."""

    def __call__(self, symbol: str, message: str, *, required: bool = True) -> None:
        """Record one check's outcome."""
        ...


@final
class EnvironmentChecks:
    """The machine-level checks ``doctor`` runs, reporting through one reporter."""

    _report: CheckReporter
    __slots__ = ("_report",)

    def __new__(cls, report: CheckReporter) -> Self:
        self = super().__new__(cls)
        self._report = report
        return self

    def fonts(self) -> None:
        """Report the display's three fonts, naming the fix for a missing one."""
        known = _MACOS_FONTS if platform.system() == "Darwin" else _LINUX_FONTS
        on_linux = known is _LINUX_FONTS
        self._report_font(
            "Font",
            self._first_existing(known["primary"]),
            missing=f"No Unicode font found{_LINUX_FONT_HINT if on_linux else ''}"
            " (falls back to Latin-only)",
            fatal_when_missing=True,
        )
        self._report_font(
            "Symbol font",
            self._first_existing(known["symbol"]),
            missing="No symbol font found (math symbols may not render)",
            fatal_when_missing=False,
        )
        self._report_font(
            "Math font",
            self._first_existing(known["math"]),
            missing=f"No math font found{_LINUX_MATH_HINT if on_linux else ''}"
            " (Z notation double-struck letters may not render)",
            fatal_when_missing=False,
        )

    def plugin(self) -> None:
        """Report the Claude CLI and whether lux is registered as a plugin."""
        claude = shutil.which("claude")
        if not claude:
            self._report(
                _OPTIONAL, "claude CLI not found (needed for plugin)", required=False
            )
            return
        self._report(_OK, f"claude CLI: {claude}", required=False)
        if self._plugin_installed(claude):
            self._report(_OK, f"Plugin: {_PLUGIN_ID}", required=False)
        else:
            self._report(
                _OPTIONAL, "Plugin not installed (run 'lux install')", required=False
            )

    def _report_font(
        self, label: str, found: str, *, missing: str, fatal_when_missing: bool
    ) -> None:
        """Report one font as found, or as the note that names what to do about it.

        The primary font's absence reads as a failure and the other two as notes,
        but none of the three is *required*: a box without them still runs lux,
        with less of the alphabet.
        """
        if found:
            self._report(_OK, f"{label}: {found}", required=False)
            return
        mark = _FAIL if fatal_when_missing else _OPTIONAL
        self._report(mark, missing, required=False)

    @staticmethod
    def _first_existing(candidates: tuple[str, ...]) -> str:
        """The first candidate path that is a file, or ``""`` when none is.

        Empty means "no font of this kind here", which every caller renders as its
        own advice — a total answer, so no caller has to unwrap an absence.
        """
        return next((p for p in candidates if Path(p).is_file()), "")

    @staticmethod
    def _plugin_installed(claude: str) -> bool:
        """Whether the Claude CLI lists lux among its installed plugins."""
        listed = subprocess.run(  # noqa: S603  # resolved binary, fixed argv
            [claude, "plugin", "list"],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        return _PLUGIN_ID in listed.stdout
