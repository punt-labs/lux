"""``WireValue`` — one interaction's raw value, narrowed to the shape it must fit.

An interaction arrives off the wire as an untyped ``value``, and every typed
event's ``from_wire`` opens by insisting it is a particular shape: a scalar for a
value input, a string for a tab id, a mapping for a table selection. The
insistence is the same work each time — check, and on a mismatch raise a
``WrongKindError`` naming the element, what was expected, and what came — so it
lives here once instead of in a raise-block inside each event.

What an event expects stays the event's own knowledge: it names the shape in the
call. How the check is made, and how the failure is worded, is this module's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.interaction_errors import WrongKindError

if TYPE_CHECKING:
    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["WireMapping", "WireValue"]


@final
class WireValue:
    """A raw wire value that can narrow itself or say why it cannot."""

    _raw: object
    _scene_id: SceneId
    _element_id: ElementId
    __slots__ = ("_element_id", "_raw", "_scene_id")

    def __new__(cls, raw: object, *, scene_id: SceneId, element_id: ElementId) -> Self:
        self = super().__new__(cls)
        self._raw = raw
        self._scene_id = scene_id
        self._element_id = element_id
        return self

    def as_scalar(self, expected: str) -> bool | int | float | str:
        """Return the value as a JSON scalar, or raise ``WrongKindError``."""
        if isinstance(self._raw, bool | int | float | str):
            return self._raw
        raise self._wrong_kind(expected)

    def as_bool(self, expected: str) -> bool:
        """Return the value as a bool, or raise ``WrongKindError``."""
        if isinstance(self._raw, bool):
            return self._raw
        raise self._wrong_kind(expected)

    def as_str(self, expected: str) -> str:
        """Return the value as a string, or raise ``WrongKindError``."""
        if isinstance(self._raw, str):
            return self._raw
        raise self._wrong_kind(expected)

    def as_string_tuple(self, expected: str) -> tuple[str, ...]:
        """Return the value as a tuple of strings, or raise ``WrongKindError``."""
        raw = self._raw
        if isinstance(raw, list) and all(
            isinstance(item, str) for item in cast("list[object]", raw)
        ):
            return tuple(cast("list[str]", raw))
        raise self._wrong_kind(expected)

    def as_mapping(self, expected: str) -> WireMapping:
        """Return the value as a mapping whose fields narrow the same way."""
        raw = self._raw
        if not isinstance(raw, Mapping):
            raise self._wrong_kind(expected)
        return WireMapping(
            cast("Mapping[str, object]", raw),
            scene_id=self._scene_id,
            element_id=self._element_id,
        )

    def _wrong_kind(self, expected: str) -> WrongKindError:
        """Return the error naming the element, the shape wanted, and what came."""
        return WrongKindError(
            scene_id=self._scene_id,
            element_id=self._element_id,
            expected=expected,
            got=type(self._raw).__name__,
        )


@final
class WireMapping:
    """A wire payload mapping; each field narrows through its own ``WireValue``."""

    _raw: Mapping[str, object]
    _scene_id: SceneId
    _element_id: ElementId
    __slots__ = ("_element_id", "_raw", "_scene_id")

    def __new__(
        cls,
        raw: Mapping[str, object],
        *,
        scene_id: SceneId,
        element_id: ElementId,
    ) -> Self:
        self = super().__new__(cls)
        self._raw = raw
        self._scene_id = scene_id
        self._element_id = element_id
        return self

    def field(self, name: str, default: object = None) -> WireValue:
        """Return ``name``'s value, or ``default`` when the field is absent."""
        return WireValue(
            self._raw.get(name, default),
            scene_id=self._scene_id,
            element_id=self._element_id,
        )
