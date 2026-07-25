"""TextureCache — the data leg decodes/caches; malformed input degrades, never raises.

The OpenGL upload needs a live context the unit tier has no window for, so these
tests stub ``TextureCache._upload`` to a sentinel id and exercise the decode and
cache-keying around it. Malformed input fails before the upload, so it needs no
stub at all — which is exactly the property under test.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from PIL import Image

from punt_lux.display.texture_cache import TextureCache

if TYPE_CHECKING:
    import pytest


def _png_base64(size: tuple[int, int] = (2, 2)) -> str:
    """Return a real, decodable PNG as a base64 string."""
    buf = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 255)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestDataLeg:
    def test_valid_png_uploads_and_caches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        uploads = {"n": 0}

        def _fake_upload(_img: object) -> int:
            uploads["n"] += 1
            return 4242

        monkeypatch.setattr(TextureCache, "_upload", _fake_upload)
        cache = TextureCache()
        data = _png_base64()

        tex_id = cache.get_or_load_data(data)
        assert tex_id == 4242
        # A second load hits the content-keyed cache — no re-decode, no re-upload.
        assert cache.get_or_load_data(data) == 4242
        assert uploads["n"] == 1

    def test_same_payload_hashes_once_across_repeated_loads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The renderer reloads the same payload every frame; the SHA-256 that
        derives the content key runs on first sight only, then serves from the
        payload→key memo — otherwise a cached image pays O(payload) per frame.
        """

        def _fake_upload(_img: object) -> int:
            return 4242

        monkeypatch.setattr(TextureCache, "_upload", _fake_upload)
        real_sha256 = hashlib.sha256
        hashes = {"n": 0}

        def _counting_sha256(payload: bytes = b"") -> object:
            hashes["n"] += 1
            return real_sha256(payload)

        monkeypatch.setattr(
            "punt_lux.display.texture_cache.hashlib.sha256", _counting_sha256
        )
        cache = TextureCache()
        data = _png_base64()

        assert [cache.get_or_load_data(data) for _ in range(3)] == [4242, 4242, 4242]
        assert hashes["n"] == 1

    def test_bad_base64_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            tex_id = cache.get_or_load_data("!!! not valid base64 !!!")
        assert tex_id is None
        assert any("decode inline image" in r.getMessage() for r in caplog.records)

    def test_strictly_invalid_base64_degrades_and_logs_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A wrong-padding payload raises ``binascii.Error`` under
        ``validate=True``. ``binascii.Error`` is a ``ValueError``, so the data
        leg catches it and degrades: ``None``, remembered, decode warned once —
        the crash never reaches the render loop.
        """
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            first = cache.get_or_load_data("YWJjZA")
            second = cache.get_or_load_data("YWJjZA")
        assert (first, second) == (None, None)
        assert sum("decode inline image" in r.getMessage() for r in caplog.records) == 1

    def test_non_image_bytes_return_none_and_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        payload = base64.b64encode(b"these bytes are not an image").decode()
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            tex_id = cache.get_or_load_data(payload)
        assert tex_id is None
        assert any("decode inline image" in r.getMessage() for r in caplog.records)

    def test_distinct_payloads_key_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids: Iterator[int] = iter((1, 2))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        monkeypatch.setattr(TextureCache, "_upload", _fake_upload)
        cache = TextureCache()
        assert cache.get_or_load_data(_png_base64((2, 2))) == 1
        assert cache.get_or_load_data(_png_base64((3, 3))) == 2


class TestPathLeg:
    def test_missing_file_returns_none_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            tex_id = cache.get_or_load("/no/such/file/exists.png")
        assert tex_id is None
        assert any("not found" in r.getMessage() for r in caplog.records)


class TestNegativeCacheLogsOnce:
    """A broken source is decoded and logged exactly once, not every frame."""

    def test_missing_path_logs_once_across_repeated_loads(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            first = cache.get_or_load("/no/such/file.png")
            second = cache.get_or_load("/no/such/file.png")
        assert (first, second) == (None, None)
        assert sum("not found" in r.getMessage() for r in caplog.records) == 1

    def test_bad_data_logs_once_across_repeated_loads(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        payload = base64.b64encode(b"not an image").decode()
        cache = TextureCache()
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_cache"):
            first = cache.get_or_load_data(payload)
            second = cache.get_or_load_data(payload)
        assert (first, second) == (None, None)
        decode_warnings = [
            r.getMessage()
            for r in caplog.records
            if "decode inline image" in r.getMessage()
        ]
        assert len(decode_warnings) == 1
        # The warning carries identifying context: payload length and the reason
        # (never the payload itself), so a broken data URL is diagnosable.
        prefix = f"Failed to decode inline image data ({len(payload)} base64 chars): "
        assert decode_warnings[0].startswith(prefix)
        assert len(decode_warnings[0]) > len(prefix)
        assert payload not in decode_warnings[0]
