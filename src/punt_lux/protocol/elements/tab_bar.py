"""TabBarElement — an interactive tabbed container on the Element ABC.

The harder of the two simple composites: a container (like ``GroupElement``)
composed with a single Hub-authoritative view-selection (like ``CheckboxElement``)
whose value is a stable ``tab_id`` rather than a bool. Every tab's children are
installed and cross the wire; only the active tab is drawn. A user click fires
``TabChanged`` carrying the clicked tab's id (never a positional index), which
routes to the Hub; the Hub mirrors the new ``active_tab`` and re-pushes.

Because the selection names a stable id, reconciliation on a structural change is
a membership check: an added tab leaves the selection unchanged, a removed active
tab resets to the first live tab, a relabel is a no-op. The invariant
``_active_tab`` is ``""`` or names a live tab is maintained on every mutation and
asserted in ``validate()``.

The codec body lives in ``tab_bar_codec.py``; ``to_dict`` / ``from_dict`` stay
here as short delegators (PY-OO-2).
"""

from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.container_interaction import TabChanged
from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.tab import Tab
from punt_lux.protocol.elements.tab_bar_codec import (
    JsonTabBarDecoder,
    JsonTabBarEncoder,
)
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.renderer import TabContainerRenderer
from punt_lux.protocol.standalone_tab_bar_handler import (
    build_standalone_tab_bar_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, Renderer, RendererFactory

__all__ = ["Tab", "TabBarElement"]


class TabBarElement(Element):
    """A tabbed container that owns a Hub-authoritative active-tab selection.

    Holds only ABC children — the render template calls ``child.render()``,
    which only ABC elements provide. The decoder decodes a ``tab_bar`` onto this
    class only when its entire subtree is migrated-ABC; any legacy descendant
    routes the whole subtree to the legacy form.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip.
    """

    _id: str
    _tabs: tuple[Tab, ...]
    _active_tab: str
    _tooltip: str | None
    _kind: Literal["tab_bar"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        tabs: Iterable[Tab] = (),
        active_tab: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._tabs = tuple(tabs)
        self._active_tab = active_tab
        self._tooltip = tooltip
        self._kind = "tab_bar"
        self._reconcile_active_tab()
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the tab bar's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["tab_bar"]:
        """Return the wire discriminator — always ``"tab_bar"``."""
        return self._kind

    @property
    def tabs(self) -> tuple[Tab, ...]:
        """Return the ordered tabs (read-only view)."""
        return self._tabs

    @property
    def active_tab(self) -> str:
        """Return the Hub-authoritative active tab's id, or ``""`` if none."""
        return self._active_tab

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    @property
    def children(self) -> tuple[Element, ...]:
        """Return every tab's children flattened — the Composite contract."""
        return self._children()

    # -- composite surface --------------------------------------------------

    def _children(self) -> tuple[Element, ...]:
        """Return every tab's children flattened — all cross the wire.

        Only the active tab is *drawn*, but every tab's children are installed,
        so the remote-dispatch wrap, factory rebind, and validation walk reach
        them.
        """
        return tuple(chain.from_iterable(tab.children for tab in self._tabs))

    def _render_children(self, renderer: Renderer) -> None:
        """Bracket each tab and gate its body on the Hub-authoritative selection.

        The domain class must not call ImGui (PY-IC-8); it delegates the tab
        brackets to the ``TabContainerRenderer`` and passes ``_active_tab`` in —
        the renderer honours the selection, it does not invent one. A plain
        ``Renderer`` (no ``begin_tab``/``end_tab``) is rejected here at the
        boundary, not deep in the loop with an opaque ``AttributeError``.
        """
        if not isinstance(renderer, TabContainerRenderer):
            msg = (
                f"tab_bar {self._id!r} requires a TabContainerRenderer "
                f"(begin_tab/end_tab), got {type(renderer).__name__}"
            )
            raise TypeError(msg)
        for tab in self._tabs:
            selected = renderer.begin_tab(tab, active=self._active_tab)
            try:
                if selected:
                    for child in tab.children:
                        child.render()
            finally:
                renderer.end_tab(opened=selected)

    # -- minimal setters for the scene patch path --------------------------

    def _set_active_tab(self, value: object) -> None:
        """Replace the active-tab selection, reconciled to name a live tab.

        Reconciling on every mutation (see ``_reconcile_active_tab``), not only
        at construction, stops a patch naming a stale tab from installing a
        dangling selection that would fire a spurious ``TabChanged``.
        """
        self._active_tab = PatchField("active_tab").as_str(value)
        self._reconcile_active_tab()

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _reconcile_active_tab(self) -> None:
        """Keep ``_active_tab`` naming a live tab after the tab set changes.

        A selection that still names a present tab is kept; a selection whose
        tab was removed resets to the first tab; an empty tab set clears it.
        """
        if self._active_tab not in {tab.tab_id for tab in self._tabs}:
            self._active_tab = self._tabs[0].tab_id if self._tabs else ""

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the tab-changed bucket's spec under the element-id action."""
        return (RemoteDispatchSpec(TabChanged, self.id, "tab_changed"),)

    # -- self-validation ---------------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return errors for empty labels, duplicate ids, or a dangling active tab.

        Every tab needs a non-empty label (an unclickable tab otherwise); tab
        ids must be unique (the selection names a tab by id); and a non-empty
        ``_active_tab`` must name a live tab (the reconciliation invariant).
        """
        errors: list[ValidationError] = []
        seen: set[str] = set()
        for index, tab in enumerate(self._tabs):
            if not tab.label:
                errors.append(self._error(f"tab {index} has an empty label"))
            if tab.tab_id in seen:
                errors.append(self._error(f"duplicate tab id {tab.tab_id!r}"))
            seen.add(tab.tab_id)
        if self._active_tab and self._active_tab not in seen:
            errors.append(self._error(f"active_tab {self._active_tab!r} names no tab"))
        return tuple(errors)

    def _error(self, message: str) -> ValidationError:
        """Build a tab_bar ValidationError carrying this element's identity."""
        return ValidationError(
            element_id=self._id, element_kind=self._kind, message=message
        )

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTabBarEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TabBarElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher and rejects a
        wire dict whose subtree is not all-ABC — the invariant belongs at this
        type's own boundary (PY-EH-1). A wire ``publish`` handler resolves
        against a ``RaisingPublishSink`` so a stray publish fails loud.
        """
        if not ContainerAbcGate.is_all_abc(d):
            offending = ContainerAbcGate.first_non_abc_kind(d)
            bar_id = d.get("id")
            msg = f"tab_bar {bar_id!r} is not all-ABC — offending kind: {offending!r}"
            raise ValueError(msg)
        decoder = JsonTabBarDecoder(
            decode_element=dispatch.from_dict,
            element_cls=cls,
            handler_decoder=build_standalone_tab_bar_handler_decoder(
                cast("PublishSink", RaisingPublishSink("TabBarElement.from_dict")),
            ),
        )
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including the active-tab view-state."""
        return {
            "tabs": [
                {
                    "tab_id": tab.tab_id,
                    "label": tab.label,
                    "children": [child.id for child in tab.children],
                }
                for tab in self._tabs
            ],
            "active_tab": self._active_tab,
            "tooltip": self._tooltip,
        }
