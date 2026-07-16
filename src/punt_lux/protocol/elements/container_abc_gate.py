"""Shared all-ABC gate for the conditionally-ABC container kinds.

A container kind holds children, so it crosses onto its Element-ABC class only
when its *entire subtree* is migrated-ABC; any legacy descendant forks the whole
subtree legacy. That "is my whole subtree all-ABC?" decision is one recursive
walk over the wire dict, shared by the ``group`` and ``collapsing_header``
codecs (and, as it migrates, ``tab_bar``) rather than duplicated per codec
(PY-OO-7). It is a pure function of the wire dict — no element construction, no
imports of the element classes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

from punt_lux.protocol.elements.abc_kind_names import AbcKindNames

__all__ = ["ContainerAbcGate"]

# The two layouts an ABC group renders; ``paged`` stays on the legacy path.
# Group-specific gate logic, not a "which kinds are ABC" fact, so it stays here
# rather than in ``AbcKindNames``.
_STACK_LAYOUTS = frozenset({"rows", "columns"})


class ContainerAbcGate:
    """Decide whether a container wire subtree is entirely migrated-ABC.

    Stateless — every method is a class- or static-method over the wire dict.
    ``is_all_abc`` is the gate the factory and each container's ``from_dict``
    consult to fork onto the ABC path; ``first_non_abc_kind`` names the first
    reason a subtree stays legacy (used in the rejection message).
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def is_all_abc(cls, raw: Mapping[str, object]) -> bool:
        """Return whether ``raw`` is an all-ABC container subtree."""
        return cls.first_non_abc_kind(raw) is None

    @classmethod
    def first_non_abc_kind(cls, raw: Mapping[str, object]) -> str | None:
        """Return the first reason ``raw`` forks legacy, or ``None`` if all-ABC.

        A container-specific self-check runs first (a ``group``'s non-stack
        layout or paged fields fork legacy); then every child in the subtree is
        checked, recursing into nested migrated containers.
        """
        self_reason = cls._self_reason(raw)
        if self_reason is not None:
            return self_reason
        for child in cls._subtree(raw):
            reason = cls._child_non_abc_reason(child)
            if reason is not None:
                return reason
        return None

    @classmethod
    def _self_reason(cls, raw: Mapping[str, object]) -> str | None:
        """Return why the container itself cannot be ABC, or ``None``.

        Only ``group`` carries a self-constraint: a non-stack ``layout`` or
        non-empty ``pages`` / ``page_source`` (panels the ABC group cannot hold)
        fork legacy; empty paged fields decode ABC.
        """
        if raw.get("kind") != "group":
            return None
        layout = raw.get("layout", "rows")
        if layout not in _STACK_LAYOUTS:
            return f"layout={layout!r}"
        if raw.get("pages"):
            return "pages"
        if raw.get("page_source"):
            return "page_source"
        return None

    @classmethod
    def _child_non_abc_reason(cls, raw_child: object) -> str | None:
        """Return why one wire child is not all-ABC, or ``None`` if it is."""
        if not isinstance(raw_child, Mapping):
            return f"non-mapping child {raw_child!r}"
        child = cast("Mapping[str, object]", raw_child)
        kind = child.get("kind")
        if not AbcKindNames.is_migrated(kind):
            return str(kind)
        if AbcKindNames.is_container(kind):
            return cls.first_non_abc_kind(child)
        return None

    @classmethod
    def _subtree(cls, raw: Mapping[str, object]) -> tuple[object, ...]:
        """Return the container's direct child wire dicts.

        ``group`` and ``collapsing_header`` hold their children under the
        ``children`` key; a ``tab_bar`` flattens each tab's ``children``, and a
        non-mapping tab is yielded as-is so the reason check can surface it.
        """
        if raw.get("kind") == "tab_bar":
            return tuple(
                item
                for tab in cls._as_list(raw.get("tabs"))
                for item in (
                    cls._as_list(cast("Mapping[str, object]", tab).get("children"))
                    if isinstance(tab, Mapping)
                    else (tab,)
                )
            )
        return tuple(cls._as_list(raw.get("children")))

    @staticmethod
    def _as_list(raw: object) -> list[object]:
        """Return ``raw`` as a list of wire objects, or empty when absent."""
        if isinstance(raw, list):
            return cast("list[object]", raw)
        return []
