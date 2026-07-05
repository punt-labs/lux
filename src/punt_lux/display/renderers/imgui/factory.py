"""ImGuiRendererFactory — surface-shared mediator for ImGui per-kind renderers.

The production RendererFactory. Constructed once at Display startup and
bound onto received elements by the Display's post-receive rebind
(``Element.bind_renderer_factory``) — not threaded through elements at
decode. Holds the Display-tier surface-shared state (``WidgetState``,
``TextureCache``, ``Emit``) and dispatches by element type to the per-kind
adapter, which receives the factory so it stays the single mediator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.checkbox import CheckboxElement
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.element_renderer import ElementRenderer
    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.protocol.renderer import Emit, Renderer
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiRendererFactory"]


class ImGuiRendererFactory:
    """Resolve an Element to its ImGui Renderer adapter."""

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit
    _element_renderer: ElementRenderer

    # Element type -> adapter constructor. One table both dispatches
    # ``__call__`` and sizes the introspection ``migrated_kind_count``.
    # Every adapter shares the ``(elem, factory)`` constructor shape.
    _DISPATCH: ClassVar[tuple[tuple[type, Callable[..., Renderer]], ...]] = (
        (TextElement, ImGuiTextRenderer),
        (ButtonElement, ImGuiButtonRenderer),
        (CheckboxElement, ImGuiCheckboxRenderer),
        (DialogElement, ImGuiDialogRenderer),
    )

    def __new__(
        cls,
        *,
        widget_state: WidgetState,
        texture_cache: TextureCache,
        emit: Emit,
        element_renderer: ElementRenderer,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._texture_cache = texture_cache
        self._emit = emit
        self._element_renderer = element_renderer
        return self

    @property
    def widget_state(self) -> WidgetState:
        """Return the per-scene widget state the factory mediates access to."""
        return self._widget_state

    @property
    def texture_cache(self) -> TextureCache:
        """Return the texture cache shared across renderers."""
        return self._texture_cache

    @property
    def emit(self) -> Emit:
        """Return the Display-tier emit channel (a no-op; clicks route to Hub)."""
        return self._emit

    @property
    def element_renderer(self) -> ElementRenderer:
        """Return the ElementRenderer that owns the per-kind renderers.

        The adapters paint through its ``text_renderer`` / ``button_renderer``
        / ``checkbox_renderer`` (per-scene widget_state) and its shared
        ``apply_tooltip`` post-processing.
        """
        return self._element_renderer

    @property
    def migrated_kind_count(self) -> int:
        """Return how many element kinds paint through this factory.

        Introspection's ``element_kinds`` total adds this to the legacy
        ``ElementRenderer`` count so pruning the migrated kinds from the
        legacy dispatch leaves the reported total unchanged.
        """
        return len(self._DISPATCH)

    def __call__(self, elem: object) -> Renderer:
        """Return the ImGui adapter for ``elem``, or raise if unsupported."""
        for element_type, adapter in self._DISPATCH:
            if isinstance(elem, element_type):
                return adapter(elem, self)
        msg = f"no imgui renderer for {type(elem).__name__}"
        raise ValueError(msg)
