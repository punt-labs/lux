"""ImageRenderer texture resolution — data blobs paint; a bad blob warns, no crash.

``render`` itself issues ImGui calls that need a frame, so these tests exercise
``_resolve_texture`` — the branch that picks the cache leg and logs the
element-named warning — with the cache's legs stubbed. The path leg stays a plain
delegation to ``get_or_load``.
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

    def test_data_source_decode_failure_warns_with_id_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()

        def _load_data(_data: str) -> int | None:
            return None

        monkeypatch.setattr(cache, "get_or_load_data", _load_data)
        renderer = ImageRenderer(cache)
        elem = ImageElement(id="broken-img", data="bad")

        with caplog.at_level(
            logging.WARNING, logger="punt_lux.display.renderers.image_renderer"
        ):
            tex_id = renderer._resolve_texture(elem)

        assert tex_id is None
        assert any("broken-img" in r.getMessage() for r in caplog.records)

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
