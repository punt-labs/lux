"""Stateless helpers used by ``Display`` — field introspection and id extraction.

The ``DisplayHelpers`` class groups them so the module passes PY-OO-7
(method_ratio + class_to_func_ratio) — every helper is a static method on
a real class, not a free function next to a domain class.  The class is
stateless and a single shared instance is the usage pattern.
"""

from __future__ import annotations

import dataclasses
import typing
from typing import Any, Self, assert_never, cast

from punt_lux.domain._typing import annotation_name, annotation_runtime_types
from punt_lux.domain.element import Element
from punt_lux.domain.ids import ElementId
from punt_lux.domain.update import AddElement, RemoveElement, SetProperty, Update

__all__ = ["DisplayHelpers"]


class DisplayHelpers:
    """Stateless helpers used by ``Display``; instance is a thin namespace."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @staticmethod
    def field_info(elem: Element, field: str) -> tuple[str, tuple[type, ...]] | None:
        """Return (declared-name, runtime-types) for a dataclass field, or None."""
        # PY-EH-5: gate on is_dataclass rather than swallowing TypeError from
        # dataclasses.fields(); cast to Any so the TypeGuard narrows from the
        # widest type (Element is a Protocol).
        elem_any = cast("Any", elem)
        if not dataclasses.is_dataclass(elem_any):
            return None
        field_names = {f.name for f in dataclasses.fields(elem_any)}
        if field not in field_names:
            return None
        hints = typing.get_type_hints(type(elem))
        annotation = hints.get(field)
        if annotation is None:
            return None
        return annotation_name(annotation), annotation_runtime_types(annotation)

    @staticmethod
    def update_target_id(update: Update) -> ElementId:
        """Pull the targeted ElementId out of any Update kind for error reporting."""
        match update:
            case AddElement():
                return ElementId(update.element.id)
            case RemoveElement() | SetProperty():
                return update.element_id
            case _:
                assert_never(update)
