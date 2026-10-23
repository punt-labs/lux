"""TmpGuard — what a test run leaves behind in its private temp directory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["TmpGuard"]

# Every directory the suite makes for a socket carries this prefix. Each test's
# own are removed when it ends, so a survivor is one made outside a test's window:
# by a module- or session-scoped fixture that never cleaned up after itself.
PREFIX = "lux-"


@final
class TmpGuard:
    """The private temp directory one test session runs in, and its leftovers."""

    _root: Path
    __slots__ = ("_root",)

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def leftovers(self) -> tuple[str, ...]:
        """Return the names of the ``lux-*`` entries still under the root."""
        return tuple(sorted(p.name for p in self._root.glob(f"{PREFIX}*")))

    def assert_clean(self) -> None:
        """Fail naming every ``lux-*`` entry a test left under the root."""
        left = self.leftovers()
        if left:
            msg = f"{len(left)} temp dir(s) outlived the test run: {', '.join(left)}"
            raise AssertionError(msg)
