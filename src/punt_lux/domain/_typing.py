"""Annotation introspection helpers used by Display.apply for SetProperty type checks.

Stateless utilities — they orbit no class in the domain package (PY-OO-7
exception #3: a primitives module).  Lifted out of display.py to keep that
module under the module_size target.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any, cast, get_args, get_origin

from punt_lux.domain.element import Element


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


__all__ = [
    "annotation_name",
    "annotation_runtime_types",
    "field_info",
    "replace_field",
    "value_matches",
]


def annotation_name(annotation: object) -> str:
    """Human-readable name for an annotation, for error messages."""
    return getattr(annotation, "__name__", str(annotation))


def annotation_runtime_types(annotation: object) -> tuple[type, ...]:
    """Flatten annotation to runtime types; raise on unsupported shapes (PY-EH-8)."""
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        out: list[type] = []
        for arg in get_args(annotation):
            out.extend(annotation_runtime_types(arg))
        return tuple(out)
    if origin is typing.Literal:
        # Literal["a", "b"] accepts whichever primitive types the literals are.
        literal_types: set[type] = {type(v) for v in get_args(annotation)}
        return tuple(literal_types)
    if annotation is type(None):
        return (type(None),)
    if isinstance(annotation, type):
        # JSON int → float parity (mirrors WireContext.require_number).
        return (float, int) if annotation is float else (annotation,)
    msg = f"unsupported annotation shape for runtime type extraction: {annotation!r}"
    raise TypeError(msg)


def value_matches(value: object, valid_types: tuple[type, ...]) -> bool:
    """Best-effort isinstance check across a union of runtime types."""
    if object in valid_types:
        return True
    # bool is a subclass of int — exclude unless explicitly allowed.
    if isinstance(value, bool) and bool not in valid_types and int in valid_types:
        return False
    return isinstance(value, valid_types)


def replace_field(elem: Element, field: str, value: object) -> Element:
    """Return a copy of ``elem`` with one field swapped (Protocol → Any cast)."""
    # cast to Any: dataclasses.replace's TypeVar can't narrow from Element Protocol.
    replaced = dataclasses.replace(cast("Any", elem), **{field: value})
    return cast("Element", replaced)
