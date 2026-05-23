"""Per-surface RendererFactory families.

Per io-model.md §"The Renderer family":
- Hub tier: NullRendererFactory (no render loop on the Hub).
- Display tier: TextRendererFactory or RecordingRendererFactory (one is chosen at startup).
"""
