"""WindowElement — a display-only floating sub-window on the Element ABC.

``GroupElement`` with window chrome: it owns an ordered tuple of ABC children and
draws them inside a movable, resizable ImGui sub-window. There is no model, no
dismiss verb, and — deliberately — no close affordance: a window element is
in-scene content, not the workspace frame, so it carries no Hub-authoritative
open/closed state and declares no remote interaction (ratified Decision 3/c). Its
drag, resize, and collapse are Display-local ephemeral state the Hub never tracks;
the element keeps only the initial :class:`WindowPlacement` an agent seeds and the
:class:`WindowFlags` that disable behaviours.

Tree position governs an element's LIFECYCLE, never its GEOMETRY. ImGui's
``begin`` always creates a top-level window, so a window floats top-level whatever
it nests in — its parent scopes when it is shown and removed, not where it draws.
Nested in a plain container it renders as a legal-but-legacy on-screen escapee;
nested in a *modal* it is incoherent (the modal blocks its own escaped child) and
forbidden — see ``ModalElement.validate``. Use a group or collapsing_header for a
panel that must stay inside its parent's box.

The codec body lives in ``window_codec.py``; ``to_dict`` / ``from_dict`` remain
here as thin delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied, mirroring the ``Group`` split precedent (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.window_chrome import WindowFlags, WindowPlacement
from punt_lux.protocol.elements.window_codec import JsonWindowDecoder, JsonWindowEncoder

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["WindowElement"]

# Frozen value objects — one shared default each (safe to share; immutable).
_DEFAULT_PLACEMENT = WindowPlacement()
_DEFAULT_FLAGS = WindowFlags()


class WindowElement(Element):
    """A floating sub-window that arranges its ABC children inside itself.

    Holds only ABC children — the render template calls ``child.render()``, which
    only ABC elements provide; the decoder guarantees this by decoding a
    ``window`` onto this class only when its entire subtree is migrated-ABC.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip.
    """

    _id: str
    _title: str
    _placement: WindowPlacement
    _flags: WindowFlags
    _children_tuple: tuple[Element, ...]
    _tooltip: str | None
    _kind: Literal["window"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        title: str = "",
        placement: WindowPlacement = _DEFAULT_PLACEMENT,
        flags: WindowFlags = _DEFAULT_FLAGS,
        children: Iterable[Element] = (),
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._title = title
        self._placement = placement
        self._flags = flags
        self._children_tuple = tuple(children)
        self._tooltip = tooltip
        self._kind = "window"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the window's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["window"]:
        """Return the wire discriminator — always ``"window"``."""
        return self._kind

    @property
    def title(self) -> str:
        """Return the window's title-bar text."""
        return self._title

    @property
    def placement(self) -> WindowPlacement:
        """Return the initial placement; live drag/resize is Display-local."""
        return self._placement

    @property
    def flags(self) -> WindowFlags:
        """Return the set of disabled window behaviours."""
        return self._flags

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the window's body children (read-only view)."""
        return self._children_tuple

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    # ``_children()``, ``child_elements``, ``remove_child`` and factory
    # rebinding come from the Element ABC, backed by ``_children_tuple``. A
    # window declares no ``_remote_dispatch_specs`` — it has no close affordance
    # and no interaction, so ``wrap_handlers_for_remote`` finds nothing to wrap.

    # -- minimal setters for the scene patch path --------------------------

    def _set_title(self, value: object) -> None:
        """Replace the window title."""
        self._title = PatchField("title").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    # -- self-validation ---------------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return one error when the placement cannot be drawn.

        Drawability (finite x/y and finite positive width/height) is the
        placement's own invariant — see :meth:`WindowPlacement.is_drawable`.
        """
        p = self._placement
        if p.is_drawable():
            return ()
        message = (
            f"window requires finite x/y and finite positive width/height, got "
            f"x={p.x} y={p.y} {p.width}x{p.height}"
        )
        return (ValidationError(self._id, self._kind, message),)

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonWindowEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a WindowElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher, which rejects
        an unknown child kind (PY-EH-1).
        """
        decoder = JsonWindowDecoder(decode_element=dispatch.from_dict, element_cls=cls)
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including composed chrome."""
        return {
            "title": self._title,
            **self._placement.to_wire(),
            "flags": list(self._flags.active_names()),
            "children": [child.id for child in self._children_tuple],
            "tooltip": self._tooltip,
        }
