"""Import-light registry of migrated Element-ABC kind names.

The container gate decides "is my whole subtree migrated-ABC?" from wire
dicts alone, without importing any element class — the aggregator imports the
container codecs to build the element union, and those codecs import the gate,
so a gate that imported element classes would close a cycle. The kind *names*
are therefore held here as plain strings and consumed both by the gate and by
the ABC registry's import-time cross-check.

This is one of the two data homes for "which kinds are on the ABC path": the
light string set here, and the heavier class-bearing ``AbcElementRegistry``.
The layering forbids merging them, so they are reconciled with a fail-loud
cross-check when the default registry is built.
"""

from __future__ import annotations

from typing import ClassVar, Self

__all__ = ["AbcKindNames"]


class AbcKindNames:
    """The wire-``kind`` strings of every migrated Element-ABC kind.

    Strings only — this class imports no element class, so the container gate
    can consult it without risking a circular import. ``is_container`` names
    the conditionally-ABC containers whose subtree must itself be all-ABC.
    """

    __slots__ = ()

    MIGRATED_ABC_KINDS: ClassVar[frozenset[str]] = frozenset(
        {
            "text",
            "button",
            "checkbox",
            "dialog",
            "progress",
            "input_text",
            "input_number",
            "slider",
            "color_picker",
            "combo",
            "group",
            "collapsing_header",
            "tab_bar",
        }
    )

    ABC_CONTAINER_KINDS: ClassVar[frozenset[str]] = frozenset(
        {"group", "collapsing_header", "tab_bar"}
    )

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @classmethod
    def is_migrated(cls, kind: object) -> bool:
        """Return whether ``kind`` decodes onto an Element-ABC class.

        A non-str ``kind`` (including an unhashable wire value like ``{}`` or
        ``[]``) returns ``False`` — the validated boundary (PY-EH-1), so the
        container gate fails closed rather than raising ``TypeError`` on the
        ``in`` membership test.
        """
        return isinstance(kind, str) and kind in cls.MIGRATED_ABC_KINDS

    @classmethod
    def is_container(cls, kind: object) -> bool:
        """Return whether ``kind`` is a conditionally-ABC container kind.

        A non-str ``kind`` returns ``False`` — see :meth:`is_migrated`.
        """
        return isinstance(kind, str) and kind in cls.ABC_CONTAINER_KINDS
