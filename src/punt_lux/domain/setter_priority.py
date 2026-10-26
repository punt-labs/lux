"""SetterPriority -- which keys of a patch a kind's setters must run first.

A kind whose setters depend on one another names the keys that must run first; every
other key follows in the caller's order. The rule lives here, with the check that a
kind names only keys it has a setter for, so ``Element`` carries the tuple as data and
neither the ordering nor its validation as behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SetterPriority"]


@final
class SetterPriority:
    """The keys a kind's patch setters run first, in this order."""

    _keys: tuple[str, ...]
    __slots__ = ("_keys",)

    def __new__(cls, keys: tuple[str, ...]) -> Self:
        duplicated = sorted({k for k in keys if keys.count(k) > 1})
        if duplicated:
            msg = f"a setter priority names {duplicated} more than once"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._keys = keys
        return self

    @property
    def keys(self) -> tuple[str, ...]:
        """The keys that run first, in the order they run."""
        return self._keys

    def require_setters(self, kind: type) -> None:
        """Refuse a kind that names a key it has no ``_set_<key>`` for.

        ``arrange`` skips a priority key the patch lacks, so a misspelt one would be
        ignored for ever and the ordering it was written to guarantee would silently
        be lost.
        """
        unset = [
            k for k in self._keys if not callable(getattr(kind, f"_set_{k}", None))
        ]
        if unset:
            msg = f"{kind.__name__}._SETTER_PRIORITY names {unset} with no _set_<key>"
            raise TypeError(msg)

    def arrange(self, patch: Mapping[str, object]) -> dict[str, object]:
        """Return the patch's own items, the priority keys first.

        A reorder only: the keys and values are the patch's, so a kind cannot change
        what the judge approved. The judge saw ``patch`` itself, before this.
        """
        first = {k: patch[k] for k in self._keys if k in patch}
        return first | {k: v for k, v in patch.items() if k not in first}
