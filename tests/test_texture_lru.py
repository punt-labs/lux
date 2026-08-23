"""TextureLru — an ordered, capped index with least-recently-used eviction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display.texture_lru import TextureLru

if TYPE_CHECKING:
    import pytest


class TestCapFromEnv:
    def test_default_cap_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUX_TEXTURE_CACHE_CAP", raising=False)
        assert TextureLru._cap_from_env() == 256

    def test_valid_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "10")
        assert TextureLru._cap_from_env() == 10

    def test_non_integer_falls_back_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "not-a-number")
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_lru"):
            cap = TextureLru._cap_from_env()
        assert cap == 256
        assert any("is not an integer" in r.getMessage() for r in caplog.records)

    def test_non_positive_falls_back_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "0")
        with caplog.at_level(logging.WARNING, logger="punt_lux.display.texture_lru"):
            cap = TextureLru._cap_from_env()
        assert cap == 256
        assert any("must be >= 1" in r.getMessage() for r in caplog.records)


class TestRememberAndEvict:
    def test_under_cap_never_evicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "5")
        lru = TextureLru()
        for i in range(3):
            assert lru.remember(f"k{i}", i) is None
        assert len(lru) == 3

    def test_over_cap_evicts_oldest_untouched_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "2")
        lru = TextureLru()
        assert lru.remember("a", 1) is None
        assert lru.remember("b", 2) is None
        assert lru.remember("c", 3) == ("a", 1)  # evicts "a", tex id 1
        assert list(lru.keys()) == ["b", "c"]

    def test_touch_renews_position_and_protects_from_eviction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "2")
        lru = TextureLru()
        lru.remember("a", 1)
        lru.remember("b", 2)
        lru.touch("a")  # "b" is now the LRU entry
        assert lru.remember("c", 3) == ("b", 2)  # evicts "b", tex id 2
        assert list(lru.keys()) == ["a", "c"]

    def test_none_entries_evict_and_report_no_texture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "1")
        lru = TextureLru()
        lru.remember("a", None)
        assert lru.remember("b", 5) == ("a", None)  # evicts "a", no texture to delete

    def test_contains_and_getitem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "5")
        lru = TextureLru()
        lru.remember("a", 1)
        assert "a" in lru
        assert lru["a"] == 1

    def test_clear_empties_the_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUX_TEXTURE_CACHE_CAP", "5")
        lru = TextureLru()
        lru.remember("a", 1)
        lru.clear()
        assert len(lru) == 0
        assert "a" not in lru
