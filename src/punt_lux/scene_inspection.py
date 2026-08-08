"""Typed introspection records for the enriched ``inspect_scene`` query.

The built-in ``inspect_scene`` returns each element's wire dict, which omits
defaulted fields. These records add the fully-resolved state so a test can
assert "this element's value reads back" without inspecting pixels. This runs
on the DISPLAY process, so it reads the display's own render state, not the
Hub's authoritative ``HubDisplay`` (which lives in luxd).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.protocol.elements import element_to_dict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.protocol.elements import Element

__all__ = ["ElementInspection", "SceneInspection"]


class ElementInspection:
    """One element's resolved state.

    ``props`` is the fully-resolved state, including defaulted fields the wire
    dict omits.
    """

    _id: str
    _kind: str
    _props: Mapping[str, object]

    def __new__(
        cls,
        *,
        element_id: str,
        kind: str,
        props: Mapping[str, object],
    ) -> Self:
        self = super().__new__(cls)
        self._id = element_id
        self._kind = kind
        self._props = props
        return self

    @classmethod
    def from_element(cls, element: Element) -> Self:
        """Capture ``element``'s resolved state."""
        return cls(
            element_id=element.id,
            kind=element.kind,
            props=element.resolved_props(),
        )

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible ``element_paths`` record."""
        return {
            "id": self._id,
            "kind": self._kind,
            "props": dict(self._props),
        }


class SceneInspection:
    """A scene's inspection: the existing ``elements`` array plus paths.

    ``to_dict`` emits the built-in ``elements`` list byte-for-byte (so
    existing consumers are untouched) alongside the new ``element_paths``
    array of per-element :class:`ElementInspection` records.
    """

    _scene_id: str
    _elements: tuple[Element, ...]

    def __new__(
        cls,
        *,
        scene_id: str,
        elements: tuple[Element, ...],
    ) -> Self:
        self = super().__new__(cls)
        self._scene_id = scene_id
        self._elements = elements
        return self

    @classmethod
    def from_scene(cls, scene_id: str, elements: Sequence[Element]) -> Self:
        """Build the inspection for ``scene_id`` and its elements."""
        return cls(scene_id=scene_id, elements=tuple(elements))

    def to_dict(self) -> dict[str, object]:
        """Return the enriched ``inspect_scene`` response.

        ``element_paths`` recurses every container's children so a nested
        child's props are emitted too — a top-level element's resolution says
        nothing about whether its children were also resolved.
        """
        records: list[dict[str, object]] = []
        for element in self._elements:
            self._append_records(element, records)
        return {
            "scene_id": self._scene_id,
            "elements": [element_to_dict(e) for e in self._elements],
            "element_paths": records,
        }

    def _append_records(self, element: Element, sink: list[dict[str, object]]) -> None:
        """Append ``element``'s record, then recurse into its children."""
        sink.append(ElementInspection.from_element(element).to_dict())
        for child in element.child_elements():
            self._append_records(cast("Element", child), sink)
