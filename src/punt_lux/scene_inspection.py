"""Typed introspection records for the enriched ``inspect_scene`` query.

The built-in ``inspect_scene`` returns each element's wire dict, which omits
defaulted fields and hides whether the element object is on the Element-ABC
path or the legacy dataclass path. These records add both signals so a
migration test can assert "this element flipped to the ABC path and its value
reads back" without inspecting pixels.

Honesty of scope (this runs on the DISPLAY process): ``render_path`` reads the
element object's type, and ``domain_mirror_present`` reads the display-side
domain ``Display`` mirror. Neither reads the Hub's authoritative
``HubDisplay`` (which lives in luxd) — that Hub-authority introspection is a
later batch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element as ElementABC
from punt_lux.domain.inspectable import Inspectable
from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.protocol.elements import element_to_dict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from punt_lux.protocol.elements import Element

__all__ = ["ElementInspection", "RenderPath", "SceneInspection"]

type RenderPath = Literal["abc", "legacy"]


class ElementInspection:
    """One element's render path, mirror presence, and resolved state.

    ``render_path`` is ``"abc"`` iff the element object is an Element-ABC
    subclass, else ``"legacy"`` — the load-bearing flip signal.

    ``domain_mirror_present`` is an HONEST display-side signal: whether the
    display-side dual-write pump routed this element into the display's domain
    ``Display`` mirror. It is NOT Hub authority; the display process cannot
    read the Hub's ``HubDisplay``.

    ``props`` is the fully-resolved state (including defaulted fields the wire
    dict omits) for migrated kinds; legacy kinds fall back to their wire dict.
    """

    _id: str
    _kind: str
    _render_path: RenderPath
    _domain_mirror_present: bool
    _props: Mapping[str, object]

    def __new__(
        cls,
        *,
        element_id: str,
        kind: str,
        render_path: RenderPath,
        domain_mirror_present: bool,
        props: Mapping[str, object],
    ) -> Self:
        self = super().__new__(cls)
        self._id = element_id
        self._kind = kind
        self._render_path = render_path
        self._domain_mirror_present = domain_mirror_present
        self._props = props
        return self

    @classmethod
    def from_element(cls, element: Element, *, domain_mirror_present: bool) -> Self:
        """Classify ``element`` and capture its resolved state."""
        render_path: RenderPath = "abc" if isinstance(element, ElementABC) else "legacy"
        props: Mapping[str, object] = (
            element.resolved_props()
            if isinstance(element, Inspectable)
            else element_to_dict(element)
        )
        return cls(
            element_id=element.id,
            kind=element.kind,
            render_path=render_path,
            domain_mirror_present=domain_mirror_present,
            props=props,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible ``element_paths`` record."""
        return {
            "id": self._id,
            "kind": self._kind,
            "render_path": self._render_path,
            "domain_mirror_present": self._domain_mirror_present,
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
    _mirror_ids: frozenset[str]

    def __new__(
        cls,
        *,
        scene_id: str,
        elements: tuple[Element, ...],
        mirror_ids: frozenset[str],
    ) -> Self:
        self = super().__new__(cls)
        self._scene_id = scene_id
        self._elements = elements
        self._mirror_ids = mirror_ids
        return self

    @classmethod
    def from_scene(
        cls,
        scene_id: str,
        elements: Sequence[Element],
        *,
        mirror_ids: frozenset[str],
    ) -> Self:
        """Build the inspection for ``scene_id`` and its elements."""
        return cls(
            scene_id=scene_id,
            elements=tuple(elements),
            mirror_ids=mirror_ids,
        )

    def to_dict(self) -> dict[str, object]:
        """Return the enriched ``inspect_scene`` response.

        ``element_paths`` recurses every container's children so a nested
        child's ``render_path`` is emitted too — a top-level ``"abc"`` group
        says nothing about whether its children also flipped.
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
        sink.append(
            ElementInspection.from_element(
                element, domain_mirror_present=element.id in self._mirror_ids
            ).to_dict()
        )
        if isinstance(element, HasChildElements):
            for child in element.child_elements():
                self._append_records(cast("Element", child), sink)
