"""ImGui renderer adapters — surface-shared factory + per-kind adapters.

The RendererFactory implementation that paints through ImGui. The factory
owns surface-shared state (``WidgetState``, ``TextureCache``, ``Emit``);
each per-kind adapter is a thin Renderer-Protocol satisfier
(``begin``/``paint``/``end``) reached via the factory. Text, button, and
checkbox are leaves that paint through ``ElementRenderer``'s per-kind
renderers; the dialog opens a modal and draws its child Buttons through the
unified button path.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.button import ImGuiButtonRenderer
from punt_lux.display.renderers.imgui.checkbox import ImGuiCheckboxRenderer
from punt_lux.display.renderers.imgui.dialog import ImGuiDialogRenderer
from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer

__all__ = [
    "ImGuiButtonRenderer",
    "ImGuiCheckboxRenderer",
    "ImGuiDialogRenderer",
    "ImGuiRendererFactory",
    "ImGuiTextRenderer",
]
