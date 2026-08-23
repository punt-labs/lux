"""DataKeyMemo — bidirectional payload<->content-hash-key memo."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from punt_lux.display.data_key_memo import DataKeyMemo

if TYPE_CHECKING:
    import pytest


class TestKeyFor:
    def test_computes_and_memoizes_the_key(self) -> None:
        memo = DataKeyMemo()
        data = "some payload"
        expected = f"data:{hashlib.sha256(data.encode()).hexdigest()}"

        assert memo.key_for(data) == expected
        assert memo.key_for(data) == expected  # memoized, not recomputed
        assert len(memo) == 1

    def test_sha256_runs_once_across_repeated_key_for_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A persistent element asks for the same payload's key every frame;
        only the first sight pays the SHA-256, or a cached image would pay
        O(payload) per frame.
        """
        real_sha256 = hashlib.sha256
        hashes = {"n": 0}

        def _counting_sha256(payload: bytes = b"") -> object:
            hashes["n"] += 1
            return real_sha256(payload)

        monkeypatch.setattr(
            "punt_lux.display.data_key_memo.hashlib.sha256", _counting_sha256
        )
        memo = DataKeyMemo()
        data = "some payload"

        assert len({memo.key_for(data) for _ in range(3)}) == 1
        assert hashes["n"] == 1

    def test_distinct_payloads_get_distinct_keys(self) -> None:
        memo = DataKeyMemo()
        assert memo.key_for("a") != memo.key_for("b")
        assert len(memo) == 2

    def test_contains_reflects_the_forward_map(self) -> None:
        memo = DataKeyMemo()
        assert "a" not in memo
        memo.key_for("a")
        assert "a" in memo


class TestForget:
    def test_forgetting_a_known_key_drops_both_directions(self) -> None:
        memo = DataKeyMemo()
        key = memo.key_for("a")

        memo.forget(key)

        assert "a" not in memo
        assert len(memo) == 0
        assert len(memo._key_to_data) == 0

    def test_forgetting_recomputes_on_next_key_for(self) -> None:
        memo = DataKeyMemo()
        key_before = memo.key_for("a")
        memo.forget(key_before)

        key_after = memo.key_for("a")

        assert key_after == key_before  # same hash, but a fresh memo entry
        assert "a" in memo

    def test_forgetting_an_unknown_key_is_a_no_op(self) -> None:
        memo = DataKeyMemo()
        memo.key_for("a")

        memo.forget("data:not-a-real-key")

        assert "a" in memo
        assert len(memo) == 1


class TestClear:
    def test_clear_empties_both_directions(self) -> None:
        memo = DataKeyMemo()
        memo.key_for("a")
        memo.key_for("b")

        memo.clear()

        assert len(memo) == 0
        assert len(memo._key_to_data) == 0
