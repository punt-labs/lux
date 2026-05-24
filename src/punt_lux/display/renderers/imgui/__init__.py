"""ImGui renderer adapter — surface-shared factory + per-kind adapters.

Per docs/oo-refactor/pr3-v2.1-design.md §2: the io-model RendererFactory
implementation that paints through ImGui. The factory owns
surface-shared state (``WidgetState``, ``TextureCache``, ``Emit``); each
per-kind adapter is a thin Renderer-Protocol satisfier that delegates to
the proven PR-2 renderer in ``display/renderers/``.

PR 3 ships ``ImGuiTextRenderer`` only. PRs 4-11 add per-kind adapters
for the other element families as each migrates to the io-model path.
"""

from __future__ import annotations

from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
from punt_lux.display.renderers.imgui.text import ImGuiTextRenderer

__all__ = ["ImGuiRendererFactory", "ImGuiTextRenderer"]
