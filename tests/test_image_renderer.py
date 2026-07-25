"""ImageRenderer texture resolution — the source picks its cache leg, no crash.

``render`` itself issues ImGui calls that need a frame, so these tests exercise
``_resolve_texture`` — which delegates to the source's loader leg — with the
cache's legs stubbed. The renderer itself never logs: a failed load returns
``None`` (the cache logged it once) and render() degrades to alt text.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display.renderers.image_renderer import ImageRenderer
from punt_lux.display.texture_cache import TextureCache
from punt_lux.protocol.elements.image import ImageElement

if TYPE_CHECKING:
    import pytest


class TestResolveTexture:
    def test_data_source_success_returns_texture_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()

        def _load_data(_data: str) -> int:
            return 99

        monkeypatch.setattr(cache, "get_or_load_data", _load_data)
        renderer = ImageRenderer(cache)
        elem = ImageElement(id="img1", data="Zm9v")

        with caplog.at_level(logging.WARNING):
            tex_id = renderer._resolve_texture(elem)

        assert tex_id == 99
        assert not caplog.records

    def test_data_source_failure_returns_none_without_renderer_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()

        def _load_data(_data: str) -> int | None:
            return None

        monkeypatch.setattr(cache, "get_or_load_data", _load_data)
        renderer = ImageRenderer(cache)
        elem = ImageElement(id="broken-img", data="bad")

        # The renderer degrades to alt text; the cache owns the log-once warning,
        # so the renderer itself never logs (no per-frame spam).
        with caplog.at_level(logging.WARNING):
            tex_id = renderer._resolve_texture(elem)

        assert tex_id is None
        assert not caplog.records

    def test_path_source_delegates_to_path_leg(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()
        seen: dict[str, str] = {}

        def _load_path(path: str) -> int:
            seen["path"] = path
            return 7

        monkeypatch.setattr(cache, "get_or_load", _load_path)
        renderer = ImageRenderer(cache)
        elem = ImageElement(id="img1", path="/tmp/a.png")

        # A path source never routes through the data leg, so it never warns.
        with caplog.at_level(logging.WARNING):
            tex_id = renderer._resolve_texture(elem)

        assert tex_id == 7
        assert seen["path"] == "/tmp/a.png"
        assert not caplog.records
