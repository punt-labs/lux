"""ImGui renderer adapters — the RendererFactory and per-kind adapters.

Kept import-light on purpose: the package ``__init__`` re-exports nothing, so
importing a helper submodule (``color_channel_strip``, ``continuous_edit_*``)
never boots the factory. Consumers import the factory from its own module
(``punt_lux.display.renderers.imgui.factory``), which breaks the import cycle
the stateless continuous-edit renderers would otherwise close.
"""

from __future__ import annotations

__all__: list[str] = []
