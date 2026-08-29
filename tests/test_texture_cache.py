"""TextureCache — the data leg decodes/caches; malformed input degrades, never raises.

The OpenGL upload needs a live context the unit tier has no window for, so these
tests stub ``GLTexture.upload`` to a sentinel id and exercise the decode and
cache-keying around it. Malformed input fails before the upload, so it needs no
stub at all — which is exactly the property under test.
"""

from __future__ import annotations

import base64
import io
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING

from PIL import Image

from punt_lux.display.gl_texture import GLTexture
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

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        cache = TextureCache()
        data = _png_base64()

        tex_id = cache.get_or_load_data(data)
        assert tex_id == 4242
        # A second load hits the content-keyed cache — no re-decode, no re-upload.
        assert cache.get_or_load_data(data) == 4242
        assert uploads["n"] == 1

    def test_repeated_loads_of_the_same_payload_hit_the_key_memo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The renderer reloads the same payload every frame; the content-hash
        key memoization (``DataKeyMemo``, tested directly for its own
        once-only SHA-256 guarantee) means repeated loads of the same payload
        never re-decode or re-upload.
        """
        uploads = {"n": 0}

        def _fake_upload(_img: object) -> int:
            uploads["n"] += 1
            return 4242

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        cache = TextureCache()
        data = _png_base64()

        assert [cache.get_or_load_data(data) for _ in range(3)] == [4242, 4242, 4242]
        assert uploads["n"] == 1

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

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
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


class TestLruEviction:
    """The cache caps at ``LUX_TEXTURE_CACHE_CAP`` entries under LRU eviction."""

    def test_cache_respects_cap_under_repeated_inserts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "3")
        ids: Iterator[int] = iter(range(100))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        def _noop_delete(_tex_id: int) -> None:
            return None

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        monkeypatch.setattr(GLTexture, "delete", staticmethod(_noop_delete))
        cache = TextureCache()

        for size in range(10):
            cache.get_or_load_data(_png_base64((size + 1, size + 1)))

        assert len(cache) == 3

    def test_lru_order_recent_access_renews_position(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Touching the oldest entry keeps it alive; the untouched one is evicted."""
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "2")
        ids: Iterator[int] = iter(range(100))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        deleted: list[int] = []
        monkeypatch.setattr(GLTexture, "delete", staticmethod(deleted.append))
        cache = TextureCache()

        payload_a = _png_base64((1, 1))
        payload_b = _png_base64((2, 2))
        payload_c = _png_base64((3, 3))

        cache.get_or_load_data(payload_a)  # tex id 0
        cache.get_or_load_data(payload_b)  # tex id 1
        # Touch A again — B is now the LRU entry, not A.
        cache.get_or_load_data(payload_a)
        cache.get_or_load_data(payload_c)  # evicts B (id 1), not A

        key_a = cache._data_keys.key_for(payload_a)
        key_c = cache._data_keys.key_for(payload_c)
        assert [d for d in deleted if d is not None] == [1]
        assert list(cache._lru.keys()) == [key_a, key_c]

    def test_gl_delete_fires_on_eviction_with_correct_tex_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "1")
        ids: Iterator[int] = iter((11, 22))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        deleted: list[int] = []
        monkeypatch.setattr(GLTexture, "delete", staticmethod(deleted.append))
        cache = TextureCache()

        cache.get_or_load_data(_png_base64((1, 1)))
        cache.get_or_load_data(_png_base64((2, 2)))

        assert [d for d in deleted if d is not None] == [11]

    def test_none_entries_evict_alongside_real_textures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "2")
        cache = TextureCache()

        cache.get_or_load("/no/such/file/one.png")
        cache.get_or_load("/no/such/file/two.png")
        cache.get_or_load("/no/such/file/three.png")

        assert len(cache) == 2
        assert "/no/such/file/one.png" not in cache._lru

    def test_failure_none_entries_do_not_trigger_a_real_gl_delete_on_eviction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Evicting a failure record calls ``GLTexture.delete(None)`` (a no-op) —
        never with a real texture id, since a failed load never uploaded one.
        """
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "1")
        deleted: list[int | None] = []
        monkeypatch.setattr(GLTexture, "delete", staticmethod(deleted.append))
        cache = TextureCache()

        cache.get_or_load("/no/such/file/one.png")
        cache.get_or_load("/no/such/file/two.png")

        assert [d for d in deleted if d is not None] == []


class TestDataKeysBounded:
    """``_data_keys`` (a ``DataKeyMemo``) is coupled to ``_lru`` eviction —
    bounded by the same cap as the textures, not left to grow for the
    process lifetime.
    """

    def test_data_keys_bounded_by_cap_under_repeated_distinct_payloads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "3")
        ids: Iterator[int] = iter(range(100))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        def _noop_delete(_tex_id: int | None) -> None:
            return None

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        monkeypatch.setattr(GLTexture, "delete", staticmethod(_noop_delete))
        cache = TextureCache()

        for size in range(10):
            cache.get_or_load_data(_png_base64((size + 1, size + 1)))

        assert len(cache._data_keys) == 3
        assert len(cache._data_keys._key_to_data) == 3

    def test_evicted_payload_re_decodes_and_re_uploads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once a data-keyed entry is evicted, its payload memo is gone too —
        loading the same payload again is a fresh decode/upload, not a hit.
        """
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "1")
        ids: Iterator[int] = iter((1, 2, 3))

        def _fake_upload(_img: object) -> int:
            return next(ids)

        def _noop_delete(_tex_id: int | None) -> None:
            return None

        monkeypatch.setattr(GLTexture, "upload", _fake_upload)
        monkeypatch.setattr(GLTexture, "delete", staticmethod(_noop_delete))
        cache = TextureCache()

        payload_a = _png_base64((1, 1))
        payload_b = _png_base64((2, 2))

        assert cache.get_or_load_data(payload_a) == 1
        assert payload_a in cache._data_keys
        cache.get_or_load_data(payload_b)  # evicts A's data-key memo too
        assert payload_a not in cache._data_keys

        assert cache.get_or_load_data(payload_a) == 3  # re-decoded, re-uploaded

    def test_path_keyed_entries_never_touch_data_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "5")
        cache = TextureCache()

        cache.get_or_load("/no/such/file/one.png")
        cache.get_or_load("/no/such/file/two.png")

        assert len(cache._data_keys) == 0
        assert len(cache._data_keys._key_to_data) == 0


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
