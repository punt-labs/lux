"""Unit tests for the ``Snapshot`` class."""

from __future__ import annotations

from pathlib import Path

import pytest

from .snapshot import Snapshot


@pytest.fixture
def sample_snapshot() -> Snapshot:
    return Snapshot(
        tool="show",
        inputs=(("scene_id", "s1"), ("elements", [{"kind": "text", "id": "t1"}])),
        setup={"display_running": True, "client": {"show": {"return": "ack:s1"}}},
        response="ack:s1",
    )


class TestRoundtrip:
    def test_to_file_then_from_file(
        self, tmp_path: Path, sample_snapshot: Snapshot
    ) -> None:
        path = tmp_path / "snap.json"
        sample_snapshot.to_file(path)
        assert Snapshot.from_file(path) == sample_snapshot

    def test_to_file_is_pretty_printed(
        self, tmp_path: Path, sample_snapshot: Snapshot
    ) -> None:
        path = tmp_path / "snap.json"
        sample_snapshot.to_file(path)
        text = path.read_text(encoding="utf-8")
        assert "\n" in text  # pretty printed, not single-line
        assert text.endswith("\n")  # trailing newline for POSIX-friendly diffs


class TestMatches:
    def test_exact_match(self, sample_snapshot: Snapshot) -> None:
        assert sample_snapshot.matches("ack:s1")

    def test_exact_mismatch(self, sample_snapshot: Snapshot) -> None:
        assert not sample_snapshot.matches("ack:s2")

    def test_ts_token_matches_decimal(self) -> None:
        snap = Snapshot(tool="ping", inputs=(), setup={}, response="pong rtt=<TS>s")
        assert snap.matches("pong rtt=0.042s")
        assert snap.matches("pong rtt=123.0s")

    def test_pid_token_matches_integer(self) -> None:
        snap = Snapshot(
            tool="screenshot",
            inputs=(),
            setup={},
            response="/tmp/lux-screenshot-<PID>.png",
        )
        assert snap.matches("/tmp/lux-screenshot-12345.png")

    def test_token_rejects_non_numeric(self) -> None:
        snap = Snapshot(tool="ping", inputs=(), setup={}, response="pong rtt=<TS>s")
        assert not snap.matches("pong rtt=abcs")

    def test_response_with_regex_metacharacters_is_escaped(self) -> None:
        # Tool responses that happen to contain regex metacharacters (e.g.,
        # JSON braces) must compare as literal text, not as regex.
        snap = Snapshot(
            tool="inspect_scene",
            inputs=(("scene_id", "s1"),),
            setup={},
            response='{"scene_id": "s1", "elements": []}',
        )
        assert snap.matches('{"scene_id": "s1", "elements": []}')
        assert not snap.matches('{"scene_id": "s2", "elements": []}')


class TestDiff:
    def test_diff_empty_on_match(self, sample_snapshot: Snapshot) -> None:
        # diff() is for failure reporting; it's permitted to be empty when
        # there is no difference.
        assert sample_snapshot.diff("ack:s1") == ""

    def test_diff_shows_change(self, sample_snapshot: Snapshot) -> None:
        diff = sample_snapshot.diff("ack:s2")
        assert "show (recorded)" in diff
        assert "show (observed)" in diff
        assert "ack:s1" in diff
        assert "ack:s2" in diff
