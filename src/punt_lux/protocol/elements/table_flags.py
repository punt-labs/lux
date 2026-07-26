"""``TableFlags`` — the basic grid's render flags as a typed value object.

Replaces the legacy ``list[str]``-with-a-comment (``borders`` / ``row_bg`` /
``resizable`` / ``sortable`` / ``copy_id``) with five booleans, so an unknown
flag is rejected at the wire boundary instead of silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Self

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["TableFlags"]


@dataclass(frozen=True, slots=True)
class TableFlags:
    """The grid's render flags. Defaults match the legacy ``borders``/``row_bg``.

    ``sortable`` enables a real, Display-local column sort; ``copy_id`` makes a
    row's key value click-to-copy; ``resizable`` lets the user drag column
    borders. ``to_wire`` emits only the set flags, in a fixed order.
    """

    borders: bool = True
    row_bg: bool = True
    resizable: bool = False
    sortable: bool = False
    copy_id: bool = False

    _ORDER: ClassVar[tuple[str, ...]] = (
        "borders",
        "row_bg",
        "resizable",
        "sortable",
        "copy_id",
    )

    @classmethod
    def from_wire(cls, flags: Iterable[str]) -> Self:
        """Build from a list of set-flag names; an unknown name raises ``ValueError``.

        The wire form is the list of *enabled* flags — a name present means the
        flag is on. A name outside the known set is a wire error, not a value to
        ignore (PY-EH-1).
        """
        known = set(cls._ORDER)
        chosen = set(flags)
        unknown = chosen - known
        if unknown:
            msg = (
                f"unknown table flag(s) {sorted(unknown)}; "
                f"valid flags are {list(cls._ORDER)}"
            )
            raise ValueError(msg)
        return cls(
            borders="borders" in chosen,
            row_bg="row_bg" in chosen,
            resizable="resizable" in chosen,
            sortable="sortable" in chosen,
            copy_id="copy_id" in chosen,
        )

    def to_wire(self) -> list[str]:
        """Return the set flags as a name list, in the canonical order."""
        enabled = {
            "borders": self.borders,
            "row_bg": self.row_bg,
            "resizable": self.resizable,
            "sortable": self.sortable,
            "copy_id": self.copy_id,
        }
        return [name for name in self._ORDER if enabled[name]]
