"""ImGui renderer adapter — surface-shared factory + per-kind adapters.

The RendererFactory implementation that paints through ImGui. The
factory owns surface-shared state (``WidgetState``, ``TextureCache``,
``Emit``); each per-kind adapter is a thin Renderer-Protocol satisfier
that delegates to the underlying renderer in ``display/renderers/``.

``ImGuiTextRenderer`` only for now. Per-kind adapters for the other
element families are added as each gains a dedicated renderer.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer

__all__ = ["ImGuiRendererFactory", "ImGuiTextRenderer"]
